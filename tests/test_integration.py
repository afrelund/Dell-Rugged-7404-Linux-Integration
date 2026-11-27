import contextlib
import importlib.machinery
import importlib.util
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
