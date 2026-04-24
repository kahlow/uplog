from __future__ import annotations

import asyncio
import logging
import socket
import time
from dataclasses import dataclass

from icmplib import SocketPermissionError, async_ping

from .config import Target

log = logging.getLogger(__name__)

# Track which targets have already failed-over to TCP so we don't retry ICMP
# every cycle and spam logs. Cleared on process restart.
_tcp_only: set[str] = set()


@dataclass
class ProbeResult:
    target: str
    address: str
    ok: bool
    latency_ms: float | None
    method: str  # 'icmp' | 'tcp'
    error: str | None


async def _icmp(address: str, timeout: float) -> tuple[bool, float | None, str | None]:
    try:
        host = await async_ping(address, count=1, timeout=timeout, privileged=True)
        if host.is_alive:
            return True, host.avg_rtt, None
        return False, None, "no reply"
    except SocketPermissionError as e:
        # Caller will fall back to TCP and remember to skip ICMP next time.
        raise
    except Exception as e:
        return False, None, type(e).__name__ + ": " + str(e)[:80]


async def _tcp(address: str, port: int, timeout: float) -> tuple[bool, float | None, str | None]:
    loop = asyncio.get_running_loop()
    start = time.monotonic()
    try:
        await asyncio.wait_for(
            loop.create_connection(lambda: asyncio.Protocol(), host=address, port=port),
            timeout=timeout,
        )
        # We don't care about the connection itself — it'll be GC'd; we measured connect time.
        latency = (time.monotonic() - start) * 1000
        return True, latency, None
    except asyncio.TimeoutError:
        return False, None, "timeout"
    except OSError as e:
        return False, None, type(e).__name__ + ": " + str(e)[:80]


async def probe_one(t: Target, timeout: float) -> ProbeResult:
    if t.address not in _tcp_only:
        try:
            ok, latency, err = await _icmp(t.address, timeout)
            return ProbeResult(t.name, t.address, ok, latency, "icmp", err)
        except SocketPermissionError:
            log.warning(
                "ICMP requires CAP_NET_RAW; falling back to TCP for %s (%s) — "
                "set cap_add: NET_RAW in docker-compose for real pings",
                t.name,
                t.address,
            )
            _tcp_only.add(t.address)

    ok, latency, err = await _tcp(t.address, t.tcp_port, timeout)
    return ProbeResult(t.name, t.address, ok, latency, "tcp", err)


async def probe_all(targets: list[Target], timeout: float) -> list[ProbeResult]:
    return await asyncio.gather(*(probe_one(t, timeout) for t in targets))
