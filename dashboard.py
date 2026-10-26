"""IoT dashboard. Python 3.9+, Streamlit 1.50.

Indítás: python -m streamlit run dashboard.py --server.address 127.0.0.1
Konfiguráció: Streamlit Secrets [supabase] vagy ~/.config/szakdolgozat/dashboard.env
Felhőben: Streamlit Community Cloud, privát tároló és privát alkalmazás szükséges.
A webes hozzáférést a szolgáltató védi; a kód önálló belépőoldalt nem tartalmaz.
A méréseket csak olvassa; az events táblába saját eseményeket rögzít.
"""

import time
import math
from uuid import uuid4
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from beallitasok import ConfigError, load_dashboard_config

READER_UID = "97e23915-250c-44e3-9eed-8d808ccecc02"
TZ = "Europe/Budapest"
MAX_ROWS = 30000
PAGE_SIZE = 1000
CO2_THRESHOLD_PPM = 1500
CO2_DURATION_SECONDS = 300
CO2_MIN_SAMPLES = 6
CO2_MAX_GAP_SECONDS = 90
HSE_SOURCE = "https://www.hse.gov.uk/ventilation/using-co2-monitors.htm"
EVENT_TYPES = {
    "window_open": "Ablak kinyitása", "window_close": "Ablak becsukása",
    "light_on": "Világítás felkapcsolása", "light_off": "Világítás lekapcsolása",
    "work_start": "Munkavégzés kezdete", "work_end": "Munkavégzés vége",
    "test": "Teszt", "sensor_moved": "Szenzor áthelyezése",
}
FIELDS = (
    "measured_at,received_at,temperature_c,relative_humidity_pct,"
    "pressure_hpa,presence,bme280_status,co2_ppm,illuminance_lux,"
    "scd40_status,bh1750_status"
)
NUMERIC = ["temperature_c", "relative_humidity_pct", "pressure_hpa",
           "co2_ppm", "illuminance_lux"]
LABELS = {
    "temperature_c": ("Hőmérséklet", "°C", "#2563eb"),
    "relative_humidity_pct": ("Relatív páratartalom", "%", "#0891b2"),
    "pressure_hpa": ("Légnyomás", "hPa", "#64748b"),
    "co2_ppm": ("CO₂-koncentráció", "ppm", "#7c3aed"),
    "illuminance_lux": ("Megvilágítás", "lux", "#d97706"),
}


class DashboardError(Exception):
    pass


class Reader:
    def __init__(self, config):
        self.config = config
        self.url = config["SUPABASE_URL"].rstrip("/")
        self.session = requests.Session()
        self.session.headers["apikey"] = config["SUPABASE_PUBLISHABLE_KEY"]
        self.token = None
        self.deadline = 0

    def login(self):
        response = self.session.post(
            self.url + "/auth/v1/token?grant_type=password",
            json={"email": self.config["SUPABASE_EMAIL"],
                  "password": self.config["SUPABASE_PASSWORD"]},
            timeout=(10, 20), allow_redirects=False,
        )
        if response.status_code != 200:
            raise DashboardError(f"Bejelentkezési hiba: HTTP {response.status_code}.")
        data = response.json()
        if data.get("user", {}).get("id") != READER_UID:
            raise DashboardError("A dashboardhoz a külön olvasófelhasználó adatai szükségesek.")
        self.token = data.get("access_token")
        if not self.token:
            raise DashboardError("A bejelentkezés nem adott hozzáférési tokent.")
        self.deadline = time.monotonic() + max(1, int(data.get("expires_in", 3600)) - 60)

    def query(self, params, resource="measurements"):
        for attempt in range(2):
            if not self.token or time.monotonic() >= self.deadline:
                self.login()
            response = self.session.get(
                self.url + "/rest/v1/" + resource,
                headers={"Authorization": "Bearer " + self.token},
                params=params, timeout=(10, 20), allow_redirects=False,
            )
            if response.status_code == 401 and attempt == 0:
                self.token = None
                continue
            if response.status_code not in (200, 206):
                raise DashboardError(f"Adatlekérési hiba: HTTP {response.status_code}.")
            result = response.json()
            if not isinstance(result, list):
                raise DashboardError("Váratlan adatbázisválasz.")
            return result

    def latest(self):
        rows = self.query({"select": FIELDS,
                           "device_id": "eq." + self.config["DEVICE_ID"],
                           "order": "measured_at.desc", "limit": 1})
        return rows[0] if rows else None

    def history(self, start, end):
        rows = []
        # Kulcs szerinti lapozás: a korábbi mérések utólagos feltöltése
        # nem tolja el az offsetet. Egy eszköz mérési időpontja egyedi.
        cursor = None
        while len(rows) < MAX_ROWS:
            lower = "gt." + cursor if cursor else "gte." + start.isoformat()
            params = [
                ("select", FIELDS),
                ("device_id", "eq." + self.config["DEVICE_ID"]),
                ("measured_at", lower),
                ("measured_at", "lte." + end.isoformat()),
                ("order", "measured_at.asc"),
                ("limit", min(PAGE_SIZE, MAX_ROWS - len(rows))),
            ]
            page = self.query(params)
            if not page:
                return rows, False
            new_cursor = page[-1]["measured_at"]
            if cursor is not None and pd.Timestamp(new_cursor) <= pd.Timestamp(cursor):
                raise DashboardError("A lapozás nem haladt előre.")
            rows.extend(page)
            cursor = new_cursor
        # Külön ellenőrizzük, valóban maradt-e további sor.
        extra = self.query([
            ("select", "measured_at"),
            ("device_id", "eq." + self.config["DEVICE_ID"]),
            ("measured_at", "gt." + cursor),
            ("measured_at", "lte." + end.isoformat()),
            ("order", "measured_at.asc"), ("limit", 1),
        ])
        return rows, bool(extra)

    def events(self, start, end):
        rows = []
        while len(rows) < 5000:
            page = self.query([
                ("select", "id,device_id,event_at,event_type,note,created_at,created_by"),
                ("device_id", "eq." + self.config["DEVICE_ID"]),
                ("event_at", "gte." + start.isoformat()),
                ("event_at", "lte." + end.isoformat()),
                ("created_at", "lte." + end.isoformat()),
                ("order", "event_at.asc,id.asc"),
                ("limit", min(1000, 5000 - len(rows))), ("offset", len(rows)),
            ], resource="events")
            if not page:
                return rows, False
            rows.extend(page)
        return rows, True

    def insert_event(self, payload):
        if payload.get("device_id") != self.config["DEVICE_ID"]:
            raise DashboardError("Az esemény más eszközhöz tartozik.")
        for attempt in range(2):
            if not self.token or time.monotonic() >= self.deadline:
                self.login()
            response = self.session.post(
                self.url + "/rest/v1/events",
                headers={"Authorization": "Bearer " + self.token,
                         "Prefer": "return=minimal"},
                json=payload, timeout=(10, 20), allow_redirects=False,
            )
            if response.status_code == 401 and attempt == 0:
                self.token = None
                continue
            if response.status_code == 201:
                return
            if response.status_code == 409:
                # Elveszett HTTP-válasz után ugyanazzal az UUID-val próbálkozunk.
                # Csak a saját, azonos tartalmú korábbi bejegyzést fogadjuk el.
                saved = self.query({"select": "id,device_id,event_at,event_type,note,created_by",
                                    "id": "eq." + payload["id"], "limit": 1},
                                   resource="events")
                if saved and same_event(saved[0], payload):
                    return
            raise DashboardError(f"Eseménymentési hiba: HTTP {response.status_code}.")


def same_event(saved, payload):
    return (
        saved.get("id") == payload.get("id")
        and saved.get("created_by") == READER_UID
        and all(saved.get(key) == payload.get(key) for key in ("device_id", "event_type", "note"))
        and pd.Timestamp(saved["event_at"]) == pd.Timestamp(payload["event_at"])
    )


def local_event_time(day, clock, occurrence="Nincs megadva"):
    naive = datetime.combine(day, clock.replace(tzinfo=None))
    zone = ZoneInfo(TZ)
    candidates = {}
    for fold in (0, 1):
        local = naive.replace(tzinfo=zone, fold=fold)
        utc = local.astimezone(timezone.utc)
        if utc.astimezone(zone).replace(tzinfo=None) == naive:
            candidates[utc] = local
    if not candidates:
        raise DashboardError("Ez a helyi időpont az óraátállítás miatt nem létezik.")
    ordered = sorted(candidates)
    if len(ordered) == 2:
        if occurrence == "Nincs megadva":
            raise DashboardError("Ez az időpont kétszer fordul elő. Válaszd ki az első vagy második előfordulást.")
        return ordered[0 if occurrence == "Első előfordulás" else 1]
    return ordered[0]


def build_event(device, kind, note, event_time, now=None):
    now = now or datetime.now(timezone.utc)
    if kind not in EVENT_TYPES:
        raise DashboardError("Ismeretlen eseménytípus.")
    if event_time.utcoffset() is None:
        raise DashboardError("Az esemény időpontjából hiányzik az időzóna.")
    if event_time > now:
        raise DashboardError("Jövőbeli eseményt nem naplózunk.")
    note = note.strip()
    if len(note) > 1000:
        raise DashboardError("A megjegyzés legfeljebb 1000 karakter lehet.")
    return {"id": str(uuid4()), "device_id": device,
            "event_at": event_time.astimezone(timezone.utc).isoformat(),
            "event_type": kind, "note": note or None}


def event_table(events):
    frame = pd.DataFrame(events)
    for field in ("event_at", "created_at"):
        frame[field] = pd.to_datetime(frame[field], utc=True).dt.tz_convert(TZ).map(
            lambda timestamp: timestamp.isoformat()
        )
    frame["esemeny"] = frame["event_type"].map(EVENT_TYPES).fillna(frame["event_type"])
    return frame[["event_at", "esemeny", "note", "created_at", "id", "event_type"]].rename(
        columns={"event_at": "Esemény időpontja", "note": "Megjegyzés",
                 "created_at": "Rögzítés időpontja", "esemeny": "Esemény"}
    )


def event_timeline(events):
    if not events:
        return
    figure = go.Figure(go.Scatter(
        x=[pd.Timestamp(event["event_at"]).tz_convert(TZ).tz_localize(None) for event in events],
        y=[EVENT_TYPES.get(event["event_type"], event["event_type"]) for event in events],
        mode="markers", marker={"size": 9, "color": "#d97706"},
        hovertemplate="%{x|%m.%d. %H:%M:%S}<br>%{y}<extra></extra>",
    ))
    figure.update_layout(title="Naplózott események", template="plotly_white",
                         height=300, xaxis_title="Budapesti idő")
    st.plotly_chart(figure, use_container_width=True)


def render_event_form(reader):
    st.subheader("Új esemény rögzítése")
    st.caption("A tényleges eseményidőt add meg. Utólagos rögzítésnél a mentés idejét külön tároljuk.")
    if "event_success" in st.session_state:
        st.success(st.session_state.pop("event_success"))

    if "pending_event" in st.session_state:
        pending = st.session_state.pending_event
        local = pd.Timestamp(pending["event_at"]).tz_convert(TZ)
        if "event_failure" in st.session_state:
            st.error(st.session_state.pop("event_failure"))
        st.warning("Egy korábbi mentés még nincs visszaigazolva. Ugyanazt a bejegyzést próbáljuk újra, új példány létrehozása nélkül.")
        st.write(EVENT_TYPES[pending["event_type"]] + " · " + local.strftime("%Y.%m.%d. %H:%M:%S %z"))
        if st.button("Függő mentés újrapróbálása", key="retry_event"):
            finish_event_save(reader, pending)
        st.caption("Hiba esetén hagyd nyitva ezt az oldalt. Újraindítás előtt ellenőrizd a Supabase events tábláját.")
        return

    use_now = st.checkbox("Az esemény most történt", value=True, key="event_use_now")
    local_now = datetime.now(ZoneInfo(TZ))
    with st.form("new_event_form", clear_on_submit=True, enter_to_submit=False):
        kind = st.selectbox("Esemény", list(EVENT_TYPES),
                            format_func=lambda value: EVENT_TYPES[value], key="event_kind")
        left, right = st.columns(2)
        day = left.date_input("Dátum", value=local_now.date(),
                              disabled=use_now, key="event_day")
        clock = right.time_input("Időpont, budapesti idő", value=local_now.time().replace(microsecond=0),
                                 step=60, disabled=use_now, key="event_clock")
        with st.expander("Óraátállításkor ismétlődő időpont"):
            occurrence = st.selectbox("Csak a kétszer előforduló órában szükséges",
                                      ["Nincs megadva", "Első előfordulás", "Második előfordulás"],
                                      disabled=use_now, key="event_occurrence")
        note = st.text_area("Megjegyzés (nem kötelező)", max_chars=1000, key="event_note")
        submitted = st.form_submit_button("Esemény mentése", type="primary")
    if submitted:
        try:
            now = datetime.now(timezone.utc)
            event_time = now if use_now else local_event_time(day, clock, occurrence)
            payload = build_event(reader.config["DEVICE_ID"], kind, note, event_time, now)
        except DashboardError as error:
            st.error(str(error))
            return
        st.session_state.pending_event = payload
        finish_event_save(reader, payload)


def finish_event_save(reader, payload):
    failure = None
    try:
        reader.insert_event(payload)
    except DashboardError as error:
        failure = str(error)
    except requests.RequestException as error:
        failure = f"A mentés nem igazolható vissza ({type(error).__name__})."
    except (ValueError, KeyError, TypeError):
        failure = "A mentés válasza nem dolgozható fel. A próbálkozást megőrizzük."
    if failure:
        st.session_state.event_failure = failure
        st.rerun()
        return
    st.session_state.pop("pending_event", None)
    st.session_state.event_success = "Az esemény mentése sikerült."
    st.rerun()


def load_config():
    try:
        return load_dashboard_config(st.secrets)
    except ConfigError as error:
        raise DashboardError(str(error)) from error


def make_frame(rows):
    frame = pd.DataFrame(rows)
    frame["measured_at"] = pd.to_datetime(frame["measured_at"], utc=True, errors="coerce")
    frame["received_at"] = pd.to_datetime(frame["received_at"], utc=True, errors="coerce")
    for name in NUMERIC:
        frame[name] = pd.to_numeric(frame[name], errors="coerce")
    return frame.sort_values("measured_at").reset_index(drop=True)


def value_text(value, unit="", decimals=2):
    if value is None or pd.isna(value):
        return "Nincs adat"
    return f"{float(value):.{decimals}f} {unit}".strip()


def co2_rule(rows, now):
    """Saját szabály: >1500 ppm, jelenlét, >=5 perc, >=6 érvényes mintapont.

    A HSE a tartósan 1500 ppm feletti értéket értelmezi szellőzési jelzésként.
    A perces/időtartam- és adatfolytonossági feltételek a prototípus saját döntései.
    """
    if not rows:
        return "unavailable", "Nincs elegendő friss adat a CO₂-szabály értékeléséhez."
    samples = []
    for row in rows:
        stamp = pd.to_datetime(row.get("measured_at"), utc=True, errors="coerce")
        if pd.isna(stamp):
            return "unavailable", "Hibás időbélyeg miatt a CO₂-szabály nem értékelhető."
        samples.append((stamp.to_pydatetime(), row))
    samples.sort(key=lambda sample: sample[0])
    # Az adatbázisban egyedi az időpont, de a szabály sem számolhat kétszer egy mintát.
    samples = list({stamp: row for stamp, row in samples}.items())
    stamp, latest = samples[-1]
    age = (now - stamp).total_seconds()
    if age < -60 or age > 180:
        return "unavailable", "A mérési idő nem friss vagy a jövőbe mutat; nincs aktuális CO₂-jelzés."

    def valid(row):
        try:
            value = float(row.get("co2_ppm"))
        except (ValueError, TypeError):
            return False
        return row.get("scd40_status") == "ok" and math.isfinite(value) and value > 0

    if not valid(latest):
        return "unavailable", "A legutóbbi CO₂-kiolvasás hiányzik vagy nem sikeres."
    if float(latest["co2_ppm"]) <= CO2_THRESHOLD_PPM:
        return "inactive", "A legutóbbi CO₂-érték nem haladja meg az 1500 ppm-es jelzési küszöböt."
    if latest.get("presence") is not True:
        return "inactive", "A CO₂-érték 1500 ppm felett van, de nincs érzékelt jelenlét; a jelenlétfüggő szabály nem aktív."

    streak = []
    previous = None
    for stamp, row in reversed(samples):
        if not valid(row) or row.get("presence") is not True:
            break
        if float(row["co2_ppm"]) <= CO2_THRESHOLD_PPM:
            break
        if previous is not None and (previous - stamp).total_seconds() > CO2_MAX_GAP_SECONDS:
            break
        streak.append(stamp)
        previous = stamp
    duration = (streak[0] - streak[-1]).total_seconds() if streak else 0
    if duration >= CO2_DURATION_SECONDS and len(streak) >= CO2_MIN_SAMPLES:
        return "active", (
            "Szellőztetés megfontolása javasolt: a mért CO₂-koncentráció "
            f"legalább {duration / 60:.1f} perce 1500 ppm felett van, "
            "az érintett mintákban érzékelt jelenlét mellett."
        )
    return "pending", (
        "A CO₂-érték 1500 ppm felett van. A tartós túllépéshez "
        f"még nincs meg az ötperces, legalább hat érvényes mintából álló adatsor "
        f"(jelenleg {duration / 60:.1f} perc, {len(streak)} minta)."
    )


def render_rules(reader, latest, now):
    st.subheader("Üzemeltetési jelzések")
    labels = {"ok": "Kiolvasás sikeres", "read_error": "Kiolvasási hiba",
              "init_error": "Inicializálási hiba", "not_ready": "Mérés még nem áll rendelkezésre"}
    for sensor, field in (("BME280", "bme280_status"), ("SCD40", "scd40_status"),
                          ("BH1750", "bh1750_status")):
        status = latest.get(field)
        if status is None:
            st.caption(f"{sensor}: a legutóbbi rekord nem tartalmaz állapotadatot.")
        elif status != "ok":
            st.warning(f"{sensor}: {labels.get(status, 'Ismeretlen kiolvasási állapot')}. "
                       "A jelzés a legutóbbi tárolt méréshez tartozik.")
    try:
        recent, limited = reader.history(now - timedelta(minutes=10), now)
        if limited:
            state, message = "unavailable", "A szabály bemeneti adatsora nem teljes."
        elif not recent or pd.Timestamp(recent[-1]["measured_at"]) != pd.Timestamp(latest["measured_at"]):
            state, message = "unavailable", "A legfrissebb mérés még nem szerepel a szabály adatsorában. Frissíts később."
        else:
            state, message = co2_rule(recent, now)
    except (DashboardError, requests.RequestException, ValueError, KeyError, TypeError):
        state, message = "unavailable", "A CO₂-szabályhoz szükséges adatok most nem kérhetők le."
    if state == "active":
        st.warning(message)
    else:
        st.info(message)
    st.caption("A jelzés szellőztetési döntést támogat. Nem egészségügyi határérték és nem az összes légszennyező mérése.")
    with st.expander("A CO₂-szabály és a forrása"):
        st.markdown(
            "**Forrás:** Health and Safety Executive (HSE), "
            f"[Using CO₂ monitors]({HSE_SOURCE}), "
            "*Understanding the numbers and when to take action* szakasz. "
            "Ellenőrizve: 2026. október 20.\n\n"
            "A HSE szerint a használt helyiségben tartósan 1500 ppm feletti CO₂ "
            "elégtelen szellőzésre utal. A CO₂-mérés csak tájékoztató jellegű "
            "a szellőzés megítélésében.\n\n"
            "**A prototípus saját működési feltétele:** 1500 ppm feletti érték "
            "legalább öt percen át, legalább hat különböző időpontú, sikeres SCD40-mérésben. "
            "Minden érintett mintában érzékelt jelenlét kell; két minta között legfeljebb "
            "90 másodperc lehet. A hiányzó, hibás vagy küszöb alatti mérés megszakítja "
            "a sorozatot. Az öt perc, hat minta és 90 másodperc **saját tervezési döntés**, "
            "ezeket nem a HSE írja elő.\n\n"
            "A jelzés a legutóbbi tíz perc adataiból készül, a grafikon időszakválasztásától "
            "függetlenül. Három percnél régebbi adatokra nem ad aktuális javaslatot. "
            "A dashboard nyitva tartása mellett frissül; ez még nem külön, folyamatos "
            "riasztási szolgáltatás vagy mentett riasztásnapló."
        )


def chart(frame, field):
    name, unit, color = LABELS[field]
    x = frame["measured_at"].dt.tz_convert(TZ).dt.tz_localize(None)
    y = frame[field].copy()
    # A háromperces adatszünetekben megszakítjuk a vonalat.
    # Az eredeti méréseket és a CSV-exportot nem módosítjuk.
    xs, ys = [], []
    previous = None
    for timestamp, value in zip(x, y):
        if previous is not None and (timestamp - previous).total_seconds() > 180:
            xs.append(previous + timedelta(seconds=1))
            ys.append(None)
        xs.append(timestamp)
        ys.append(None if pd.isna(value) else float(value))
        previous = timestamp
    figure = go.Figure(go.Scatter(
        x=xs, y=ys, mode="lines", connectgaps=False,
        line={"color": color, "width": 2}, name=name,
        hovertemplate="%{x|%m.%d. %H:%M:%S}<br>%{y:.2f} " + unit + "<extra></extra>",
    ))
    figure.update_layout(title=name, height=290, margin={"l": 15, "r": 15, "t": 45, "b": 15},
                         xaxis_title="Budapesti idő", yaxis_title=unit,
                         template="plotly_white")
    if field == "co2_ppm":
        figure.add_hline(y=CO2_THRESHOLD_PPM, line_dash="dot", line_color="#d97706",
                         annotation_text="Jelzési küszöb: 1500 ppm")
    st.plotly_chart(figure, use_container_width=True)


def display(reader, hours):
    st.button("Frissítés most")
    now = datetime.now(timezone.utc)
    try:
        latest = reader.latest()
        if latest is None:
            st.info("Nem érhető el mérés. Ellenőrizd az olvasási jogosultságot és a feltöltést.")
            return
        rows, truncated = reader.history(now - timedelta(hours=hours), now)
    except DashboardError as error:
        st.error(str(error))
        return
    except requests.RequestException as error:
        st.error(f"Nem sikerült kapcsolódni az adatbázishoz ({type(error).__name__}).")
        return
    except (ValueError, KeyError, TypeError):
        st.error("A válasz vagy egy időbélyeg nem dolgozható fel.")
        return

    events, events_limited, events_ok = [], False, True
    try:
        events, events_limited = reader.events(now - timedelta(hours=hours), now)
    except (DashboardError, requests.RequestException, ValueError, KeyError, TypeError):
        events_ok = False
        st.warning("Az eseménynapló most nem kérhető le. A mérési adatokat ettől függetlenül megjelenítjük.")

    measured = pd.to_datetime(latest["measured_at"], utc=True, errors="coerce")
    received = pd.to_datetime(latest["received_at"], utc=True, errors="coerce")
    if pd.isna(measured) or pd.isna(received):
        st.error("Érvénytelen időbélyeg a legutóbbi mérésben.")
        return
    age = (now - measured.to_pydatetime()).total_seconds()
    if age < -60:
        st.warning("A mérési idő a jövőbe mutat. Ellenőrizd a Raspberry Pi óráját.")
    elif age > 180:
        st.warning(f"A legutóbbi mérés {age / 60:.1f} perces. Az alábbi értékek nem frissek.")
    else:
        st.success("Friss mérési adatok érkeznek.")
    st.caption(
        "Utolsó mérés: " + measured.tz_convert(TZ).strftime("%Y.%m.%d. %H:%M:%S %z")
        + " · Beérkezés: " + received.tz_convert(TZ).strftime("%H:%M:%S %z")
    )
    columns = st.columns(4)
    for column, field in zip(columns[:3], NUMERIC[:3]):
        name, unit, _ = LABELS[field]
        column.metric(name, value_text(latest.get(field), unit))
    presence = latest.get("presence")
    columns[3].metric("Jelenlétjelzés", "Érzékelve" if presence is True
                      else "Nem érzékelve" if presence is False else "Nincs adat")
    if latest.get("bme280_status") != "ok":
        st.warning("A legutóbbi BME280-kiolvasás hibás; a hiányzó értékeket nem pótoljuk.")
    if any(latest.get(field) is not None for field in ("co2_ppm", "illuminance_lux")):
        for column, field in zip(st.columns(2), ("co2_ppm", "illuminance_lux")):
            name, unit, _ = LABELS[field]
            column.metric(name, value_text(latest.get(field), unit, 0))
    else:
        st.caption("CO₂- és megvilágításadat még nem érkezett.")

    render_rules(reader, latest, now)

    if not rows:
        st.info("A kiválasztott időszakban nincs mérés.")
        return
    frame = make_frame(rows)
    if truncated:
        st.warning("A megjelenítés elérte a 30 000 soros korlátot. Válassz rövidebb időszakot.")
    st.caption(f"{len(frame):,} mérési rekord a kiválasztott időszakból. "
               "A grafikonok a méréseket mutatják, hiányzó értékek pótlása nélkül.")
    graphs, data, event_data = st.tabs(["Grafikonok", "Mérési táblázat és letöltés", "Eseménynapló"])
    with graphs:
        event_timeline(events)
        for field in NUMERIC:
            if frame[field].notna().any():
                chart(frame, field)
        presence_fig = go.Figure(go.Scatter(
            x=frame["measured_at"].dt.tz_convert(TZ).dt.tz_localize(None),
            y=frame["presence"].map({True: 1, False: 0}),
            mode="markers", marker={"size": 4, "color": "#2563eb"},
            hovertemplate="%{x|%m.%d. %H:%M:%S}<br>Jelenlétjelzés: %{y}<extra></extra>",
        ))
        presence_fig.update_layout(title="Jelenlét a mintavételi időpontokban", height=240,
                                  template="plotly_white", xaxis_title="Budapesti idő",
                                  yaxis={"tickvals": [0, 1], "ticktext": ["Nem érzékelve", "Érzékelve"]})
        st.plotly_chart(presence_fig, use_container_width=True)
    with data:
        export = frame.copy()
        for field in ("measured_at", "received_at"):
            export[field] = export[field].dt.tz_convert(TZ).map(
                lambda timestamp: timestamp.isoformat() if pd.notna(timestamp) else ""
            )
        export.insert(0, "device_id", reader.config["DEVICE_ID"])
        st.download_button("Mérési adatok letöltése CSV-ben",
                           export.to_csv(index=False, sep=";").encode("utf-8-sig"),
                           file_name=f"szoba_01_{now:%Y-%m-%d_%H-%M}_UTC.csv",
                           mime="text/csv", on_click="ignore")
        st.dataframe(export.iloc[::-1].head(500), use_container_width=True, hide_index=True)
        st.caption("A táblázat legfeljebb az utolsó 500 sort mutatja. "
                   "A letöltés az összes, ebben a nézetben lekért sort tartalmazza.")
    with event_data:
        if not events_ok:
            st.info("Az események listája jelenleg nem érhető el.")
        elif not events:
            st.info("A kiválasztott időszakban még nincs naplózott esemény.")
        else:
            if events_limited:
                st.warning("Az eseménylista elérte az 5000 soros korlátot. Válassz rövidebb időszakot.")
            table = event_table(events)
            st.dataframe(table.iloc[::-1], use_container_width=True, hide_index=True)
            st.download_button("Eseménynapló letöltése CSV-ben",
                               table.to_csv(index=False, sep=";").encode("utf-8-sig"),
                               file_name=f"szoba_01_esemenyek_{now:%Y-%m-%d_%H-%M}_UTC.csv",
                               mime="text/csv", on_click="ignore")
            st.caption("A lista az esemény időpontja szerint szűrt. A rögzítési idő ettől eltérhet.")
    st.caption("Utolsó lekérdezés: " + pd.Timestamp(now).tz_convert(TZ).strftime("%H:%M:%S")
               + " · Automatikus frissítés: 60 másodperc, amíg az oldal nyitva van.")


def main():
    st.set_page_config(page_title="Irodai környezeti monitoring", layout="wide")
    st.title("Irodai környezeti monitoring")
    st.caption("Raspberry Pi prototípus · Szoba 01 · Otthoni munkakörnyezet")
    with st.sidebar:
        st.header("Megjelenítés")
        options = {"Utolsó 1 óra": 1, "Utolsó 6 óra": 6, "Utolsó 24 óra": 24,
                   "Utolsó 3 nap": 72, "Utolsó 7 nap": 168}
        selected = st.selectbox("Időszak", list(options), index=2)
        st.caption("Időzóna: Europe/Budapest")
        st.caption("A jelenlétjelzés nem személyszám. A műszeres adatok kutatási célú mérések.")
    try:
        config = load_config()
    except DashboardError as error:
        st.error(str(error))
        st.stop()
    # Kliens munkamenetenként: nincs megosztott jelszó- vagy adatcache.
    if "reader" not in st.session_state or st.session_state.reader.config != config:
        if "reader" in st.session_state:
            st.session_state.reader.session.close()
        st.session_state.reader = Reader(config)

    @st.fragment(run_every=60)
    def refresh_panel():
        display(st.session_state.reader, options[selected])

    refresh_panel()

    @st.fragment
    def event_form_panel():
        render_event_form(st.session_state.reader)

    event_form_panel()


if __name__ == "__main__":
    main()
