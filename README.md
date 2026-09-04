# Munkaidő-nyilvántartó

Mobiltelefonon és asztali gépen használható, Dockerben futó munkaidő-nyilvántartó.

Fő funkciók:

- regisztráció és belépés;
- másodperc pontos érkezés és távozás;
- „Megérkeztem most” és „Távoztam most” gyorsgomb;
- „Kiszaladok / Visszaértem” szünetmérés;
- múltbeli napok szerkesztése;
- havi és éves túlóra-egyenleg;
- teljes és fél nap szabadság;
- éves szabadságkeret;
- magyar munkaszüneti napok és munkanap-áthelyezések;
- adminisztrátori jelszó-visszaállítás;
- Excel-export;
- az átadott 2026-os Excel-adatok automatikus, egyszeri importálása.

## Első belépés

| Szerepkör | Felhasználónév | Jelszó |
|---|---|---|
| Admin | `admin` | `admin` |
| Importált adatok tulajdonosa | `sora.luna@gmail.com` | `Almafa.123` |

Az admin minden felhasználó jelszavát az `Almafa.123` alapértelmezett jelszóra tudja visszaállítani. Mindenki megváltoztathatja a saját jelszavát.

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

4. Az `.env` fájlban az `APP_SECRET` értékét ajánlott tetszőleges hosszú szövegre cserélni.
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

## Adatbázis és Excel-import

Az adatbázis helye:

```text
./data/munkaido.db
```

Az első induláskor a `seed/Kimutatas_a_ledolgozott_munkaidorol.xlsx` tartalma egyszer kerül be a `sora.luna@gmail.com` felhasználóhoz. Az alkalmazás megjegyzi az importálás tényét, ezért újraindításkor nem duplikálja az adatokat.

A 2026. július 27-i hibás Excel-sort szándékosan érkezés és távozás nélkül importálja. A felületen „Hiányzó adat” jelzést kap, és addig nem módosítja az egyenleget, amíg kézzel ki nem javítják.

A július 1-jei Excel-beállítás változatlan marad: az importált elvárt idő `00:00:00`.

Ha teljesen üres adatbázissal szeretnél indulni, még az első indítás előtt írd ezt az `.env` fájlba:

```text
IMPORT_SEED_EXCEL=0
```

## Munkaidő-számítás

```text
Ledolgozott idő = távozás − érkezés − összes kint töltött idő
Napi egyenleg = ledolgozott idő − elvárt idő
```

Alapértelmezett heti beosztás:

| Nap | Elvárt idő |
|---|---:|
| Hétfő | 10:00:00 |
| Kedd | 08:00:00 |
| Szerda | 08:30:00 |
| Csütörtök | 08:00:00 |
| Péntek | 05:30:00 |
| Szombat | 00:00:00 |
| Vasárnap | 00:00:00 |

Az admin ezt felhasználónként módosíthatja.

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

Az alkalmazás nem tartalmaz HTTPS-kiszolgálót. Nyilvános interneten a HTTP-forgalom titkosítatlan. Az adatbázisban a jelszavak egyirányú hash formában szerepelnek.

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
