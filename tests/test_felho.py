"""Kizárólag fiktív hitelesítőadatok és szimulált HTTP-válaszok."""
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import beallitasok as b
import dashboard as d
from streamlit.runtime.secrets import Secrets
from streamlit.testing.v1 import AppTest


def config():
    return {"SUPABASE_URL": "https://pelda.supabase.co", "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_TECHNIKAI_TESZT",
            "SUPABASE_EMAIL": "teszt@example.invalid", "SUPABASE_PASSWORD": "fiktiv_jelszo",
            "DEVICE_ID": "szoba_01"}


def response(status, body):
    r = Mock(); r.status_code = status; r.json.return_value = body
    return r


class CloudConfigTests(unittest.TestCase):
    def test_cloud_section(self):
        with patch.object(b, "dotenv_values") as local:
            self.assertEqual(b.load_dashboard_config({"supabase": config()}), config())
            local.assert_not_called()

    def test_partial_cloud_does_not_mix_in_local_password(self):
        with patch.object(b, "dotenv_values", return_value=config()) as local:
            with self.assertRaises(b.ConfigError):
                b.load_dashboard_config({"supabase": {"SUPABASE_URL": config()["SUPABASE_URL"]}})
            local.assert_not_called()

    def test_bad_section_type_rejected(self):
        with self.assertRaises(b.ConfigError):
            b.load_dashboard_config({"supabase": "hibas"})

    def test_local_dotenv_remains_usable(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"dashboard.env"
            p.write_text("\n".join(k+"="+v for k,v in config().items()))
            self.assertEqual(b.load_dashboard_config({}, p), config())

    def test_real_streamlit_missing_secrets_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            secrets=Secrets()
            with patch("streamlit.runtime.secrets.config.get_option",return_value=[str(Path(tmp)/"nem-letezik.toml")]), patch.object(b, "dotenv_values", return_value=config()):
                self.assertEqual(b.load_dashboard_config(secrets), config())

    def test_real_streamlit_nested_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"secrets.toml"
            p.write_text('[supabase]\n'+"\n".join(k+' = "'+v+'"' for k,v in config().items()))
            secrets=Secrets()
            with patch("streamlit.runtime.secrets.config.get_option",return_value=[str(p)]), patch.object(Secrets,"_maybe_install_file_watchers"):
                self.assertEqual(b.load_dashboard_config(secrets), config())

    def test_malformed_secrets_error_does_not_reveal_value(self):
        store = Mock()
        store.__getitem__ = Mock(side_effect=ValueError("fiktiv_jelszo"))
        with self.assertRaises(b.ConfigError) as caught:
            b.load_dashboard_config(store)
        self.assertNotIn("fiktiv_jelszo", str(caught.exception))

    def test_invalid_urls_rejected(self):
        for url in ("http://pelda.supabase.co", "https://user:pw@pelda.supabase.co", "https://pelda.supabase.co/path", "https://pelda.supabase.co?token=valami"):
            with self.subTest(url=url):
                cfg=config();cfg["SUPABASE_URL"]=url
                with self.assertRaises(b.ConfigError):
                    b.load_dashboard_config({"supabase": cfg})

    def test_wrong_device_and_privileged_key_rejected(self):
        for key,value in (("DEVICE_ID","masik_szoba"),("SUPABASE_PUBLISHABLE_KEY","sb_secret_TESZT")):
            cfg=config();cfg[key]=value
            with self.assertRaises(b.ConfigError):
                b.load_dashboard_config({"supabase": cfg})

    def test_password_whitespace_not_modified(self):
        cfg=config();cfg["SUPABASE_PASSWORD"]=" fiktiv_jelszo "
        self.assertEqual(b.load_dashboard_config({"supabase":cfg})["SUPABASE_PASSWORD"]," fiktiv_jelszo ")


class ExistingBehaviourTests(unittest.TestCase):
    def test_reader_rejects_other_account(self):
        reader=d.Reader(config())
        reader.session=Mock()
        reader.session.post.return_value=response(200,{"user":{"id":"MASIK_FELHASZNALO"},"access_token":"teszt"})
        with self.assertRaises(d.DashboardError):reader.login()
        self.assertIsNone(reader.token)

    def test_reader_accepts_expected_account(self):
        reader=d.Reader(config());reader.session=Mock()
        reader.session.post.return_value=response(200,{"user":{"id":d.READER_UID},"access_token":"teszt","expires_in":3600})
        reader.login();self.assertEqual(reader.token,"teszt")

    def test_query_reauthenticates_after_401(self):
        reader=d.Reader(config());reader.session=Mock();reader.token="lejart";reader.deadline=float("inf")
        reader.session.get.side_effect=[response(401,{}),response(200,[{"value":1}])]
        reader.session.post.return_value=response(200,{"user":{"id":d.READER_UID},"access_token":"uj_teszt"})
        self.assertEqual(reader.query({"select":"id"}),[{"value":1}])
        self.assertEqual(reader.session.post.call_count,1)

    def test_co2_rule_still_activates_after_six_samples(self):
        now=datetime(2026,10,26,12,0,tzinfo=timezone.utc)
        rows=[dict(measured_at=(now-timedelta(minutes=5-i)).isoformat(), co2_ppm=1600,
                   scd40_status="ok",presence=True) for i in range(6)]
        self.assertEqual(d.co2_rule(rows,now)[0],"active")
        rows[-1]["presence"]=False
        self.assertEqual(d.co2_rule(rows,now)[0],"inactive")

    def test_event_export_keeps_machine_type_and_offset(self):
        t="2026-10-26T12:00:00Z"
        frame=d.event_table([dict(id="TECHNIKAI_TESZT",event_at=t,created_at=t,event_type="test",note=None)])
        self.assertIn("Esemény időpontja",frame)
        self.assertEqual(frame.iloc[0]["event_type"],"test")
        self.assertTrue(frame.iloc[0]["Esemény időpontja"].endswith("+01:00"))


class AppSmokeTests(unittest.TestCase):
    def test_missing_configuration_stops_before_database(self):
        with patch.object(b,"dotenv_values",return_value={}), patch.object(d.Reader,"latest") as latest:
            at=AppTest.from_file(str(Path(d.__file__))).run(timeout=15)
        self.assertEqual(len(at.exception),0)
        self.assertTrue(any("Hiányzó" in x.value for x in at.error))
        latest.assert_not_called()

    def test_cloud_config_renders_with_simulated_database(self):
        now=datetime.now(timezone.utc).replace(microsecond=0)
        rows=[dict(measured_at=(now-timedelta(minutes=5-i)).isoformat(),received_at=(now-timedelta(minutes=5-i)).isoformat(),
                   temperature_c=23.,relative_humidity_pct=45.,pressure_hpa=1005.,presence=True,
                   co2_ppm=900.,illuminance_lux=300.,bme280_status="ok",scd40_status="ok",bh1750_status="ok") for i in range(6)]
        events=[dict(id="TECHNIKAI_TESZT",event_at=now.isoformat(),created_at=now.isoformat(),event_type="test",note=None)]
        # Az AppTest külön néven tölti be a dashboard modult; a tesztbelépő
        # a hálózati lekéréseket mesterséges bemenetekkel helyettesíti.
        source=Path(d.__file__).read_text()
        source=source.replace('if __name__ == "__main__":\n    main()', '')
        source+='\nReader.latest = lambda self: TEST_ROWS[-1]\nReader.history = lambda self, start, end: (TEST_ROWS, False)\nReader.events = lambda self, start, end: (TEST_EVENTS, False)\nmain()\n'
        source='TEST_ROWS = '+repr(rows)+'\nTEST_EVENTS = '+repr(events)+'\n'+source
        at=AppTest.from_string(source)
        at.secrets["supabase"]=config()
        at.run(timeout=20)
        self.assertEqual(len(at.exception),0)
        self.assertEqual(len(at.metric),6)
        self.assertEqual(len(at.error),0)
        self.assertEqual([x.label for x in at.tabs],["Grafikonok","Mérési táblázat és letöltés","Eseménynapló"])
        self.assertEqual(len(at.get("download_button")),2)


if __name__=="__main__":
    unittest.main()
