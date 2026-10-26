# Védett, internetről elérhető IoT-dashboard

Előkészítve: 2026. október 26. Ez a csomag telepítésre előkészített kód;
önmagában nem jelent már létrehozott webcímet vagy ellenőrzött éles hozzáférésvédelmet.
Az érdemi mérés kezdete nincs kijelölve, a jelenlegi adatok technikai tesztadatok.

## A választott működés

A teljes Streamlit-dashboard a Streamlit Community Cloudon fut, privát
GitHub-tárolóból, **privát alkalmazásként**. A webes hozzáférést a szolgáltató
bejelentkezése védi. Az adatbázis-kapcsolat a meglévő Supabase dashboard-fiókot
használja, szerveroldalon. Első körben kizárólag a tulajdonos használja a felületet.

A kódnak nincs önálló belépőoldala. Más tárhelyre vagy nyilvános Cloud-alkalmazásként
telepítve nem biztosít önmagában látogatói hozzáférésvédelmet. A választott
megoldásban a privát megosztás a működés szükséges része.

Az érzékelők, a Pi gyűjtője, feltöltője és a Supabase-szabályok a meglévő módon
működnek. A Mac a felhős alkalmazás használatához kikapcsolható. A jelzés továbbra
is megnyitott dashboard-munkamenetben frissül, nem önálló riasztási szolgáltatás.

## A csomag tartalma

- `dashboard.py`: a meglévő, eseménynaplós és CO₂-jelzéses dashboard felhős konfigurációval.
- `beallitasok.py`: Streamlit Secrets és a meglévő helyi dotenv beolvasása.
- `requirements.txt`: Python 3.12 környezetben ellenőrzött öt közvetlen függőség.
- `.streamlit/config.toml`: visszafogott hibamegjelenítés, bekapcsolt CORS/XSRF-védelem.
- `.streamlit/secrets.example.toml`: kitöltendő minta, kizárólag helyőrzőkkel.
- `.gitignore`: helyi jelszófájlok, mérések és virtuális környezetek kizárása gitből.
- `tests/test_felho.py`: 17 technikai teszt fiktív hozzáférésekkel és szimulált adatbázissal.

## 1. Privát GitHub-tároló

A forrásnak dedikált privát tárolót használj, például `iot-dashboard` néven.
Ha már van megfelelő privát tárolód, annak címével folytathatjuk. Más meglévő
tároló láthatóságának átállítása nem szükséges része ennek a csomagnak.

A tároló gyökerében legyen `dashboard.py`, `beallitasok.py` és `requirements.txt`.
A csomag többi forrásfájlját és a `.streamlit` mappát is elhelyezheted ugyanitt.
A `dashboard-felho` külső csomagmappát nem kell a tárolóba beágyazni.

A ZIP csak helyőrzőket tartalmaz. A valódi `dashboard.env` és `secrets.toml`
maradjon a tárolón kívül. A `.gitignore` nem távolít el már korábban feltöltött
fájlt a git előzményeiből. A szolgáltatásokhoz a saját fiókodban jelentkezz be;
jelszót és hozzáférési értékeket ne küldj beszélgetésben.

## 2. Streamlit Community Cloud

Nyisd meg: https://share.streamlit.io/

A saját GitHub-fiókoddal kapcsold össze a szolgáltatást. A privát tárolóhoz
hozzáférést kérhet a Streamlit; ezt a saját felületén tekintsd át és engedélyezd.

Új alkalmazás beállításai:

- Repository: a kiválasztott **privát** tároló.
- Branch: a kódot tartalmazó ág, új tárolónál rendszerint `main`.
- Main file path: `dashboard.py` (ha a tároló gyökerébe töltötted a csomag tartalmát).
- Advanced settings / Python version: **3.12**.

## 3. Supabase-konfiguráció a Secrets mezőben

Az Advanced settings / Secrets mezőbe a `.streamlit/secrets.example.toml`
szerkezetét másold. A helyőrzőket a Macen már működő
`~/.config/szakdolgozat/dashboard.env` megfelelő értékeire cseréld.
A szakasz neve pontosan `[supabase]` legyen.

Mind az öt érték szükséges: SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY,
SUPABASE_EMAIL, SUPABASE_PASSWORD, DEVICE_ID. A dashboard-fiók adatai kellenek,
nem a Pi feltöltőfiókjáé. A program a meglévő olvasóazonosítót ellenőrzi.

A TOML-ban az értékek idézőjeles karakterláncok. Ha az érték tartalmaz
idézőjelet vagy fordított perjelet, a TOML szabályai szerint kell megadni.
A hiányos felhős szakaszt a program nem egészíti ki csendben egy helyi fájlból.
Felhőben hiányzó konfigurációnál adatlekérés előtt megáll.

A Secrets szakaszban megadott SUPABASE_EMAIL háttérfiók. A webes belépést
a Streamlit-fiókhoz tartozó azonosítás kezeli; ez a két szerep eltérhet.

## 4. Privát hozzáférés és telepítés

A Streamlit dokumentációja szerint privát tárolóból az alkalmazás alapból
privát lesz. Az App settings / Sharing alatt ellenőrizd a beállítást:

**Who can view this app → Only specific people can view this app**

Ne állítsd public módba. Első körben maradjon csak a saját fejlesztői fiókod
jogosult. A hozzáadott látogatók a háttérben ugyanazt a dashboard-fiókot
használnák, és az eseményrögzítéshez is hozzáférnének.

A szolgáltató belépéséhez Google-fiók vagy e-mailben kapott egyszer használatos
link használható. A szolgáltatás jelenleg egyszerre egy privát alkalmazást enged.

## 5. Éles ellenőrzés

1. Nyisd meg az alkalmazás webcímét egy olyan privát böngészőablakban, ahol nem
   vagy bejelentkezve. A belépés előtt sem mérési adat, sem eseményűrlap ne jelenjen meg.
2. Lépj be a jogosult saját fiókoddal. Ellenőrizd a méréseket, a szenzorállapotokat
   és az eseménynaplót.
3. A felhős felületen rögzíts egy tényleges `test` eseményt. Ellenőrizd, hogy megjelenik,
   majd exportáld az eseménynaplót. Ez technikai próba, nem az érdemi mérés kezdete.
4. Zárd be a Macen futó helyi dashboardot. Telefonon, mobilinternetről is próbáld ki
   a felhős webcímet és az eseménymentést.

## Helyi használat a Macen

A meglévő helyi dashboard további működéséhez a `dashboard.py` és `beallitasok.py`
fájlokat együtt kell használni. A meglévő dashboard.env konfiguráció támogatott.
A felhős `requirements.txt` Python 3.12-höz készült; a Mac már működő Python 3.9-es
környezetébe ezt a csomaglistát nem szükséges telepíteni.

## Elérhetőség

A dokumentáció szerint 12 óra forgalom nélkül a Cloud-alkalmazás elalhat;
jogosult látogató fel tudja ébreszteni. Ez nem folyamatosan futó riasztási háttérrendszer.
Az adatok tárolása továbbra is a Supabase-ben történik, a Pi helyi CSV-mentése mellett.
A felhős felület újraindulásakor egy még vissza nem igazolt, csak munkamenetben őrzött
eseménymentés elveszhet. Bizonytalan mentésnél ellenőrizd a naplót az új bejegyzés előtt.

## Ellenőrzött dokumentáció, 2026. október 26.

- Telepítés, Python és Advanced settings:
  https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy
- Privát hozzáférés, belépés, megosztás:
  https://docs.streamlit.io/deploy/streamlit-community-cloud/share-your-app
- Secrets kezelése:
  https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management
- GitHub-jogosultságok és támogatott környezet:
  https://docs.streamlit.io/deploy/streamlit-community-cloud/status
- Alvó állapot:
  https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app

## Fejlesztői ellenőrzés

Python 3.12.14; Streamlit 1.50.0, pandas 2.2.3, Plotly 6.9.0,
requests 2.34.2, python-dotenv 1.2.4. Mind a 17 teszt sikeres.
Az AppTest a felületet szimulált adatokkal és hozzáférési értékekkel futtatta;
valódi Supabase- vagy Cloud-fiókhoz nem kapcsolódott. Ellenőriztük a titokkezelést,
a konfiguráció hiányakor történő megállást, az olvasófiók ellenőrzését, a token
újrakérését, a CO₂-szabályt és az eseményexportot. Az élő Cloud-telepítés és annak
kijelentkezett hozzáférési próbája még szükséges.

Telepített függőségekkel a csomag mappájából:

```bash
python -m unittest discover -s tests -v
```
