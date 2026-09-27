"""Public Bonjour identity and best-effort LAN discovery; pairing remains authenticated.

Only a one-way public receiver ID is advertised. This module never logs the pairing
token or exception messages, and discovery failure must not stop the HTTP receiver.
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import ipaddress
import logging
import os
import socket
import sys
import time

SERVICE_TYPE = "_skycompanion-live._tcp.local."
REFRESH_SECONDS = 15.0
_log = logging.getLogger("uvicorn.error")


def receiver_id(config):
    token = config.get("token")
    if not isinstance(token, str) or not token:
        return None
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def listener_settings(argv=None, environ=None):
    """Use the actual uvicorn CLI host/port; default loopback must not be advertised.

    Programmatic hosts can supply SKYCOMPANION_LIVE_BIND_HOST / SKYCOMPANION_LIVE_BIND_PORT. These
    are listener configuration, never inferred from an old phone server_url.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    env = os.environ if environ is None else environ
    host = env.get("SKYCOMPANION_LIVE_BIND_HOST", env.get("UVICORN_HOST", "127.0.0.1"))
    port = env.get("SKYCOMPANION_LIVE_BIND_PORT", env.get("UVICORN_PORT", "8000"))
    for index, argument in enumerate(argv):
        if argument in ("--host", "--port") and index + 1 < len(argv):
            if argument == "--host":
                host = argv[index + 1]
            else:
                port = argv[index + 1]
        elif argument.startswith("--host="):
            host = argument.partition("=")[2]
        elif argument.startswith("--port="):
            port = argument.partition("=")[2]
    port = int(port)
    if not 1 <= port <= 65535:
        raise ValueError("invalid_listener_port")
    return str(host), port


def usable_ipv4(value):
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return (address.version == 4 and not address.is_loopback and not address.is_unspecified
            and not address.is_multicast and not address.is_link_local and not address.is_reserved)


def lan_ipv4_addresses():
    # ifaddr is also a zeroconf dependency; imports remain optional until discovery.
    import ifaddr
    addresses = set()
    for adapter in ifaddr.get_adapters():
        name = adapter.name.lower()
        if name.startswith(("lo", "utun", "tun", "tap", "awdl", "llw", "gif", "stf", "veth", "docker", "vmnet")):
            continue
        for entry in adapter.ips:
            if isinstance(entry.ip, str) and usable_ipv4(entry.ip):
                addresses.add(entry.ip)
    return sorted(addresses, key=lambda address: tuple(int(part) for part in address.split(".")))


def _zeroconf_factory(addresses):
    from zeroconf import IPVersion
    from zeroconf.asyncio import AsyncZeroconf
    return AsyncZeroconf(interfaces=list(addresses), ip_version=IPVersion.V4Only)


def _service_info(identity, addresses, port):
    from zeroconf import ServiceInfo
    return ServiceInfo(
        SERVICE_TYPE, f"SkyCompanion-{identity}.{SERVICE_TYPE}",
        addresses=[socket.inet_aton(address) for address in addresses], port=port,
        properties={"receiver_id": identity, "scheme": "http", "path": "/"},
        server=f"skycompanion-{identity}.local.", host_ttl=30, other_ttl=30,
    )


class ReceiverDiscovery:
    def __init__(self, *, address_provider=lan_ipv4_addresses, settings_provider=listener_settings,
                 zeroconf_factory=_zeroconf_factory, service_factory=_service_info,
                 interval=REFRESH_SECONDS):
        self.address_provider = address_provider
        self.settings_provider = settings_provider
        self.zeroconf_factory = zeroconf_factory
        self.service_factory = service_factory
        self.interval = interval
        self._task = None
        self._config_reader = None
        self._zeroconf = None
        self._published_key = None
        self._status = {"state": "not_started", "service_type": SERVICE_TYPE, "addresses": [],
                        "port": None, "receiver_id": None, "last_error": None,
                        "refresh_interval_s": interval}

    def snapshot(self):
        return {**self._status, "addresses": list(self._status["addresses"])}

    def _set_status(self, state, *, identity=None, addresses=(), port=None, error=None):
        prior = self._status["state"]
        self._status = {"state": state, "service_type": SERVICE_TYPE, "receiver_id": identity,
                        "service_name": f"SkyCompanion-{identity}.{SERVICE_TYPE}" if identity else None,
                        "addresses": list(addresses), "port": port, "last_error": error,
                        "refresh_interval_s": self.interval, "checked_at_unix_s": time.time()}
        if state != prior and state in ("unavailable", "dependency_unavailable"):
            # Exception arguments can contain config contents. Log only a class name.
            _log.warning("SkyCompanion Bonjour discovery is unavailable (%s); HTTP receiver continues.", error)

    async def start(self, config_reader):
        if self._task and not self._task.done():
            return
        self._config_reader = config_reader
        # Network work stays in a background task; startup does not depend on mDNS.
        self._task = asyncio.create_task(self._run(), name="skycompanion-receiver-discovery")

    async def stop(self):
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        await self._disconnect()
        self._set_status("stopped")

    async def _disconnect(self):
        current, self._zeroconf = self._zeroconf, None
        self._published_key = None
        if current:
            try:
                # async_close withdraws services and closes sockets, including goodbyes.
                await asyncio.wait_for(current.async_close(), timeout=4)
            except Exception:
                pass

    async def refresh(self):
        """One check, also used by focused tests without opening real network sockets."""
        identity = receiver_id(self._config_reader() if self._config_reader else {})
        host, port = self.settings_provider()
        if not identity:
            await self._disconnect()
            self._set_status("unconfigured", port=port)
            return
        if host in ("127.0.0.1", "localhost", "::1"):
            await self._disconnect()
            self._set_status("loopback_only", identity=identity, port=port)
            return
        # This first transport advertises IPv4. Do not claim IPv4 reachability for
        # an IPv6-only or hostname-bound listener whose actual socket is unknown.
        if host != "0.0.0.0" and not usable_ipv4(host):
            await self._disconnect()
            self._set_status("unsupported_bind", identity=identity, port=port)
            return
        addresses = tuple(address for address in self.address_provider() if usable_ipv4(address))
        if host != "0.0.0.0":
            addresses = tuple(address for address in addresses if address == host)
        addresses = tuple(sorted(set(addresses)))
        if not addresses:
            await self._disconnect()
            self._set_status("no_lan_address", identity=identity, port=port)
            return
        key = (identity, addresses, port)
        if key != self._published_key:
            # A DHCP change also changes multicast interface sockets, so rebuild
            # the announcer instead of updating A records on a dead old socket.
            await self._disconnect()
            info = self.service_factory(identity, addresses, port)
            self._zeroconf = self.zeroconf_factory(addresses)
            announcements = await asyncio.wait_for(
                self._zeroconf.async_register_service(info, ttl=30, allow_name_change=False), timeout=4)
            # zeroconf 0.151 returns another awaitable for completion of broadcasts.
            if inspect.isawaitable(announcements):
                await asyncio.wait_for(announcements, timeout=4)
            self._published_key = key
        self._set_status("advertised", identity=identity, addresses=addresses, port=port)

    async def _run(self):
        try:
            while True:
                try:
                    await self.refresh()
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    await self._disconnect()
                    self._set_status("dependency_unavailable" if isinstance(error, ImportError) else "unavailable",
                                     error=type(error).__name__)
                await asyncio.sleep(self.interval)
        finally:
            await self._disconnect()


receiver_discovery = ReceiverDiscovery()
