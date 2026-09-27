import asyncio
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.receiver_discovery import (ReceiverDiscovery, SERVICE_TYPE, _service_info,
                                    lan_ipv4_addresses, listener_settings, receiver_id, usable_ipv4)


class DiscoveryProtocolTests(unittest.TestCase):
    def test_identity_is_exact_public_hash_and_missing_token_has_no_identity(self):
        secret = "fixture-pairing-key"
        self.assertEqual(receiver_id({"token": secret}), hashlib.sha256(secret.encode()).hexdigest()[:16])
        for config in ({}, {"token": ""}, {"token": None}):
            self.assertIsNone(receiver_id(config))

    def test_cli_listener_wins_and_default_loopback_is_not_assumed_lan(self):
        self.assertEqual(listener_settings([], {}), ("127.0.0.1", 8000))
        self.assertEqual(listener_settings(["--host", "0.0.0.0", "--port=8010"], {"UVICORN_PORT": "8001"}), ("0.0.0.0", 8010))
        self.assertEqual(listener_settings([], {"SKYCOMPANION_LIVE_BIND_HOST": "192.168.1.3", "SKYCOMPANION_LIVE_BIND_PORT": "8011"}), ("192.168.1.3", 8011))
        with self.assertRaises(ValueError):
            listener_settings(["--port", "0"], {})

    def test_lan_filter_excludes_loopback_ipv6_tunnel_and_link_local(self):
        adapters = [SimpleNamespace(name=name, ips=[SimpleNamespace(ip=ip)]) for name, ip in (
            ("lo0", "127.0.0.1"), ("en0", "192.168.1.165"), ("en1", "169.254.1.2"),
            ("en3", ("fe80::1", 0, 0)), ("utun4", "10.20.1.2"), ("awdl0", "10.5.0.1"),
            ("en4", "0.0.0.0"), ("en5", "224.0.0.251"), ("en6", "192.168.1.165"))]
        with patch("ifaddr.get_adapters", return_value=adapters):
            self.assertEqual(lan_ipv4_addresses(), ["192.168.1.165"])
        self.assertFalse(usable_ipv4("not-an-address"))

    def test_real_service_info_contains_public_protocol_not_pairing_secret(self):
        identity = receiver_id({"token": "fixture-secret"})
        info = _service_info(identity, ["192.168.1.165"], 8000)
        self.assertEqual(info.type, SERVICE_TYPE)
        self.assertEqual(info.properties, {b"receiver_id": identity.encode(), b"scheme": b"http", b"path": b"/"})
        self.assertEqual(info.parsed_addresses(), ["192.168.1.165"])
        self.assertEqual(info.port, 8000)
        self.assertNotIn("fixture-secret", str(info))

    def test_health_reports_same_identity_without_disclosing_configuration(self):
        from app import live
        secret = "fixture-health-key"
        with patch.object(live, "read_config", return_value={"token": secret, "server_url": "http://stale.local:8000"}):
            health = live.health()
        self.assertEqual(health["receiver_id"], receiver_id({"token": secret}))
        self.assertTrue(health["configured"])
        self.assertNotIn(secret, json.dumps(health))
        self.assertNotIn("server_url", health)


class FakeZeroconf:
    def __init__(self):
        self.registered = []
        self.closed = 0

    async def async_register_service(self, info, **kwargs):
        self.registered.append((info, kwargs))
        future = asyncio.get_running_loop().create_future()
        future.set_result(None)
        return future

    async def async_close(self):
        self.closed += 1


class DiscoveryLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.addresses = ["192.168.1.165"]
        self.host = "0.0.0.0"
        self.config = {"token": "fixture-secret"}
        self.instances = []

        def factory(addresses):
            instance = FakeZeroconf()
            self.instances.append(instance)
            return instance

        self.discovery = ReceiverDiscovery(
            address_provider=lambda: self.addresses,
            settings_provider=lambda: (self.host, 8000),
            zeroconf_factory=factory,
            service_factory=lambda identity, addresses, port: {"id": identity, "addresses": addresses, "port": port},
            interval=.01,
        )
        self.discovery._config_reader = lambda: self.config

    async def asyncTearDown(self):
        await self.discovery.stop()

    async def test_initial_publish_and_unchanged_refresh_do_not_repeat_registration(self):
        await self.discovery.refresh()
        await self.discovery.refresh()
        self.assertEqual(len(self.instances), 1)
        self.assertEqual(len(self.instances[0].registered), 1)
        self.assertEqual(self.discovery.snapshot()["state"], "advertised")
        self.assertNotIn("fixture-secret", json.dumps(self.discovery.snapshot()))
        copy = self.discovery.snapshot()
        copy["addresses"].clear()
        self.assertEqual(self.discovery.snapshot()["addresses"], ["192.168.1.165"])

    async def test_dhcp_change_withdraws_old_service_and_reopens_correct_interface(self):
        await self.discovery.refresh()
        self.addresses = ["192.168.1.170"]
        await self.discovery.refresh()
        self.assertEqual(len(self.instances), 2)
        self.assertEqual(self.instances[0].closed, 1)
        self.assertEqual(self.instances[1].registered[0][0]["addresses"], ("192.168.1.170",))
        self.assertEqual(self.discovery.snapshot()["addresses"], ["192.168.1.170"])

    async def test_network_loss_removes_old_addresses_and_returns_when_network_recovers(self):
        await self.discovery.refresh()
        self.addresses = []
        await self.discovery.refresh()
        self.assertEqual(self.instances[0].closed, 1)
        self.assertEqual(self.discovery.snapshot()["state"], "no_lan_address")
        self.assertEqual(self.discovery.snapshot()["addresses"], [])
        self.addresses = ["10.0.0.4"]
        await self.discovery.refresh()
        self.assertEqual(self.discovery.snapshot()["state"], "advertised")

    async def test_pairing_rotation_updates_public_identity(self):
        await self.discovery.refresh()
        old_id = self.discovery.snapshot()["receiver_id"]
        self.config = {"token": "changed-secret"}
        await self.discovery.refresh()
        self.assertEqual(self.instances[0].closed, 1)
        self.assertNotEqual(self.discovery.snapshot()["receiver_id"], old_id)
        self.assertEqual(self.discovery.snapshot()["receiver_id"], receiver_id(self.config))

    async def test_loopback_unconfigured_and_ipv6_do_not_publish_false_lan_endpoint(self):
        for host, config, expected in (("127.0.0.1", self.config, "loopback_only"),
                                       ("0.0.0.0", {}, "unconfigured"),
                                       ("::", self.config, "unsupported_bind")):
            self.host, self.config = host, config
            await self.discovery.refresh()
            self.assertEqual(self.discovery.snapshot()["state"], expected)
        self.assertEqual(self.instances, [])

    async def test_explicit_bind_only_publishes_that_interface(self):
        self.addresses = ["10.0.0.4", "192.168.1.165", "127.0.0.1"]
        self.host = "192.168.1.165"
        await self.discovery.refresh()
        self.assertEqual(self.discovery.snapshot()["addresses"], ["192.168.1.165"])

    async def test_failed_advertisement_is_sanitized_and_background_retries(self):
        original = self.discovery.zeroconf_factory
        attempts = 0

        def failing_then_recovering(addresses):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise OSError("Do not expose fixture-secret from this exception")
            return original(addresses)

        self.discovery.zeroconf_factory = failing_then_recovering
        with self.assertLogs("uvicorn.error", level="WARNING") as captured:
            await self.discovery.start(lambda: self.config)
            for _ in range(30):
                if self.discovery.snapshot()["state"] == "advertised":
                    break
                await asyncio.sleep(.005)
        self.assertEqual(self.discovery.snapshot()["state"], "advertised")
        self.assertNotIn("fixture-secret", " ".join(captured.output))
        await self.discovery.stop()
        self.assertEqual(self.instances[-1].closed, 1)
        self.assertEqual(self.discovery.snapshot()["state"], "stopped")

    async def test_application_lifespan_starts_and_stops_discovery_with_receiver(self):
        from app import main
        calls = []

        async def receiver_start():
            calls.append("receiver_start")

        async def discovery_start(reader):
            self.assertIs(reader, main.read_live_config)
            calls.append("discovery_start")

        async def receiver_stop():
            calls.append("receiver_stop")

        async def discovery_stop():
            calls.append("discovery_stop")

        with patch.object(main.live_hub, "start", receiver_start), patch.object(main.live_hub, "stop", receiver_stop), \
             patch.object(main.receiver_discovery, "start", discovery_start), patch.object(main.receiver_discovery, "stop", discovery_stop), \
             patch.object(main, "_log_google_credentials_status"):
            async with main.lifespan(main.app):
                self.assertEqual(calls, ["receiver_start", "discovery_start"])
        self.assertEqual(calls, ["receiver_start", "discovery_start", "discovery_stop", "receiver_stop"])


if __name__ == "__main__":
    unittest.main()
