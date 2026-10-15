# Munkaidő-nyilvántartó

Verzió: **1.5.0**

Az 1.5.0-s verzió passkey/WebAuthn alapú biometrikus belépést ad az
alkalmazáshoz. A beállítás után a felhasználónév és a jelszó beírása nélkül,
a telefon ujjlenyomat-, arc- vagy képernyőzár-ellenőrzésével lehet belépni.
Maga a biometrikus adat nem kerül az alkalmazásba vagy az adatbázisba.

Az 1.4.0-s verzió megtartja a Docker Compose futtatást, és hozzáadja a NUC-on
futó k3s telepítést, a meglévő SQLite-adatok leállításos migrációját, az
automatikus frissítés előtti mentést, valamint a Traefik `/munkaido/` prefix
helyes kezelését.

Az 1.3.0-s verzióban az alkalmazás saját Excel-exportja közvetlenül vissza is tölthető. Az import alapból nem írja felül a már meglévő napokat, de ez külön bekapcsolható.

Mobiltelefonon és asztali gépen használható, Dockerben futó munkaidő-nyilvántartó.

Fő funkciók:

- regisztráció és belépés;
- felhasználónév nélküli biometrikus passkey-belépés;
- másodperc pontos érkezés és távozás;
- „Megérkeztem most” és „Távoztam most” gyorsgomb;
- „Kiszaladok / Visszaértem” szünetmérés;
- múltbeli napok szerkesztése;
- felhasználónkénti, saját maguk által is szerkeszthető heti beosztás;
- a kijelölt hét üres munkanapjainak automatikus pótlása;
- havi és éves túlóra-egyenleg;
- teljes és fél nap szabadság;
- éves szabadságkeret;
- magyar munkaszüneti napok és munkanap-áthelyezések;
- adminisztrátori jelszó-visszaállítás;
- adminisztrátori felhasználónév-módosítás és teljes fióktörlés;
- egymással azonos formátumú Excel-export és -import;
- az átadott 2026-os Excel-adatok automatikus, egyszeri importálása.

## Belépési adatok

A konkrét admin- és importált felhasználói belépési adatokat a helyi `.env` fájl tartalmazza, amelyet a Git nem tölt fel. Új telepítésnél az első indítás előtt legalább az `ADMIN_PASSWORD`, az Excel-import használatakor pedig a `SEED_USER_LOGIN` és `SEED_USER_PASSWORD` értékét is meg kell adni.

A jelszó-visszaállításkor használt érték a `DEFAULT_USER_PASSWORD` beállítás. Minden felhasználó megváltoztathatja a saját jelszavát.

Már működő telepítés frissítésekor a meglévő adminfiók, felhasználók és jelszavak változatlanul megmaradnak.

## Biometrikus belépés

Az első passkey beállításához egyszer még jelszóval kell belépni, majd:

1. nyisd meg a `Fiók` menüpontot;
2. adj nevet a készüléknek, és nyomd meg a `Passkey hozzáadása` gombot;
3. hagyd jóvá a telefon vagy a számítógép biometrikus/képernyőzáras kérését;
4. a következő kijelentkezés után válaszd a `Belépés biometriával` gombot.

A passkey úgynevezett felfedezhető hitelesítő adat, ezért belépéskor a
készülék választja ki a hozzá tartozó fiókot: sem a felhasználónevet, sem a
jelszót nem kell kitölteni. Több készülékhez külön passkey adható, és ezek a
`Fiók` oldalon egyenként törölhetők. A jelszavas belépés és az adminisztrátori
jelszó-visszaállítás tartalék lehetőségként megmarad.

A WebAuthn normál hálózati címen HTTPS-t igényel. A k3s telepítés ehhez a
`https://pmqxyz.hopto.org` origint és a `pmqxyz.hopto.org` RP ID-t használja.
Helyi Docker-próbánál a böngésző `http://localhost:1985` címét kell használni;
ezt a `WEBAUTHN_ORIGIN` és `WEBAUTHN_RP_ID` beállítások szabályozzák.

## Követelmények

- Docker Engine;
- Docker Compose v2;
- a gépen szabad `1985` TCP-port.

## Első indítás

1. Csomagold ki a ZIP-fájlt.
2. Lépj be a könyvtárba:

   ```bash
   cd munkaido-nyilvantarto
   ```

3. Készítsd el a konfigurációs fájlt:

   ```bash
   cp .env.example .env
   ```

4. Az `.env` fájlban:

   - az `APP_SECRET` értékét cseréld tetszőleges hosszú szövegre;
   - új adatbázis esetén add meg az `ADMIN_PASSWORD` értékét;
   - az Excel-importhoz add meg a `SEED_USER_LOGIN`, `SEED_USER_DISPLAY_NAME` és `SEED_USER_PASSWORD` értékét;
   - a jelszó-visszaállításhoz add meg a `DEFAULT_USER_PASSWORD` értékét.
   - helyi passkey-használathoz hagyd meg a `WEBAUTHN_ORIGIN=http://localhost:1985`
     és `WEBAUTHN_RP_ID=localhost` értékeket; publikus HTTPS-címnél ezeket a
     tényleges domainhez kell igazítani.

   A saját `.env` fájlt ne töltsd fel nyilvános Git-tárolóba.
5. Indítsd el:

   ```bash
   docker compose up -d --build
   ```

6. Ellenőrizd az állapotot:

   ```bash
   docker compose ps
   docker compose logs --tail=100
   ```

A szolgáltatás helyi címe:

```text
http://A-SZERVER-IP-CÍME:1985
```

Ugyanazon a gépen:

```text
http://localhost:1985
```

## Leállítás és újraindítás

Leállítás:

```bash
docker compose stop
```

Újraindítás:

```bash
docker compose start
```

Konténer eltávolítása az adatok megtartásával:

```bash
docker compose down
```

A `docker compose down` nem törli a `data/munkaido.db` fájlt.

## Frissítés

Az új programfájlok bemásolása után:

```bash
docker compose down
docker compose up -d --build
```

Az adatbázis a gazdagépen, a `data` könyvtárban van, ezért a konténer újraépítése nem törli.

## Biztonsági mentés

Az alkalmazást érdemes a másolás idejére leállítani:

```bash
docker compose stop
cp data/munkaido.db backups/munkaido-$(date +%Y-%m-%d-%H%M%S).db
docker compose start
```

Az SQLite a működés során `munkaido.db-wal` és `munkaido.db-shm` segédfájlokat is használhat. A fenti leállítás biztosítja, hogy a fő adatbázisfájl önmagában konzisztens legyen.

## Visszaállítás mentésből

1. Állítsd le az alkalmazást:

   ```bash
   docker compose down
   ```

2. Nevezd át a jelenlegi adatbázist, hogy szükség esetén visszaállítható maradjon:

   ```bash
   mv data/munkaido.db data/munkaido.db.elotte
   ```

3. Másold vissza a kiválasztott mentést:

   ```bash
   cp backups/A-KIVALASZTOTT-MENTES.db data/munkaido.db
   ```

4. Indítsd el:

   ```bash
   docker compose up -d
   ```

## Adatbázis és kezdeti Excel-import

Az adatbázis helye:

```text
./data/munkaido.db
```

Az első induláskor a `seed/Kimutatas_a_ledolgozott_munkaidorol.xlsx` tartalma egyszer kerül a helyi `.env` fájlban megadott importfelhasználóhoz. Az alkalmazás megjegyzi az importálás tényét, ezért újraindításkor nem duplikálja az adatokat.

Az adminfelületen törölt fiókot az alkalmazás újraindításkor sem hozza létre ismét.

A 2026. július 27-i hibás Excel-sort szándékosan érkezés és távozás nélkül importálja. A felületen „Hiányzó adat” jelzést kap, és addig nem módosítja az egyenleget, amíg kézzel ki nem javítják.

A július 1-jei Excel-beállítás változatlan marad: az importált elvárt idő `00:00:00`.

Ha teljesen üres adatbázissal szeretnél indulni, még az első indítás előtt írd ezt az `.env` fájlba:

```text
IMPORT_SEED_EXCEL=0
```

## Kézi Excel-export és -import

A `Statisztika` oldalon letöltött `.xlsx` fájl egyben a hivatalos importsablon is. A fájl az `Import` menüpontban tölthető vissza, mindig a belépett felhasználó adataihoz.

Az importálható mezők a `Munkaidőadatok` munkalap első nyolc oszlopában vannak:

| Oszlop | Tartalom |
|---|---|
| Dátum | A munkanap dátuma |
| Nap | Tájékoztató napnév; importáláskor nem ez határozza meg a dátumot |
| Típus | Munkanap, egész/fél nap szabadság vagy nem számolt nap |
| Érkezés | Óra, perc, másodperc |
| Távozás | Óra, perc, másodperc |
| Kint töltött idő | A ledolgozott időből levonandó összes idő |
| Egyedi elvárt idő | Csak az adott napra érvényes felülírás; üresen a heti beosztás számít |
| Megjegyzés | Szabad szöveges megjegyzés |

A további oszlopok számított értékek, az alkalmazás importálás után újraszámolja őket. Az `Éves összesítő` munkalapon szereplő szabadságkeret szintén átvehető. A heti beosztást az import nem módosítja.

Két ütközéskezelés választható:

- `Maradjanak változatlanok`: ez az alapértelmezett és ajánlott mód; a már létező dátumokat kihagyja;
- `Írja felül őket`: az Excelben szereplő dátumok korábbi adatait lecseréli.

A teljes fájlt az alkalmazás mentés előtt ellenőrzi. Ha akár egy importálandó sor hibás, sem a munkanapok, sem a szabadságkeretek nem változnak. Egy fájl legfeljebb 8 MB és 5000 munkanap lehet. A korábbi, 1.2.0-s alkalmazásból letöltött exportok is visszatölthetők.

## Munkaidő-számítás

```text
Ledolgozott idő = távozás − érkezés − összes kint töltött idő
Napi egyenleg = ledolgozott idő − elvárt idő
```

Új felhasználók kezdeti heti beosztása:

| Nap | Érkezés | Távozás | Elvárt idő |
|---|---:|---:|---:|
| Hétfő | 08:00:00 | 18:00:00 | 10:00:00 |
| Kedd | 08:00:00 | 16:00:00 | 08:00:00 |
| Szerda | 08:00:00 | 16:30:00 | 08:30:00 |
| Csütörtök | 08:00:00 | 16:00:00 | 08:00:00 |
| Péntek | 08:00:00 | 13:30:00 | 05:30:00 |
| Szombat | — | — | 00:00:00 |
| Vasárnap | — | — | 00:00:00 |

A felhasználó a „Beosztás” menüpontban saját magának, az admin pedig az adminfelületen bármelyik felhasználónak módosíthatja ezt. Az elvárt idő az érkezés és távozás különbségéből számolódik. Ha egy nap mindkét időpontja üres, az a felhasználó alapbeosztásában szabadnap; ezért hétvégi munkarend is megadható.

### Heti automatikus pótlás

A napi rögzítés oldalán a kijelölt dátum teljes hetéhez elérhető a „Hét üres napjainak kitöltése” gomb. A funkció:

- csak a hét kezdetétől a mai napig dolgozik, jövőbeli napot nem tölt ki;
- a felhasználó saját alapértelmezett érkezési és távozási idejét írja be;
- a meglévő vagy részben kitöltött napokat nem módosítja;
- a szabadságot, ünnepnapot, pihenőnapot és a beosztás szerinti szabadnapot kihagyja;
- egyszerre mindig csak a kijelölt hetet kezeli, ezért régebbi időszakok biztonságosan, hetenként pótolhatók.

Az importált egyedi elvárt idők változatlanok maradnak.

Nincs automatikus ebédszünet-levonás. A „Kiszaladok” funkcióval mért idő csökkenti a ledolgozott időt.

## Szabadság

- Egész nap szabadság: az adott nap nem számít bele sem a ledolgozott, sem az elvárt időbe; a keretből 1 nap fogy.
- Fél nap szabadság: az elvárt napi munkaidő fele marad; a keretből 0,5 nap fogy.
- A délelőtti és délutáni fél nap számítása azonos, de a kimutatásban külön megnevezéssel látszik.
- A szabadság előre is rögzíthető.
- A statisztika külön mutatja az eddig kivett és a jövőre tervezett napokat.

## Munkanap-áthelyezések

Az alkalmazás ismeri a magyar munkaszüneti napokat. A 2026-os hivatalos munkanap-áthelyezések előre be vannak állítva.

Az áthelyezett szombat az eredeti nap felhasználói munkaidő-beosztását örökli. Például ha egy pénteket helyeznek át szombatra, akkor az alapbeosztás szerint 5 óra 30 perc lesz az elvárt idő.

Az admin a `Admin → Munkanaptár` oldalon további napokat vehet fel vagy módosíthat.

## Hálózati elérés

A konténer a gép `1985` portján érhető el. Routeres porttovábbítás esetén ezt a portot kell a Docker-gépre irányítani.

Az alkalmazás nem tartalmaz saját HTTPS-kiszolgálót. Nyilvános interneten a
Traefikhez hasonló HTTPS reverse proxy szükséges; a biometrikus passkey-belépés
HTTP-n nem működik. Az adatbázisban a jelszavak egyirányú hash formában, a
passkeyk pedig nyilvános kulcsként szerepelnek.

## K3s telepítés és a Docker-adatok migrációja

A NUC-os telepítés egyetlen példányt futtat a `default` namespace-ben:

- `Deployment/munkaido-nyilvantarto`, `Recreate` frissítési stratégiával;
- `Service/munkaido-nyilvantarto`, belső `8000` porttal;
- statikus `PersistentVolume/munkaido-data-pv`, `Retain` házirenddel;
- `PersistentVolumeClaim/munkaido-data`;
- az adatbázis tényleges hostútvonala:
  `/var/lib/munkaido-nyilvantarto/data/munkaido.db`.

Az adat ezért pod- és Deployment-frissítéskor nem törlődik. A PV szándékosan
a `nuc` node-hoz kötött. A PVC/PV törlése sem törli automatikusan a hoston lévő
adatbázist, de kézi törlés előtt mindig készüljön külön mentés.

### 1. Előzetes, módosítás nélküli ellenőrzés

A repo és a jelenlegi `.env`, illetve `data/munkaido.db` ugyanazon a NUC-on
legyen, ahol a k3s fut. A `.env` nem kerül Kubernetes manifestbe vagy Gitbe;
a migráció helyben készít belőle `Secret/munkaido-config` erőforrást.

```bash
cd ~/codes/munkaido-nyilvantarto
git pull --ff-only
chmod +x migrate-to-k3s.sh update.sh scripts/k3s-manage.sh scripts/db_tool.py

KUBECTL='sudo k3s kubectl' \
K3S='sudo k3s' \
./migrate-to-k3s.sh --target nuc --dry-run
```

A dry-run ellenőrzi:

- hogy a kube-context az egy node-os, Ready állapotú `nuc`/AMD64 cluster;
- hogy megvan a `.env` és a Docker-adatbázis;
- hogy az SQLite `quick_check` sikeres;
- hogy a k3s API elfogadja a Kustomize manifesteket;
- hogy nincs már korábbi `munkaido-data` PVC vagy céladatbázis.

Nem állít le konténert, nem épít image-et és nem ír a clusterbe.

### 2. Leállítás és adatköltöztetés

```bash
KUBECTL='sudo k3s kubectl' \
K3S='sudo k3s' \
./migrate-to-k3s.sh --target nuc
```

A script a következő sorrendet tartja:

1. helyben felépíti és a k3s containerd-be importálja az AMD64 image-et;
2. elkészíti a Kubernetes Secretet a meglévő `.env` fájlból;
3. ha fut, csak a `munkaido` Docker Compose szolgáltatást állítja le;
4. a SQLite backup API-val konzisztens, `0600` jogosultságú mentést készít a
   `backups/munkaido-pre-k3s-<időpont>.db` fájlba;
5. a mentést a megtartott hosttárhelyre másolja;
6. telepíti a PV/PVC/Deployment/Service erőforrásokat;
7. ellenőrzi a másolat SHA-256 ellenőrzőösszegét, a rolloutot, a health
   endpointot, a Ready EndpointSlice-ot és a felhasználó-, munkaidő- és
   szabadságrekordok számát.

Ha a folyamat a sikeres ellenőrzés előtt hibázik, a k3s Deploymentet nullára
állítja, és a korábban futó Docker-példány újraindítását megkísérli. Az eredeti
`data/munkaido.db` fájlt nem módosítja és nem törli.

Ha a hiba már a PV/PVC létrehozása után történt, ezeket és a céladatbázist ne
töröld. A hiba javítása és egy új `git pull --ff-only` után a migráció külön,
ellenőrzött folytatási móddal indítható:

```bash
KUBECTL='sudo k3s kubectl' \
K3S='sudo k3s' \
./scripts/k3s-manage.sh resume --target nuc
```

A `resume` csak létező PVC, létező céladatbázis és nullára skálázott k3s
Deployment mellett fut. Ismét leállítja a közben visszaindított Docker-példányt,
friss mentést készít annak aktuális adatbázisáról, ellenőrzött másolatot ír a
k3s tárhelyre, majd újra elvégzi a teljes rollout- és adatellenőrzést.

### 3. HTTPS útvonal publikálása

A sikeres alkalmazásmigráció után az `ingress` repóban:

```bash
cd ~/codes/ingress
git pull --ff-only

KUBECTL='sudo k3s kubectl' \
python3 scripts/manage.py publish-munkaido --target nuc --dry-run

KUBECTL='sudo k3s kubectl' \
python3 scripts/manage.py publish-munkaido --target nuc
```

Az eredmény:

```text
https://pmqxyz.hopto.org/munkaido/
```

A központi ingress a `/munkaido` előtagot levágja, és
`X-Forwarded-Prefix: /munkaido` fejlécet ad. Az alkalmazás ezt csak a k3s
telepítésben bízza meg, így a generált linkek, űrlapok és statikus fájlok címei
továbbra is a `/munkaido/` útvonalon maradnak.

Az új útvonal ugyanazt a 443-as Traefik/TLS bejáratot használja, mint a többi
alkalmazás. Sikeres külső próba után a router régi 1985-ös porttovábbítása
megszüntethető.

### K3s frissítés, mentés és vezérlés

Frissítés előtt a script konzisztens adatbázismentést készít, újraépíti és
importálja az image-et, frissíti a helyi Secretet, majd megvárja az új podot:

```bash
KUBECTL='sudo k3s kubectl' K3S='sudo k3s' ./update.sh --target nuc --dry-run
KUBECTL='sudo k3s kubectl' K3S='sudo k3s' ./update.sh --target nuc
```

További műveletek:

```bash
KUBECTL='sudo k3s kubectl' ./scripts/k3s-manage.sh status --target nuc
KUBECTL='sudo k3s kubectl' ./scripts/k3s-manage.sh backup --target nuc
KUBECTL='sudo k3s kubectl' ./scripts/k3s-manage.sh stop --target nuc
KUBECTL='sudo k3s kubectl' ./scripts/k3s-manage.sh start --target nuc
```

A `stop` csak nullára skálázza a Deploymentet; sem a PVC-t, sem az adatot nem
törli. A régi Docker Compose konténer a sikeres migráció után leállítva marad,
így gyors visszalépési lehetőségként még rendelkezésre áll. Csak a k3s és a
HTTPS útvonal teljes ellenőrzése után indokolt a `docker compose down`.

## Hibaelhárítás

Naplók:

```bash
docker compose logs -f
```

Újraépítés gyorsítótár nélkül:

```bash
docker compose build --no-cache
docker compose up -d
```

Portfoglalás ellenőrzése Linuxon:

```bash
sudo ss -ltnp | grep ':1985'
```

Adatbázis jogosultsági hiba esetén:

```bash
ls -la data
```

Az alkalmazás health check végpontja:

```text
http://localhost:1985/health
```
