from __future__ import annotations

import logging
import os
import socket
import struct
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Target:
    name: str
    address: str
    tcp_port: int = 53
    is_external: bool = True  # gateway is internal; everything else counts toward outages


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    db_path: Path
    archive_dir: Path
    probe_interval_sec: int
    probe_timeout_sec: float
    retention_days: int
    targets: list[Target] = field(default_factory=list)


def _detect_default_gateway() -> str | None:
    """Read /proc/net/route to find the default gateway. Linux-only.

    Returns None on macOS / Windows / unreadable.
    """
    route_file = Path("/proc/net/route")
    if not route_file.exists():
        return None
    try:
        with route_file.open() as f:
            next(f)  # header
            for line in f:
                fields = line.strip().split()
                if len(fields) < 4:
                    continue
                destination = fields[1]
                flags = int(fields[3], 16)
                # 0x2 = RTF_GATEWAY, destination 00000000 = default route
                if destination == "00000000" and flags & 0x2:
                    gw_hex = fields[2]
                    gw_bytes = struct.pack("<L", int(gw_hex, 16))
                    return socket.inet_ntoa(gw_bytes)
    except (OSError, ValueError, StopIteration) as e:
        log.warning("could not parse /proc/net/route: %s", e)
    return None


def _parse_targets_env(value: str) -> list[Target]:
    out: list[Target] = []
    for pair in value.split(","):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        name, address = pair.split("=", 1)
        out.append(Target(name=name.strip(), address=address.strip()))
    return out


def load_settings() -> Settings:
    data_dir = Path(os.environ.get("DATA_DIR", "/data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    archive_dir = data_dir / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    targets_env = os.environ.get("TARGETS", "").strip()
    if targets_env:
        targets = _parse_targets_env(targets_env)
    else:
        targets = [
            Target(name="google", address="8.8.8.8"),
            Target(name="cloudflare", address="1.1.1.1"),
        ]

    gateway_ip = os.environ.get("GATEWAY_IP", "").strip() or _detect_default_gateway()
    if gateway_ip:
        targets.append(Target(name="gateway", address=gateway_ip, is_external=False))
    else:
        log.warning(
            "no gateway IP detected and GATEWAY_IP unset; gateway probing disabled "
            "— outage classification will be limited"
        )

    return Settings(
        data_dir=data_dir,
        db_path=data_dir / "probes.db",
        archive_dir=archive_dir,
        probe_interval_sec=int(os.environ.get("PROBE_INTERVAL_SEC", "30")),
        probe_timeout_sec=float(os.environ.get("PROBE_TIMEOUT_SEC", "2")),
        retention_days=int(os.environ.get("RETENTION_DAYS", "7")),
        targets=targets,
    )
