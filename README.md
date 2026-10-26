# IoT környezeti monitoring

Raspberry Pi mérési adataihoz kapcsolódó Streamlit-dashboard és eseménynapló, Supabase háttérrel.

## Felhős telepítés

- Belépési fájl: `dashboard.py`
- Python: **3.12**
- Csomagok: `requirements.txt`
- Tárhely: Streamlit Community Cloud, **privát alkalmazásként**
- Beállítások: a Cloud Secrets mezőjében, `[supabase]` szakaszban

A részletes lépéseket a [TELEPITES.md](TELEPITES.md) tartalmazza. A titkos beállítások szerkezetét a `.streamlit/secrets.example.toml` mutatja, kizárólag helyőrzőkkel.

A webes hozzáférést a Streamlit Cloud privát megosztása védi. A kód önálló látogatói bejelentkezést nem valósít meg, ezért nyilvános Cloud-alkalmazásként ne telepítsd.

## Ellenőrzés

Telepített függőségekkel:

```bash
python -m unittest discover -s tests -v
```

17 technikai teszt készült. A tesztek fiktív hozzáféréseket és szimulált adatbázisválaszokat használnak. Az éles telepítést és a kijelentkezett hozzáférésvédelmet külön kell ellenőrizni.

A repository nem tartalmaz valódi jelszót, API-kulcsot vagy mérési CSV-t.
