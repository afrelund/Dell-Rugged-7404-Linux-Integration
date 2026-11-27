# Dell Latitude 14 Rugged Extreme (7404) – Linux integration

Fixes for Ubuntu on the Latitude 14 Rugged Extreme (7404) only:

- **Touchscreen** (eGalax `0eef:0001`): correct classification and no autosuspend.
- **Built-in speaker**: the speaker is driven through the HDA *Headphone* control.
  While the headphone jack is unplugged, a user service keeps **Headphone Playback
  Switch unmuted** and **Headphone Playback Volume at 100%**. Plugged-in
  headphones are never touched.

## Install (stand-alone .deb)

1. Download the latest `dell-rugged-7404_*_all.deb` from the
   [Releases page](https://github.com/afrelund/Dell-Rugged-7404-Linux-Integration/releases/latest).
2. Install it:

   ```sh
   sudo apt install ./dell-rugged-7404_1.0.1_all.deb
   ```

3. Log out and back in (or run
   `systemctl --user enable --now dell-speaker-check.service`) to start the speaker helper.
4. Lower the volume, then test sound from the built-in speaker. Check status with:

   ```sh
   dell-speaker-check --status
   systemctl --user status dell-speaker-check.service
   ```

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
