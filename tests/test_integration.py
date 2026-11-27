import contextlib
import importlib.machinery
import importlib.util
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
import os
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


audio = load("audio", ROOT / "files/dell-speaker-check")
touch = load("touch", ROOT / "files/egalax-touchscreen-check")
installer = load("installer", ROOT / "install.py")
status = load("status", ROOT / "deb/dell-rugged-7404/usr/bin/dell-rugged-7404-status")
setup = load("setup", ROOT / "deb/dell-rugged-7404/usr/bin/dell-rugged-7404-setup")
gps = load("gps", ROOT / "deb/dell-rugged-7404/usr/bin/dell-gps-monitor")
SWITCH_OFF = " : values=off,off\n"
SWITCH_ON = " : values=on,on\n"
VOLUME = "  ; type=INTEGER,min=0,max=87,step=0\n  : values=12,14\n"


class AudioSafetyTests(unittest.TestCase):
    def test_connected_headphones_are_never_changed(self):
        with patch.object(audio, "amixer", return_value=" : values=on\n") as mixer:
            self.assertIn("left alone", audio.check())
        mixer.assert_called_once_with("cget", audio.JACK)

    def test_unplugged_speaker_unmutes_and_sets_volume(self):
        with patch.object(audio, "jack_connected", side_effect=[False, False, False]), \
                patch.object(audio, "switches", return_value=[audio.SWITCH]), \
                patch.object(audio, "amixer", side_effect=[VOLUME, SWITCH_OFF, "", ""]) as mixer:
            self.assertIn("Unmuted", audio.check())
        self.assertEqual(mixer.call_args_list[-2].args, ("cset", audio.SWITCH, "on,on"))
        self.assertEqual(mixer.call_args_list[-1].args, ("cset", audio.VOLUME, "87,87"))

    def test_healthy_state_makes_no_writes(self):
        with patch.object(audio, "jack_connected", return_value=False), \
                patch.object(audio, "switches", return_value=[audio.SWITCH]), \
                patch.object(audio, "amixer",
                             side_effect=["  ; type=INTEGER,min=0,max=87,step=0\n  : values=87,87\n", SWITCH_ON]) as mixer:
            self.assertIn("healthy", audio.check())
        self.assertEqual(mixer.call_count, 2)

    def test_status_is_read_only(self):
        with patch.object(audio, "jack_connected", return_value=False), \
                patch.object(audio, "switches", return_value=[audio.SWITCH]), \
                patch.object(audio, "amixer", side_effect=[VOLUME, SWITCH_OFF]) as mixer:
            self.assertIn("muted", audio.check(status_only=True))
        self.assertEqual(mixer.call_count, 2)

    def test_insertion_before_write_prevents_change(self):
        with patch.object(audio, "jack_connected", side_effect=[False, True]), \
                patch.object(audio, "switches", return_value=[audio.SWITCH]), \
                patch.object(audio, "amixer", side_effect=[VOLUME, SWITCH_OFF]) as mixer:
            audio.check()
        self.assertEqual(mixer.call_count, 2)

    def test_insertion_during_write_restores_previous_settings(self):
        with patch.object(audio, "jack_connected", side_effect=[False, False, True]), \
                patch.object(audio, "switches", return_value=[audio.SWITCH]), \
                patch.object(audio, "amixer", side_effect=[VOLUME, SWITCH_OFF, "", "", "", ""]) as mixer:
            self.assertIn("restored previous", audio.check())
        self.assertEqual(mixer.call_args_list[-2].args, ("cset", audio.VOLUME, "12,14"))
        self.assertEqual(mixer.call_args_list[-1].args, ("cset", audio.SWITCH, "off,off"))

    def test_unknown_jack_state_fails_without_write(self):
        with patch.object(audio, "amixer", return_value=" : values=unknown\n") as mixer:
            with self.assertRaisesRegex(RuntimeError, "Unknown headphone"):
                audio.check()
        mixer.assert_called_once_with("cget", audio.JACK)

    def test_missing_volume_limits_fails_without_write(self):
        with patch.object(audio, "jack_connected", return_value=False), \
                patch.object(audio, "amixer", return_value=" : values=12,14\n") as mixer:
            with self.assertRaisesRegex(RuntimeError, "limits unavailable"):
                audio.check()
        mixer.assert_called_once_with("cget", audio.VOLUME)


class CardDiscoveryTests(unittest.TestCase):
    CARDS = " 0 [HDMI           ]: HDA-Intel - HDA Intel HDMI\n                      HDA Intel HDMI at 0x1 irq 62\n 1 [PCH            ]: HDA-Intel - HDA Intel PCH\n                      HDA Intel PCH at 0x2 irq 63\n"

    def test_finds_pch_card_number(self):
        with patch.object(Path, "read_text", return_value=self.CARDS):
            self.assertEqual(audio.card(), "1")

    def test_discovers_headphone_and_headset_switches(self):
        controls = ("numid=1,iface=MIXER,name='Headphone Playback Switch'\n"
                    "numid=2,iface=MIXER,name='Headset Mic Capture Switch'\n"
                    "numid=3,iface=MIXER,name='Master Playback Switch'\n")
        with patch.object(audio, "amixer", return_value=controls):
            self.assertEqual(len(audio.switches()), 2)


class GpsMonitorTests(unittest.TestCase):
    def test_mgrs_known_points(self):
        self.assertEqual(gps.to_mgrs(0.0, 0.0), "31N AA 66021 00000")
        self.assertTrue(gps.to_mgrs(38.8895, -77.0353).startswith("18S UJ 234"))

    def test_utm_southern_hemisphere_and_zone_exceptions(self):
        zone, hemisphere, _, northing = gps.to_utm(-33.8568, 151.2153)
        self.assertEqual((zone, hemisphere), (56, "S"))
        self.assertGreater(northing, 6000000)
        self.assertEqual(gps.utm_zone(60.0, 5.0), 32)

    def test_degree_formats_round_without_overflow(self):
        self.assertEqual(gps.dms(10.99999999, "N", "S"), "11°00'00.00\"N")
        self.assertEqual(gps.ddm(-109.5, "E", "W"), "109°30.0000'W")

    def test_gps_time_is_ahead_of_utc(self):
        lines = dict(gps.time_lines(gps.parse_gps_utc("2026-11-27T16:24:33.000Z")))
        self.assertTrue(lines["GPS time"].startswith("2026-11-27 16:24:51"))

    def test_mon_hw_parsing(self):
        parsed = gps.parse_mon_hw("aStatus 2 aPower 1 flags x5 reserved1 1\n jamInd 77 reserved2")
        self.assertEqual((parsed["jam"], parsed["antenna"], parsed["jam_state"]), (77, "OK", "OK"))
        self.assertEqual(gps.jam_level(150)[0], "STRONG interference")


class TouchSafetyTests(unittest.TestCase):
    def test_only_exact_usb_id_matches(self):
        with tempfile.TemporaryDirectory() as directory:
            device = Path(directory)
            (device / "idVendor").write_text("0eef\n")
            (device / "idProduct").write_text("0001\n")
            self.assertTrue(touch.matches(device))
            (device / "idProduct").write_text("0002\n")
            self.assertFalse(touch.matches(device))

    def test_reconnect_rechecks_identity_before_writing(self):
        with patch.object(touch, "matches", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "identity changed"):
                touch.reconnect(Path("/not-a-device"))

    def test_check_only_never_changes_power_or_reconnects(self):
        device = Mock()
        device.name = "mock-touchscreen"
        power = device.__truediv__ = Mock(return_value=Mock())
        power.return_value.read_text.return_value = "auto\n"
        with patch.object(touch, "USB_ROOT") as usb, \
                patch.object(touch, "RULE") as rule, \
                patch.object(touch, "matches", return_value=True), \
                patch.object(touch, "classified", return_value=True), \
                patch.object(touch, "reconnect") as reconnect, \
                patch.object(touch, "run") as run, \
                contextlib.redirect_stdout(io.StringIO()):
            usb.iterdir.return_value = [device]
            rule.is_file.return_value = True
            touch.check(Mock(check_only=True))
        power.return_value.write_text.assert_not_called()
        reconnect.assert_not_called()
        run.assert_not_called()

    def test_classification_rejects_mouse_and_tablet_tags(self):
        with patch.object(touch, "events", return_value=[Path("/fake/event1")]), \
                patch.object(touch, "run",
                             return_value="ID_INPUT_TOUCHSCREEN=1\nID_INPUT_TABLET=1\n"):
            self.assertFalse(touch.classified(Path("/fake")))


class InstallerTests(unittest.TestCase):
    def test_dry_run_executes_no_subprocesses(self):
        with patch.object(installer.subprocess, "run") as run, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            installer.install(Path("/home/example"), dry_run=True)
        run.assert_not_called()
        self.assertIn("DRY RUN", output.getvalue())
        self.assertIn("/home/example/.local/bin", output.getvalue())
        self.assertNotIn(str(Path.home()) + "/",
                         output.getvalue().replace(str(ROOT), "SOURCE"))

    def test_preflight_rejects_root(self):
        with patch.object(installer.os, "getuid", return_value=0):
            with self.assertRaisesRegex(RuntimeError, "without sudo"):
                installer.preflight(Path("/root"))

    def test_preflight_rejects_other_models_before_commands(self):
        with patch.object(installer.os, "getuid", return_value=1000), \
                patch.object(Path, "read_text", return_value="Other laptop"), \
                patch.object(installer, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "Unsupported model"):
                installer.preflight(Path("/home/example"))
        run.assert_not_called()

    def test_backups_precede_every_install(self):
        calls = []

        def record(*args, **kwargs):
            calls.append(tuple(str(arg) for arg in args))
            if "mktemp" in args:
                return "/var/backups/dell-rugged-7404.TEST"
            return ""

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(installer, "run", side_effect=record), \
                contextlib.redirect_stdout(io.StringIO()):
            destination = Path(directory) / "existing"
            destination.write_text("original")
            with patch.object(installer, "targets",
                              return_value=[("dell-speaker-check", destination, "0755", False)]):
                installer.install(Path(directory))
        backup = next(index for index, args in enumerate(calls) if "cp" in args)
        write = next(index for index, args in enumerate(calls) if "install" in args)
        self.assertLess(backup, write)
        self.assertEqual(destination.parent.exists(), False)

    def test_backup_failure_prevents_replacement(self):
        calls = []

        def fail_backup(*args, **kwargs):
            calls.append(args)
            if "cp" in args:
                raise subprocess.CalledProcessError(1, args)
            return "/var/backups/dell-rugged-7404.TEST"

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(installer, "run", side_effect=fail_backup), \
                contextlib.redirect_stdout(io.StringIO()):
            destination = Path(directory) / "existing"
            destination.write_text("original")
            with patch.object(installer, "targets",
                              return_value=[("dell-speaker-check", destination, "0755", False)]):
                with self.assertRaises(subprocess.CalledProcessError):
                    installer.install(Path(directory))
            self.assertEqual(destination.read_text(), "original")
        self.assertFalse(any("install" in args for args in calls))

    def test_audio_service_uses_installing_users_home(self):
        unit = (ROOT / "files/dell-speaker-check.service").read_text()
        self.assertIn("%h/.local/bin/dell-speaker-check", unit)
        self.assertNotIn(str(Path.home()) + "/", unit)


class GpsNavigationTests(unittest.TestCase):
    def test_bearing_distance_and_compass(self):
        metres, bearing = gps.bearing_distance(0, 0, 0, 1)
        self.assertAlmostEqual(metres, 111195, delta=100)
        self.assertAlmostEqual(bearing, 90, delta=0.01)
        self.assertEqual((gps.compass_point(0), gps.compass_point(135), gps.compass_point(355)),
                         ("N", "SE", "N"))
        self.assertEqual(gps.turn_hint(350, 10), "20° right")
        self.assertEqual(gps.turn_hint(10, 350), "20° left")

    def test_sun_times_salt_lake_midsummer(self):
        import datetime
        rise, sunset = gps.sun_times(40.77, -111.89, datetime.date(2026, 6, 21))
        self.assertAlmostEqual(rise.hour + rise.minute / 60, 11.8, delta=0.15)
        self.assertAlmostEqual((sunset.hour + sunset.minute / 60) % 24, 3.05, delta=0.15)
        self.assertIsNone(gps.sun_times(80, 0, datetime.date(2026, 6, 21)))

    def test_gpx_escapes_names_and_lists_points(self):
        text = gps.gpx_text([{"time": "2026-01-01T00:00:00Z", "lat": 1.0, "lon": 2.0, "alt": 3.0}],
                            [{"name": "A&B", "lat": 4.0, "lon": 5.0}])
        self.assertIn("<name>A&amp;B</name>", text)
        self.assertIn('<trkpt lat="1.0000000" lon="2.0000000"><ele>3.0</ele>', text)

    def test_waypoints_round_trip_and_bad_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "sub" / "waypoints.json")
            self.assertEqual(gps.load_waypoints(path), [])
            gps.save_waypoints(path, [{"name": "Camp", "lat": 1.5, "lon": 2.5}])
            self.assertEqual(gps.load_waypoints(path)[0]["name"], "Camp")

    def test_dop_quality(self):
        self.assertEqual(gps.dop_quality(1.2)[0], "good")
        self.assertEqual(gps.dop_quality(8)[0], "poor")
        self.assertEqual(gps.dop_quality(None)[0], "-")


class CoordinateInputTests(unittest.TestCase):
    def test_formats_are_recognised(self):
        for text, kind in (("40.4656, -109.53", "Decimal degrees"),
                           ("40°27.936'N 109°31.8'W", "Degrees + decimal minutes"),
                           ("40 27 56.2 N, 109 31 48 W", "Degrees minutes seconds"),
                           ("12T XK 24624 80474", "MGRS / US National Grid"),
                           ("12T 624624 4480474", "UTM")):
            lat, lon, found = gps.parse_coordinate(text)
            self.assertEqual(found, kind)
            self.assertAlmostEqual(lat, 40.4656, places=3)
            self.assertAlmostEqual(lon, -109.53, places=3)

    def test_mgrs_round_trip_and_rejects_text(self):
        for lat, lon in ((-33.9, 151.2), (47.6, -122.3), (0.5, 10.2)):
            got = gps.parse_coordinate(gps.to_mgrs(lat, lon))
            self.assertAlmostEqual(got[0], lat, places=3)
            self.assertAlmostEqual(got[1], lon, places=3)
        self.assertIsNone(gps.parse_coordinate("123 Main Street, Vernal UT"))


class OfflineRoutingTests(unittest.TestCase):
    TEXT = ("# header\n#\n"
            " 39.1\t -75.5\t      -1 \tWaypt#1\t0.000\t 0.00\t 0.00\t  0.0\t\t\t\n"
            " 39.2\t -75.5\t   1*\tJunct\t1.500\t 2.00\t 1.50\t  2.0\t 80\t  74\tMain Street\n"
            " 39.3\t -75.5\t   2*\tJunct\t0.500\t 1.00\t 2.00\t  3.0\t 80\t  74\tMain Street\n"
            " 39.4\t -75.5\t   3 \tJunct\t3.000\t 4.00\t 5.00\t  7.0\t 80\t  74\t(null)\n")

    def test_route_text_is_parsed_into_legs(self):
        points = gps.parse_route_text(self.TEXT)
        self.assertEqual(len(points), 4)
        self.assertEqual(points[-1]["total_km"], 5.0)
        steps = gps.route_steps(points)
        self.assertEqual([(s["road"], round(s["km"], 1)) for s in steps],
                         [("Main Street", 2.0), ("unnamed road", 3.0)])
        self.assertEqual([(s["first"], s["last"]) for s in steps], [(0, 2), (2, 3)])

    def test_routing_without_a_downloaded_area_explains_itself(self):
        with patch.object(gps, "MAPS_DIR", "/nonexistent-maps"):
            with self.assertRaises(gps.RouteError):
                gps.compute_route(1, 2, 3, 4)

    def test_every_state_has_a_geofabrik_slug(self):
        self.assertEqual(gps.geofabrik_slug(gps.STATES["33"]), "new-hampshire")
        self.assertEqual(gps.format_duration(75), "1 h 15 min")


class SetupAppTests(unittest.TestCase):
    def test_components_report_state_for_each_item(self):
        with unittest.mock.patch.object(status, "component_touchscreen", return_value=("missing", "x")), \
             unittest.mock.patch.object(status, "component_speaker", return_value=("installed", "y")), \
             unittest.mock.patch.object(status, "component_gps", return_value=("partial", "z")), \
             unittest.mock.patch.object(status, "component_graphics", return_value=("installed", "w")), \
             unittest.mock.patch.object(status, "component_smartcard", side_effect=RuntimeError("boom")):
            items = status.components()
        ids = [i["id"] for i in items]
        self.assertEqual(ids[:4], ["touchscreen", "speaker", "gps", "graphics"])
        self.assertEqual({"smartcard", "rfid", "lte", "sdr", "battery", "firmware"}, set(ids[4:]))
        self.assertEqual([i["state"] for i in items][:4], ["missing", "installed", "partial", "installed"])
        self.assertEqual(items[ids.index("smartcard")]["state"], "partial")

    def test_smartcard_needs_packages_then_reader(self):
        with unittest.mock.patch.object(status, "installed", return_value=False):
            self.assertEqual(status.component_smartcard()[0], "missing")
        with unittest.mock.patch.object(status, "installed", return_value=True), \
             unittest.mock.patch.object(status, "run", return_value=(0, "active")), \
             unittest.mock.patch.object(status, "card_readers", return_value=[]):
            self.assertEqual(status.component_smartcard()[0], "partial")
        with unittest.mock.patch.object(status, "installed", return_value=True), \
             unittest.mock.patch.object(status, "run", return_value=(0, "active")), \
             unittest.mock.patch.object(status, "card_readers", return_value=["Broadcom Contactless"]):
            self.assertEqual(status.component_smartcard()[0], "installed")

    def test_apply_rejects_unknown_component_and_non_root(self):
        with contextlib.redirect_stdout(io.StringIO()), unittest.mock.patch.object(status.os, "geteuid", return_value=1000):
            self.assertEqual(status.apply("bogus"), 2)
            self.assertEqual(status.apply("gps"), 1)

    def test_only_speaker_runs_without_pkexec(self):
        with unittest.mock.patch.object(setup.os, "geteuid", return_value=1000):
            self.assertEqual(setup.install_command("speaker")[0], setup.STATUS_TOOL)
            self.assertEqual(setup.install_command("gps")[0], "pkexec")

    def test_state_colours_have_button_styles(self):
        css = setup.build_css()
        for state, (_badge, colour, _action) in setup.STATES.items():
            self.assertIn(f"state-{setup.COLOUR_NAME[colour]}", css)
            self.assertIn(colour, css)
        self.assertIn("min-height: 48px", css)


class ElevationProfileTests(unittest.TestCase):
    def test_sampling_and_stats(self):
        path = [(40.0, -109.0), (40.0, -108.99), (40.01, -108.99)]
        samples = gps.sample_path(path, 10)
        self.assertEqual(len(samples), 10)
        self.assertAlmostEqual(samples[0][0], 0)
        self.assertAlmostEqual(samples[-1][1], 40.01)
        stats = gps.profile_stats([(0, 100), (1, 150), (2, 120), (3, 130)])
        self.assertEqual((stats["gain"], stats["loss"], stats["min"], stats["max"]), (60, 30, 100, 150))


class ImageryTests(unittest.TestCase):
    def test_tile_math_and_counts(self):
        self.assertEqual(gps.tile_xy(0, 0, 1), (1, 1))
        self.assertEqual(gps.tile_xy(40.7, -109.5, 0), (0, 0))
        bbox = (40.0, -110.0, 41.0, -109.0)
        self.assertEqual(len(list(gps.tiles_for_bbox(bbox, 8, 10))), gps.count_tiles(bbox, 8, 10))
        self.assertGreater(gps.count_tiles(bbox, 8, 12), gps.count_tiles(bbox, 8, 10))

    def test_geojson_bbox(self):
        data = {"features": [{"geometry": {"coordinates": [[[[-110, 40], [-109, 41], [-109.5, 40.5]]]]}}]}
        self.assertEqual(gps.geojson_bbox(data), (40, -110, 41, -109))


class CellTowerTests(unittest.TestCase):
    def test_import_query_and_colours(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = os.path.join(tmp, "t.csv")
            with open(csv_path, "w") as handle:
                handle.write("radio,mcc,net,area,cell,unit,lon,lat,range,samples,changeable,created,updated,averageSignal\n"
                             "LTE,310,260,100,7,0,-109.5,40.4,500,3,1,0,0,0\n"
                             "GSM,310,260,100,8,0,-100.0,35.0,500,3,1,0,0,0\n")
            with patch.object(gps, "CELLS_DIR", tmp), patch.object(gps, "CELL_DB", os.path.join(tmp, "c.db")):
                self.assertEqual(gps.import_cell_csv(csv_path), 2)
                found = gps.cells_in_bbox(40, -110, 41, -109)
                self.assertEqual([(r[0], r[4]) for r in found], [("LTE", 7)])
        self.assertEqual(gps.signal_color(None), "#d32f2f")
        self.assertEqual([gps.signal_color(q) for q in (10, 50, 90)], ["#ef8f00", "#fbc02d", "#2e7d32"])

    def test_area_download_filters_to_downloaded_counties(self):
        import gzip, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            data = ("LTE,310,260,1,1,0,-109.5,40.4,1,1,1,0,0,0\nLTE,310,260,1,2,0,-90.0,30.0,1,1,1,0,0,0\n")

            def fake_download(url, dest, progress=None):
                self.assertIn("downloads.php?token=KEY&type=mcc&file=", url)
                with gzip.open(dest, "wt") as handle:
                    handle.write(data)
            with patch.object(gps, "CELLS_DIR", tmp), patch.object(gps, "CELL_DB", os.path.join(tmp, "c.db")), \
                    patch.object(gps, "CELL_TOKEN", os.path.join(tmp, "token")), \
                    patch.object(gps, "download_file", fake_download), \
                    patch.object(gps, "downloaded_county_bboxes", lambda: {"x": (40, -110, 41, -109)}):
                self.assertEqual(gps.download_cells_for_areas("KEY", mccs=(310,)), 1)
                self.assertEqual(gps.cell_count(), 1)
                self.assertEqual(gps.load_cell_token(), "KEY")

    def test_mmcli_keyvalue(self):
        self.assertEqual(gps.parse_mmcli_keyvalue("modem.generic.state : failed\nbad line\n")["modem.generic.state"],
                         "failed")


if __name__ == "__main__":
    unittest.main()
