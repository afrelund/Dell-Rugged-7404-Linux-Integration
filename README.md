# Dell Latitude 14 Rugged Extreme (7404) – Linux integration

Fixes for Ubuntu (tested on Ubuntu 26.04 LTS) on the Latitude 14 Rugged Extreme (7404) only:

- **Touchscreen** (eGalax `0eef:0001`): correct classification and no autosuspend.
- **Built-in speaker**: the speaker is driven through the HDA *Headphone* control.
  The helper locates the **HDA Intel PCH** sound card (not HDMI) automatically.
  While the headphone jack is unplugged, a user service keeps the **Headphone and
  Headset switches unmuted** and **Headphone Playback Volume at 100%**. Plugged-in
  headphones are never touched.

## Install (stand-alone .deb)

1. Download the latest `dell-rugged-7404_*_all.deb` from the
   [Releases page](https://github.com/afrelund/Dell-Rugged-7404-Linux-Integration/releases/latest).
2. Install it:

   ```sh
   sudo apt install ./dell-rugged-7404_1.9.1_all.deb
   ```

3. Nothing is enabled automatically. Open **Dell Rugged 7404 Setup** from the app menu
   (it also opens once at your next login) and click **Install** next to the touchscreen
   repair, speaker fix, GPS support or graphics check. Each row shows whether it is
   installed; administrator steps ask for your password.
   The Setup window covers: touchscreen repair, speaker fix, GPS support, graphics driver,
   smart card / ID card (CAC), RFID / NFC reader, 4G LTE modem, software-defined radio (RTL-SDR),
   battery health and firmware updates. Buttons are **red** (not installed), **orange**
   (error / needs attention) and **green** (installed and working).
4. Lower the volume, then test sound from the built-in speaker. Check status with:

   ```sh
   dell-speaker-check --status
   systemctl --user status dell-speaker-check.service
   ```

## GPS Monitor (desktop app)

Open **Dell Rugged GPS Monitor** from the application menu, or run `dell-gps-monitor`.

The window follows the Ubuntu **Settings → Appearance** light/dark choice and switches live.

The right side has five tabs:

- **LIVE** – coordinates in every common format (click any value to copy it), time, satellites, and the JAMMING INDICATOR. A red JAMMING ALERT appears in the title (with a beep) when interference is strong.
- **SIGNALS** – fix/DOP/accuracy dashboard, per-satellite signal-strength bars, and a jamming history graph.
- **NAVIGATE** – compass with your heading, saved waypoints, and distance/bearing to a chosen target.
- **MAP** – street map (OpenStreetMap, darkened in dark mode; needs internet) with your position, saved waypoints, "Add waypoint" (drag the map under an amber target, then confirm) or press-and-hold to add one, and a "Full map" mode that hides the satellite view.
- **TRACK** – log your position once per second to CSV, and export the session as GPX (with waypoints). Files go to `~/GPS-Tracks`.
- **TOOLS** – sunrise/sunset/daylight for your position, and receiver setup (enable/disable Galileo, GLONASS, BeiDou; 1/2/5 Hz update rate). Setup buttons ask for confirmation and are not saved to the receiver's flash.

On first launch the app pins itself to the Ubuntu dock (once; unpin it and it stays unpinned). Run `dell-gps-monitor --pin-dock` to pin without opening the window.
It shows a satellite sky plot (colored by GPS, Galileo, GLONASS, BeiDou, SBAS, QZSS;
filled = used in the fix; dB-Hz under each satellite), your position as decimal
degrees, degrees/decimal minutes, degrees/minutes/seconds, UTM, MGRS / US National
Grid and Maidenhead, altitude, GPS time (with week and time of week), UTC, local
time, and the u-blox jamming indicator with antenna status. It is read-only:
nothing is written to the receiver. GPS time is UTC plus 18 leap seconds.

## Status and install progress (terminal)

```sh
dell-rugged-7404-status            # what is installed / working (OK, WORK, TODO)
dell-rugged-7404-status --watch    # live view, refreshes every 2 seconds
dell-rugged-7404-status --install  # installs missing packages one by one with progress
dell-gpu-check                     # which GPUs and drivers are in use
dell-gps-check                     # GPS fix, satellites, signal strength, jamming indicator
```

These are also in the application menu ("Dell Rugged 7404 Setup" and
"Dell Rugged 7404 Status"). The package also attaches a u-blox USB GPS receiver
to gpsd; view the fix with `cgps -s`. The Latitude's NVIDIA GT 720M has no
proprietary driver in Ubuntu 26.04, so the in-kernel `nouveau` driver is used;
`dell-gpu-check --install` only installs a driver Ubuntu itself recommends.

Upgrading from 1.0.0 is the same `apt install` command, followed by a
re-login (or `systemctl --user restart dell-speaker-check.service`).

Remove with `sudo apt remove dell-rugged-7404`. The package refuses to enable
itself on any other laptop model. A "Dell Rugged 7404 Setup" entry is added to
the application menu.

## Other install methods

Build the .deb yourself with `sh deb/build.sh` (output in `dist/`), or use
`python3 install.py` (see [INSTALL.txt](INSTALL.txt)). Do not combine the two.

## Tests

```sh
python3 -m unittest discover -s tests -v
```
