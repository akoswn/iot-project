"""Helyi dotenv vagy Streamlit Secrets konfiguráció, érzékeny értékek naplózása nélkül."""

from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values

REQUIRED = ("SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_EMAIL",
            "SUPABASE_PASSWORD", "DEVICE_ID")


class ConfigError(Exception):
    pass


def load_dashboard_config(secret_store=None, env_path=None):
    """A [supabase] szakasz elsőbbséget élvez; részleges szakasz nem egészül ki más forrásból."""
    missing = object()
    section = missing
    if secret_store is not None:
        try:
            section = secret_store["supabase"]
        except (KeyError, FileNotFoundError):
            pass
        except Exception as error:
            # TOML- vagy konfigurációs hiba részlete érzékeny szöveget is tartalmazhat.
            raise ConfigError("A Streamlit Secrets beállítás nem olvasható. Ellenőrizd a TOML formátumát.") from error
    if section is missing:
        path = Path(env_path) if env_path else Path.home() / ".config/szakdolgozat/dashboard.env"
        values = dotenv_values(path)
    else:
        if not isinstance(section, Mapping):
            raise ConfigError("A Streamlit Secrets beállításban [supabase] szakasz szükséges.")
        values = section
    if any(not isinstance(values.get(key), str) or not values[key].strip() for key in REQUIRED):
        raise ConfigError("Hiányzó vagy hibás beállítás. Add meg az öt szükséges értéket a [supabase] szakaszban vagy a helyi dashboard.env fájlban.")
    config = {key: values[key] for key in REQUIRED}
    # A jelszó elején/végén lévő szóköz szándékos is lehet; azt nem módosítjuk.
    for key in REQUIRED:
        if key != "SUPABASE_PASSWORD":
            config[key] = config[key].strip()
    try:
        parsed = urlsplit(config["SUPABASE_URL"])
    except ValueError as error:
        raise ConfigError("Hibás SUPABASE_URL; a HTTPS projektcímet add meg.") from error
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ("", "/")):
        raise ConfigError("Hibás SUPABASE_URL; a HTTPS projektcímet add meg.")
    if not config["SUPABASE_PUBLISHABLE_KEY"].startswith("sb_publishable_"):
        raise ConfigError("Publishable API-kulcs szükséges.")
    if config["DEVICE_ID"] != "szoba_01":
        raise ConfigError("A jelenlegi olvasási jogosultság a szoba_01 eszközhöz tartozik.")
    config["SUPABASE_URL"] = config["SUPABASE_URL"].rstrip("/")
    return config
