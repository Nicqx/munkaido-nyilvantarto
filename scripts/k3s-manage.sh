#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
OVERLAY_DIR="$ROOT_DIR/k8s/overlays/nuc"
HOST_DATA_DIR="/var/lib/munkaido-nyilvantarto/data"
HOST_DATABASE="$HOST_DATA_DIR/munkaido.db"
IMAGE="munkaido-nyilvantarto:latest"
NAMESPACE="default"
DEPLOYMENT="munkaido-nyilvantarto"
SERVICE="munkaido-nyilvantarto"
TARGET=""
DRY_RUN=0

usage() {
  echo "Használat: $0 {migrate|update|status|start|stop|backup} --target nuc [--dry-run]" >&2
  exit 2
}

[[ $# -ge 1 ]] || usage
COMMAND="$1"
shift
while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)
      [[ $# -ge 2 ]] || usage
      TARGET="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    *) usage ;;
  esac
done

[[ "$TARGET" == "nuc" ]] || { echo "HIBA: ez a telepítés kizárólag a nuc célgépre készült." >&2; exit 1; }
case "$COMMAND" in
  migrate|update|status|start|stop|backup) ;;
  *) usage ;;
esac
if [[ "$DRY_RUN" == 1 && ! "$COMMAND" =~ ^(migrate|update)$ ]]; then
  echo "HIBA: a --dry-run csak migrate és update művelethez használható." >&2
  exit 1
fi

read -r -a KUBECTL_BIN <<< "${KUBECTL:-kubectl}"
read -r -a K3S_BIN <<< "${K3S:-sudo k3s}"

kube() {
  "${KUBECTL_BIN[@]}" --request-timeout=30s "$@"
}

verify_cluster() {
  local node_name architecture ready_count node_count
  node_count="$(kube get nodes -o jsonpath='{.items[*].metadata.name}' | wc -w)"
  node_name="$(kube get nodes -o jsonpath='{.items[0].metadata.name}')"
  architecture="$(kube get nodes -o jsonpath='{.items[0].status.nodeInfo.architecture}')"
  ready_count="$(kube get nodes -o jsonpath='{range .items[0].status.conditions[?(@.type=="Ready")]}{.status}{end}')"
  [[ "$node_count" == 1 && "$node_name" == "nuc" && "$architecture" == "amd64" && "$ready_count" == "True" ]] || {
    echo "HIBA: a kube-context nem az egy node-os, Ready állapotú amd64 nuc clusterre mutat." >&2
    exit 1
  }
}

require_config() {
  [[ -f "$ROOT_DIR/.env" ]] || {
    echo "HIBA: hiányzik a $ROOT_DIR/.env; a meglévő Docker-konfigurációt meg kell őrizni." >&2
    exit 1
  }
  [[ -s "$ROOT_DIR/.env" ]] || { echo "HIBA: a .env üres." >&2; exit 1; }
}

validate_manifests() {
  kube apply --dry-run=server -k "$OVERLAY_DIR" >/dev/null
  echo "Kubernetes szerveroldali manifest-ellenőrzés: rendben."
}

build_and_import_image() {
  local image_tar
  image_tar="$(mktemp --suffix=.tar)"
  trap 'rm -f -- "$image_tar"' RETURN
  docker build --pull -t "$IMAGE" "$ROOT_DIR"
  docker save "$IMAGE" -o "$image_tar"
  "${K3S_BIN[@]}" ctr images import "$image_tar" >/dev/null
  rm -f -- "$image_tar"
  trap - RETURN
}

apply_secret() {
  local secret_manifest
  secret_manifest="$(mktemp)"
  trap 'rm -f -- "$secret_manifest"' RETURN
  kube create secret generic munkaido-config \
    -n "$NAMESPACE" \
    --from-env-file="$ROOT_DIR/.env" \
    --dry-run=client -o yaml >"$secret_manifest"
  kube apply -f "$secret_manifest" >/dev/null
  rm -f -- "$secret_manifest"
  trap - RETURN
}

wait_ready() {
  kube rollout status "deployment/$DEPLOYMENT" -n "$NAMESPACE" --timeout=180s
  local pod
  pod="$(kube get pod -n "$NAMESPACE" -l app.kubernetes.io/name="$DEPLOYMENT" -o jsonpath='{.items[0].metadata.name}')"
  kube exec -n "$NAMESPACE" "$pod" -c web -- \
    python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5).read()" >/dev/null
  kube get endpointslice -n "$NAMESPACE" -l kubernetes.io/service-name="$SERVICE" \
    -o jsonpath='{range .items[*].endpoints[*]}{.conditions.ready}{"\n"}{end}' | grep -qx True
}

pod_name() {
  kube get pod -n "$NAMESPACE" -l app.kubernetes.io/name="$DEPLOYMENT" \
    -o jsonpath='{.items[0].metadata.name}'
}

backup_from_pod() {
  local stamp destination pod remote
  stamp="$(date +%Y%m%dT%H%M%S)"
  destination="$ROOT_DIR/backups/munkaido-k3s-$stamp.db"
  remote="/tmp/munkaido-backup-$stamp.db"
  pod="$(pod_name)"
  mkdir -p "$ROOT_DIR/backups"
  kube exec -n "$NAMESPACE" "$pod" -c web -- \
    python /app/scripts/db_tool.py backup /app/data/munkaido.db "$remote" >/dev/null
  kube cp -n "$NAMESPACE" -c web "$pod:$remote" "$destination"
  kube exec -n "$NAMESPACE" "$pod" -c web -- \
    python -c "from pathlib import Path; Path('$remote').unlink(missing_ok=True)" >/dev/null
  chmod 600 "$destination"
  python3 "$ROOT_DIR/scripts/db_tool.py" check "$destination" >/dev/null
  echo "$destination"
}

case "$COMMAND" in
  status)
    verify_cluster
    docker compose -f "$ROOT_DIR/compose.yaml" ps 2>/dev/null || true
    kube get deployment,pod,service,pvc -n "$NAMESPACE" \
      -l app.kubernetes.io/name="$DEPLOYMENT" -o wide
    exit 0
    ;;
  stop)
    verify_cluster
    kube scale deployment "$DEPLOYMENT" -n "$NAMESPACE" --replicas=0
    exit 0
    ;;
  start)
    verify_cluster
    kube scale deployment "$DEPLOYMENT" -n "$NAMESPACE" --replicas=1
    wait_ready
    exit 0
    ;;
  backup)
    verify_cluster
    backup_from_pod
    exit 0
    ;;
esac

verify_cluster
require_config
validate_manifests

if [[ "$COMMAND" == "migrate" ]]; then
  [[ -f "$ROOT_DIR/data/munkaido.db" ]] || {
    echo "HIBA: nem található a Docker adatbázisa: $ROOT_DIR/data/munkaido.db" >&2
    exit 1
  }
  python3 "$ROOT_DIR/scripts/db_tool.py" check "$ROOT_DIR/data/munkaido.db" >/dev/null
  if kube get pvc munkaido-data -n "$NAMESPACE" --ignore-not-found -o name | grep -q .; then
    echo "HIBA: a munkaido-data PVC már létezik; meglévő k3s telepítéshez az update parancs való." >&2
    exit 1
  fi
  if sudo test -e "$HOST_DATABASE"; then
    echo "HIBA: a céladatbázis már létezik: $HOST_DATABASE. Nem írjuk felül." >&2
    exit 1
  fi
fi

if [[ "$DRY_RUN" == 1 ]]; then
  echo "Dry-run kész: Docker és k3s állapot nem változott."
  exit 0
fi

build_and_import_image
apply_secret

if [[ "$COMMAND" == "update" ]]; then
  if kube get deployment "$DEPLOYMENT" -n "$NAMESPACE" --ignore-not-found -o name | grep -q .; then
    echo "Frissítés előtti mentés: $(backup_from_pod)"
  fi
  kube apply -k "$OVERLAY_DIR"
  kube rollout restart "deployment/$DEPLOYMENT" -n "$NAMESPACE"
  wait_ready
  echo "Frissítés kész. Elérés: https://pmqxyz.hopto.org/munkaido/"
  exit 0
fi

docker_was_running=0
migration_finished=0
rollback_migration() {
  local exit_code=$?
  if [[ "$migration_finished" != 1 ]]; then
    echo "A k3s migráció megszakadt; a k3s példányt leállítjuk." >&2
    kube scale deployment "$DEPLOYMENT" -n "$NAMESPACE" --replicas=0 >/dev/null 2>&1 || true
    if [[ "$docker_was_running" == 1 ]]; then
      docker compose -f "$ROOT_DIR/compose.yaml" start munkaido >/dev/null 2>&1 || true
      echo "A korábbi Docker-példány újraindítását megkíséreltük." >&2
    fi
  fi
  exit "$exit_code"
}
trap rollback_migration ERR INT TERM

if [[ -n "$(docker compose -f "$ROOT_DIR/compose.yaml" ps --status running -q munkaido 2>/dev/null)" ]]; then
  docker_was_running=1
  docker compose -f "$ROOT_DIR/compose.yaml" stop munkaido
fi

mkdir -p "$ROOT_DIR/backups"
stamp="$(date +%Y%m%dT%H%M%S)"
source_backup="$ROOT_DIR/backups/munkaido-pre-k3s-$stamp.db"
python3 "$ROOT_DIR/scripts/db_tool.py" backup "$ROOT_DIR/data/munkaido.db" "$source_backup" >/dev/null
source_summary="$(python3 "$ROOT_DIR/scripts/db_tool.py" check "$source_backup")"

sudo install -d -o 10001 -g 10001 -m 0750 "$HOST_DATA_DIR"
sudo install -o 10001 -g 10001 -m 0600 "$source_backup" "$HOST_DATABASE"
source_hash="$(sha256sum "$source_backup" | awk '{print $1}')"
target_hash="$(sudo sha256sum "$HOST_DATABASE" | awk '{print $1}')"
[[ "$source_hash" == "$target_hash" ]] || {
  echo "HIBA: a hosttárhelyre másolt adatbázis ellenőrzőösszege eltér." >&2
  exit 1
}

kube apply -k "$OVERLAY_DIR"
wait_ready
pod="$(pod_name)"
target_summary="$(kube exec -n "$NAMESPACE" "$pod" -c web -- python /app/scripts/db_tool.py check /app/data/munkaido.db)"
[[ "$source_summary" == "$target_summary" ]] || {
  echo "HIBA: a migrált adatbázis rekordszámai eltérnek." >&2
  exit 1
}

migration_finished=1
trap - ERR INT TERM
echo "Migráció kész; a korábbi Docker-példány leállítva maradt."
echo "Biztonsági mentés: $source_backup"
echo "Következő lépés az ingress repóban: publish-munkaido --target nuc"
