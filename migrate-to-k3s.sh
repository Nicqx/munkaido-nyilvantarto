#!/usr/bin/env bash
set -euo pipefail
exec "$(dirname -- "${BASH_SOURCE[0]}")/scripts/k3s-manage.sh" migrate "$@"
