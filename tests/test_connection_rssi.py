# SPDX-License-Identifier: MPL-2.0
import asyncio
import contextlib
import io
import unittest
from unittest import mock

import openzilo as sdk
from openzilo import _cli as cli
from test_compatibility import LEGACY, Peer, VECTOR, tlv


class RssiPeer(Peer):
    version = "V2.001.0002.0002-prod-f371c957"
    feature = b"\1\0"
    response = b"\0\0\xbf"

    async def write(self, raw):
        packet = sdk.decode_packet(raw)
        if packet.command == 0x0105:
            self.writes.append(packet)
            body = VECTOR.replace(b"V2.001.0002.0001", self.version.encode())
            # The firmware version TLV has a variable-length value.
            body = body[:5] + len(self.version).to_bytes(2, "big") + body[7:]
            if self.feature is not None:
                body += tlv(0x010C, self.feature)
            self.rx(sdk.encode_packet(0x0106, body))
        elif packet.command == 0x0107:
            self.writes.append(packet)
            if self.response is not None:
                self.rx(sdk.encode_packet(0x0108, self.response))
        else:
            await super().write(raw)


class ConnectionRssiTests(unittest.IsolatedAsyncioTestCase):
    async def connect(self, peer):
        client = sdk.OpenZiloClient(transport=peer, command_timeout_s=0.05)
        await client.connect()
        self.addAsyncCleanup(client.disconnect)
        return client

    async def test_release_capability_and_signed_rssi_wire(self):
        peer = RssiPeer()
        client = await self.connect(peer)
        self.assertEqual(await sdk.get_connection_rssi(client), -65)
        self.assertTrue(client.capabilities.supports("connection_rssi"))
        self.assertEqual(client.capabilities.firmware_version, peer.version)
        self.assertEqual((peer.writes[-1].command, peer.writes[-1].body), (0x0107, b""))
        peer.response = b"\0\0\0"
        self.assertEqual(await sdk.get_connection_rssi(client), 0)
        self.assertEqual([p.command for p in peer.writes].count(0x0105), 1)

    async def test_missing_or_incompatible_contract_rejected_before_query(self):
        for feature in (None, b"\2\0"):
            peer = RssiPeer()
            peer.feature = feature
            client = await self.connect(peer)
            with self.assertRaises(sdk.CompatibilityError):
                await sdk.get_connection_rssi(client)
            self.assertNotIn(0x0107, [p.command for p in peer.writes])

    async def test_legacy_profile_does_not_claim_rssi(self):
        peer = Peer()
        peer.version, peer.mode = LEGACY, "unsupported"
        client = await self.connect(peer)
        with self.assertRaises(sdk.CompatibilityError):
            await sdk.get_connection_rssi(client)
        self.assertEqual(client.capabilities.source, "legacy_profile")
        self.assertFalse(client.capabilities.supports("connection_rssi"))
        self.assertNotIn(0x0107, [p.command for p in peer.writes])

    async def test_device_error_and_unavailable_value(self):
        peer = RssiPeer()
        client = await self.connect(peer)
        peer.response = b"\0\1"
        with self.assertRaises(sdk.DeviceError) as error:
            await sdk.get_connection_rssi(client)
        self.assertEqual(error.exception.error_code, 1)
        peer.response = b"\0\0\x7f"
        with self.assertRaises(sdk.ProtocolError):
            await sdk.get_connection_rssi(client)
        with self.assertRaises(sdk.TransportError):
            await sdk.get_connection_rssi(client)

    async def test_timeout_requires_reconnect_before_retry(self):
        peer = RssiPeer()
        client = await self.connect(peer)
        peer.response = None
        with self.assertRaises(sdk.TimeoutError):
            await sdk.get_connection_rssi(client, timeout_s=0.02)
        peer.rx(sdk.encode_packet(0x0108, b"\0\0\xbf"))
        with self.assertRaises(sdk.TransportError):
            await sdk.get_connection_rssi(client)
        await client.disconnect()
        await client.connect()
        peer.response = b"\0\0\xc4"
        self.assertEqual(await sdk.get_connection_rssi(client), -60)

    async def test_signed_boundaries_and_malformed_responses(self):
        peer = RssiPeer()
        client = await self.connect(peer)
        for value in (-127, -65, 0, 20):
            peer.response = b"\0\0" + value.to_bytes(1, "big", signed=True)
            self.assertEqual(await sdk.get_connection_rssi(client), value)
        for body in (b"", b"\0", b"\0\0", b"\0\0\0\0", b"\0\1\0",
                     b"\0\0\x80", b"\0\0\x15"):
            await client.disconnect()
            await client.connect()
            peer.response = body
            with self.subTest(body=body), self.assertRaises(sdk.ProtocolError):
                await sdk.get_connection_rssi(client)

    async def test_cancelled_query_requires_reconnect(self):
        peer = RssiPeer()
        client = await self.connect(peer)
        await sdk.get_device_capabilities(client)
        peer.response = None
        query = asyncio.create_task(sdk.get_connection_rssi(client))
        while not any(p.command == 0x0107 for p in peer.writes):
            await asyncio.sleep(0)
        query.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await query
        peer.response = b"\0\0\xbf"
        with self.assertRaises(sdk.TransportError):
            await sdk.get_connection_rssi(client)

    async def test_concurrent_queries_remain_separate(self):
        peer = RssiPeer()
        client = await self.connect(peer)
        self.assertEqual(await asyncio.gather(
            sdk.get_connection_rssi(client), sdk.get_connection_rssi(client)), [-65, -65])
        self.assertEqual([p.command for p in peer.writes].count(0x0107), 2)

    async def test_invalid_timeout_does_not_send(self):
        peer = RssiPeer()
        client = await self.connect(peer)
        for timeout in (0, -1, float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                await sdk.get_connection_rssi(client, timeout_s=timeout)
        self.assertFalse(peer.writes)

    async def test_cli_rssi_output_and_options(self):
        client = mock.MagicMock()
        client.__aenter__ = mock.AsyncMock(return_value=client)
        client.__aexit__ = mock.AsyncMock(return_value=False)
        output = io.StringIO()
        with mock.patch.object(cli, "OpenZiloClient", return_value=client), \
                mock.patch.object(cli, "get_connection_rssi", mock.AsyncMock(return_value=-65)) as read, \
                contextlib.redirect_stdout(output):
            args = cli.build_parser().parse_args(["rssi", "--address", "synthetic", "--timeout", "2"])
            await args.func(args)
        read.assert_awaited_once_with(client, timeout_s=2)
        self.assertEqual(output.getvalue(), "-65 dBm\n")
