# Raspberry Pi 4B + External SSD setup

This guide gets a Pi 4B running uplog 24/7, **booting directly from an external SSD** with no SD card involved. SSD-boot is recommended over SD because uplog writes to SQLite every 30 seconds forever, which is the exact workload that wears out SD cards.

## What you need

- Raspberry Pi 4B (any RAM size — 2 GB is plenty for this app)
- Official **5V / 3A USB-C** power supply (cheap supplies cause undervoltage warnings, especially with an SSD attached)
- USB 3.0 SSD enclosure or USB-SSD (e.g. Samsung T7, SanDisk Extreme, or any 2.5" SATA SSD in a USB 3 enclosure)
  - Prefer enclosures with **UASP** support — much faster, fewer quirks
  - Avoid no-name JMicron-bridge enclosures; they're known for I/O hangs on the Pi
- A computer (Mac/Windows/Linux) to flash the SSD with Raspberry Pi Imager
- Network connection (Ethernet preferred for a monitor; Wi-Fi works too)

## Effect on uplog

None — the app writes to whatever directory you bind-mount as `./data` in `docker-compose.yml`. By putting the whole project (and OS) on the SSD, every read/write hits the SSD instead of an SD card. No code changes.

---

## Step 1 — Update bootloader (older Pi 4Bs only)

If you bought your Pi 4B in 2021 or later, USB boot is already enabled in the EEPROM and you can skip this step.

If older or unsure: boot it from any SD card with a current Raspberry Pi OS, then run:

```bash
sudo rpi-eeprom-update -a
sudo reboot
```

After reboot, confirm boot order prefers USB:

```bash
sudo rpi-eeprom-config | grep BOOT_ORDER
```

You want `BOOT_ORDER=0xf41` (try SD → USB → repeat) or `0xf14` (try USB → SD → repeat). To set it explicitly:

```bash
sudo rpi-eeprom-config --edit
# change BOOT_ORDER=0xf14, save
sudo reboot
```

You can now eject the SD card forever.

## Step 2 — Flash Raspberry Pi OS to the SSD

On your Mac:

1. Plug the SSD into your Mac via the USB enclosure.
2. Install **Raspberry Pi Imager** (`brew install --cask raspberry-pi-imager` or [download](https://www.raspberrypi.com/software/)).
3. Open Imager → **Choose Device**: Raspberry Pi 4 → **Choose OS**: Raspberry Pi OS Lite (64-bit) → **Choose Storage**: your SSD.
4. Click the **gear icon** (or `Cmd+Shift+X`) to set:
   - hostname (e.g. `uplog-pi`)
   - username + password (default `pi` is fine, or pick your own)
   - **Enable SSH** with password auth
   - Wi-Fi credentials (skip if using Ethernet)
   - Locale + timezone (e.g. `America/New_York`)
5. **Write**.
6. When finished, eject and unplug the SSD.

## Step 3 — Boot the Pi from SSD

1. Make sure no SD card is inserted.
2. Plug the SSD into one of the Pi's **blue USB 3.0 ports** (not the black USB 2.0 ones).
3. Connect Ethernet (recommended) and power it on.
4. After ~30 seconds, find its IP. From your Mac:
   ```bash
   ping uplog-pi.local
   # or scan your LAN
   arp -a | grep -i b8:27:eb  # older Pi MAC prefix
   arp -a | grep -i dc:a6:32  # Pi 4 MAC prefix
   ```
5. SSH in:
   ```bash
   ssh pi@uplog-pi.local
   ```

## Step 4 — Install Docker

Once you're SSH'd in:

```bash
sudo apt update && sudo apt full-upgrade -y
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker     # or just log out and back in
docker --version  # confirm
```

The convenience script also installs the `docker compose` plugin.

## Step 5 — Clone and run uplog

```bash
git clone https://github.com/kahlow/uplog.git
cd uplog
cp .env.example .env

# (optional) edit .env to set your timezone
# nano .env

docker compose up -d
docker compose logs -f
```

After ~30 seconds you should see probe-cycle logs. Hit `Ctrl-C` to leave the log tail (the container keeps running).

## Step 6 — Open the dashboard

From any device on your LAN:

```
http://uplog-pi.local:8000
http://<pi-ip>:8000
```

Bookmark it.

## Step 7 — Make sure it survives reboots

It already will — `restart: unless-stopped` in `docker-compose.yml` plus Docker's systemd unit means the container comes back automatically after a power cycle or `sudo reboot`. Test it once:

```bash
sudo reboot
# wait 60 seconds, then re-check the dashboard
```

---

## Troubleshooting

**Pi won't boot from SSD.** Re-do Step 1 (EEPROM update + boot order). Some very early Pi 4Bs (2019) need the EEPROM update before they'll see USB devices at boot at all.

**Dashboard isn't reachable from other devices on the LAN.** Check the Pi's firewall (`sudo ufw status` — most Pi OS images don't have one enabled by default). Confirm the container is running: `docker compose ps`. Check it's bound to all interfaces: `ss -tlnp | grep 8000` should show `0.0.0.0:8000`.

**`gateway` target shows as down or auto-detect failed.** This means `/proc/net/route` didn't expose a default gateway when the app started. Set it explicitly in `.env`:
```
GATEWAY_IP=192.168.1.1   # whatever your router's LAN IP is
```
Then `docker compose up -d` to apply.

**`tcp` showing in the method column instead of `icmp`.** That means the `cap_add: NET_RAW` in `docker-compose.yml` isn't taking effect. Confirm the container actually has the cap: `docker inspect uplog | grep -A3 CapAdd`. If you removed it, add it back — ICMP probes are the "real" ping and what your ISP will recognize.

**Random USB I/O errors / SSD disconnecting.** Cheap JMicron USB-SATA bridges sometimes need a UAS quirk to behave on the Pi. Find your enclosure's vendor/product ID with `lsusb`, then add a kernel param:
```bash
sudo nano /boot/firmware/cmdline.txt
# append (on the same line, space-separated):
usb-storage.quirks=VVVV:PPPP:u
sudo reboot
```
(Replace `VVVV:PPPP` with the actual IDs from `lsusb`.)

**Undervoltage warnings.** `dmesg | grep -i voltage` — if you see them, you need a beefier power supply. Use the official Pi 4B 5V/3A USB-C unit. Some SSDs draw enough current that even that isn't enough; in that case, use a powered USB hub between the Pi and the SSD.

## Updating uplog later

```bash
cd ~/uplog
git pull
docker compose up -d --build
```

Your `data/` directory is preserved across rebuilds because it's a bind mount.
