#!/usr/bin/env python3
"""Install the verified Dell Latitude 7404 touchscreen and speaker workarounds.

Run as the desktop user, NOT with sudo:
    python3 install.py --dry-run
    python3 install.py

The installer asks sudo for system-file operations only. It does not download
code, install packages, change the desktop audio profile, or restore ALSA state.
"""

import argparse
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

MODEL = "Latitude 14 Rugged Extreme (7404)"
FILES = Path(__file__).resolve().parent / "files"


def targets(home):
    return [
        ("99-egalax-touchscreen.rules",
         Path("/etc/udev/rules.d/99-egalax-touchscreen.rules"), "0644", True),
        ("egalax-touchscreen-check",
         Path("/usr/local/sbin/egalax-touchscreen-check"), "0755", True),
        ("egalax-touchscreen-check.service",
         Path("/etc/systemd/system/egalax-touchscreen-check.service"), "0644", True),
        ("egalax-touchscreen-check.timer",
         Path("/etc/systemd/system/egalax-touchscreen-check.timer"), "0644", True),
        ("dell-speaker-check",
         home / ".local/bin/dell-speaker-check", "0755", False),
        ("dell-speaker-check.service",
         home / ".config/systemd/user/dell-speaker-check.service", "0644", False),
    ]


def run(*args, dry_run=False):
    print("+ " + shlex.join(str(arg) for arg in args), flush=True)
    if dry_run:
        return ""
    return subprocess.run(
        [str(arg) for arg in args], check=True, text=True,
        stdout=subprocess.PIPE, timeout=60,
    ).stdout.strip()


def preflight(home):
    if os.getuid() == 0:
        raise RuntimeError("Run as your desktop user, without sudo.")
    if Path("/sys/class/dmi/id/product_name").read_text().strip() != MODEL:
        raise RuntimeError("Unsupported model; this installer is only for the Dell 7404.")
    missing = [name for name in ("sudo", "systemctl", "udevadm", "amixer",
                                 "install", "cp", "mktemp")
               if shutil.which(name) is None]
    if missing:
        raise RuntimeError(
            "Missing commands: " + ", ".join(missing)
            + ". On Ubuntu install python3, alsa-utils, udev, systemd and sudo."
        )
    devices = Path("/sys/bus/usb/devices")
    found = False
    for device in devices.iterdir():
        try:
            found = (
                (device / "idVendor").read_text().strip() == "0eef"
                and (device / "idProduct").read_text().strip() == "0001"
            )
        except FileNotFoundError:
            continue
        if found:
            break
    if not found:
        raise RuntimeError("eGalax 0eef:0001 touchscreen not detected; nothing changed.")
    for name, destination, _, _ in targets(home):
        if not (FILES / name).is_file():
            raise RuntimeError(f"Installer payload missing: {name}")
        if destination.is_symlink():
            raise RuntimeError(f"Refusing to replace symlink: {destination}")
    # Read-only validation: wrong/missing ALSA controls must fail before writes.
    run(sys.executable, FILES / "dell-speaker-check", "--status")


def install(home, dry_run=False):
    # Verify a desktop user manager before touching any files.
    run("systemctl", "--user", "show-environment", dry_run=dry_run)
    if dry_run:
        backup = "/var/backups/dell-rugged-7404.DRY-RUN"
        print("DRY RUN: no files, services, input devices or mixer controls changed.")
    else:
        run("sudo", "-v")
        backup = run("sudo", "mktemp", "-d",
                     "/var/backups/dell-rugged-7404.XXXXXXXX")
    print(f"Backup directory: {backup}", flush=True)
    # Back up ALL existing targets before the first replacement.
    for _, destination, _, _ in targets(home):
        if destination.exists():
            run("sudo", "cp", "-a", "--parents", "--", destination, backup,
                dry_run=dry_run)
    for name, destination, mode, system in targets(home):
        prefix = ("sudo",) if system else ()
        run(*prefix, "install", "-D", "-m", mode, "--",
            FILES / name, destination, dry_run=dry_run)
    run("sudo", "systemctl", "daemon-reload", dry_run=dry_run)
    run("sudo", "udevadm", "control", "--reload-rules", dry_run=dry_run)
    run("systemctl", "--user", "daemon-reload", dry_run=dry_run)
    # restart (not just enable --now) also picks up updates on repeat installs.
    run("sudo", "systemctl", "enable", "egalax-touchscreen-check.timer",
        dry_run=dry_run)
    run("sudo", "systemctl", "restart", "egalax-touchscreen-check.timer",
        dry_run=dry_run)
    run("sudo", "systemctl", "start", "egalax-touchscreen-check.service",
        dry_run=dry_run)
    run("systemctl", "--user", "enable", "dell-speaker-check.service",
        dry_run=dry_run)
    run("systemctl", "--user", "restart", "dell-speaker-check.service",
        dry_run=dry_run)
    run("systemctl", "--user", "is-active", "dell-speaker-check.service",
        dry_run=dry_run)
    run("sudo", "/usr/local/sbin/egalax-touchscreen-check", "--check-only",
        dry_run=dry_run)
    print("Dry run complete." if dry_run else
          "Installation complete. Test touch input and speaker/headphone audio.")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate hardware and print writes without applying them")
    args = parser.parse_args()
    try:
        home = Path.home()
        preflight(home)
        install(home, dry_run=args.dry_run)
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Installation stopped: {error}", file=sys.stderr)
        print("If writes began, backups remain at the path printed above. "
              "See INSTALL.txt for recovery. No automatic rollback was attempted.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
