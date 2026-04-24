# Home Internet Tester

Always-on home internet monitor that pings Google DNS, Cloudflare DNS, and your local router every 30 seconds, stores results in SQLite, and serves a dashboard on your LAN. Built to run in Docker on a Raspberry Pi.

## What it answers

- Is the internet up *right now*?
- How long has it been up since the last outage?
- When were the recent outages, how long, and was it the **ISP** (gateway responded, external didn't) or **local** (everything failed)?
- When do outages cluster (heatmap by hour-of-day and day-of-week)?

Old data (>7 days by default) auto-archives to per-day JSON files in `data/archive/` so you can keep history forever without growing the live DB.

## Quickstart

```bash
cp .env.example .env       # edit TZ to your local timezone
docker compose up -d
```

Then open `http://<pi-ip>:8000` from any device on your LAN.

For local dev on a Mac:

```bash
docker compose up --build
# dashboard at http://localhost:8000
```

**Deploying on a Raspberry Pi 4B with an external SSD:** see [docs/raspberry-pi-setup.md](docs/raspberry-pi-setup.md). SSD-boot is strongly recommended — this app writes to SQLite every 30s forever, which wears out SD cards.

## How it talks to your network

- `network_mode: host` — the container shares the Pi's network stack. The dashboard appears on `<pi-ip>:8000` directly, and the container's default route *is* your real LAN gateway, so router probing works without configuring an IP.
- `cap_add: [NET_RAW]` — needed for real ICMP pings (the `ping` command equivalent). Without this it falls back to TCP probes on port 53.

## Outage classification

When all external targets fail simultaneously, the tester checks whether the gateway also failed during that window:

- **isp** — gateway responded but external didn't → upstream / WAN / ISP issue
- **local** — both failed → likely your router, modem, or LAN
- **partial** — at least one external responded → degraded, not a full outage

A failure has to last ≥ 2 consecutive cycles (60s by default) to count as an outage. This filters out single-packet noise.

## Giving data to your ISP

The dashboard has **Download CSV** and **Download JSON** buttons that export the last 7 days of raw probes. The outage list shows start time, end time, duration, and classification — that's exactly the kind of evidence support reps respond to.

## Tweaking

All config is via env vars in `.env` (see `.env.example`):

| Var | Default | Notes |
|---|---|---|
| `PROBE_INTERVAL_SEC` | 30 | Lower = more granular but more rows |
| `RETENTION_DAYS` | 7 | Live DB retention; older data goes to JSON |
| `PROBE_TIMEOUT_SEC` | 2 | Per-probe timeout |
| `TARGETS` | `google=8.8.8.8,cloudflare=1.1.1.1` | Comma-separated `name=ip` pairs |
| `GATEWAY_IP` | auto | Override gateway auto-detection |
| `TZ` | `America/New_York` | Affects heatmap labels |

## Cross-arch builds

The Pi is arm64 and so is Apple Silicon, so the image built locally on a Mac runs on the Pi as-is. If you build from an x86 host, use `docker buildx build --platform linux/arm64`.
