# SPDX-License-Identifier: MPL-2.0
"""Publisher/SDK interoperability with ephemeral keys and synthetic payloads."""
import hashlib
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
import openzilo as sdk
from openzilo._firmware_bundle import DOMAIN
from test_ota import RingPeer, TARGET, OLD


class BundleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.public = self.key.public_key().public_bytes(serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo)
        self.payload = b"RINGENC1" + struct.pack("<II", 1, 100) + b"0" * 16 + b"x" * 100
        self.meta = dict(schema=1, algorithm="ECDSA-P256-SHA256", image="app",
            key_id=hashlib.sha256(self.key.public_key().public_bytes(serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest(),
            version=TARGET, model="Test Ring", board="synthetic/board", profile="production",
            security_version=1, source_versions=[OLD], payload=dict(file="app.ota.bin",
            format="RINGENC1", size=len(self.payload), sha256=hashlib.sha256(self.payload).hexdigest()))

    def bundle(self, *, payload=None, raw=None, signature=None, extra=False, duplicate=False):
        raw = raw if raw is not None else json.dumps(self.meta).encode()
        signature = signature if signature is not None else self.key.sign(DOMAIN + raw, ec.ECDSA(hashes.SHA256()))
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as z:
            z.writestr("manifest.json", raw)
            z.writestr("manifest.sig", signature)
            z.writestr("app.ota.bin", self.payload if payload is None else payload)
            if extra:
                z.writestr("../unexpected", b"x")
            if duplicate:
                z.writestr("manifest.json", raw)
        return stream.getvalue()

    def test_valid_and_tampered_packages(self):
        result = sdk.inspect_firmware_bundle(self.bundle(), trusted_public_key=self.public)
        self.assertEqual(result.payload, self.payload)
        self.assertEqual(result.source_versions, (OLD,))
        for data in (self.bundle(payload=self.payload[:-1] + b"!"), self.bundle(signature=b"x"),
                     self.bundle(extra=True), self.bundle(raw=b'{"schema":1,"schema":1}'), b"bad"):
            with self.subTest(size=len(data)), self.assertRaises(ValueError):
                sdk.inspect_firmware_bundle(data, trusted_public_key=self.public)
        foreign = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        with self.assertRaisesRegex(ValueError, "signature"):
            sdk.inspect_firmware_bundle(self.bundle(), trusted_public_key=foreign)

    def test_rejects_unsupported_schema_and_invalid_signed_header(self):
        self.meta["schema"] = 2
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            sdk.inspect_firmware_bundle(self.bundle(), trusted_public_key=self.public)
        self.meta["schema"] = 1
        self.payload = self.payload[:8] + struct.pack("<II", 1, 999) + self.payload[16:]
        self.meta["payload"]["sha256"] = hashlib.sha256(self.payload).hexdigest()
        with self.assertRaisesRegex(ValueError, "header"):
            sdk.inspect_firmware_bundle(self.bundle(), trusted_public_key=self.public)

    async def test_cli_rejects_untrusted_zip_before_connecting(self):
        from openzilo import _cli as cli
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bundle.zip"
            path.write_bytes(self.bundle())
            public = Path(directory) / "untrusted.pem"
            foreign_key = ec.generate_private_key(ec.SECP256R1()).public_key()
            public.write_bytes(foreign_key.public_bytes(serialization.Encoding.PEM,
                                                       serialization.PublicFormat.SubjectPublicKeyInfo))
            args = cli.build_parser().parse_args(["ota-update", str(path), "--public-key", str(public)])
            with patch.object(cli, "OpenZiloClient") as client:
                with self.assertRaisesRegex(ValueError, "signature"):
                    await args.func(args)
                client.assert_not_called()

    async def test_offline_inspection_displays_all_verified_fields_without_ble(self):
        from openzilo import _cli as cli
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "firmware.zip").write_bytes(self.bundle())
            (root / "public.pem").write_bytes(self.public)
            for json_output in (False, True):
                args = cli.build_parser().parse_args(["ota-inspect", str(root / "firmware.zip"),
                    "--public-key", str(root / "public.pem")] + (["--json"] if json_output else []))
                output = io.StringIO()
                with patch.object(cli, "OpenZiloClient") as client, redirect_stdout(output):
                    await args.func(args)
                    client.assert_not_called()
                if json_output:
                    self.assertEqual(json.loads(output.getvalue()),
                                     {"signature_verified": True, "manifest": self.meta})
                else:
                    self.assertIn("signature: verified", output.getvalue())
                    for name in self.meta:
                        self.assertIn(f"{name if name != 'payload' else 'payload.sha256'}:", output.getvalue())
            (root / "firmware.zip").write_bytes(self.bundle(signature=b"invalid"))
            output = io.StringIO()
            with redirect_stdout(output), self.assertRaisesRegex(ValueError, "signature"):
                await args.func(args)
            self.assertEqual(output.getvalue(), "")

    async def test_update_sends_only_payload_and_checks_device(self):
        peer = RingPeer(self.payload)
        client = sdk.OpenZiloClient(transport=peer)
        await client.connect()
        capabilities = sdk.DeviceCapabilities("device", OLD, "Test Ring", "synthetic/board")
        try:
            with patch("openzilo._compatibility.get_device_capabilities", return_value=capabilities):
                result = await sdk.update_firmware(client, self.bundle(), trusted_public_key=self.public,
                    timeout_s=.5, reboot_timeout_s=.5)
            self.assertEqual(result.firmware_version, TARGET)
            self.assertEqual(b"".join(data for _, data in peer.responses), self.payload)
        finally:
            await client.disconnect()

    async def test_exact_legacy_firmware_can_upgrade_without_new_discovery_command(self):
        legacy = "V2.001.0002.0001-prod-7fd1dfc9"
        self.meta.update(model="Open Zilo", board="ring_dvt2//nrf54l15/cpuapp", source_versions=[legacy])
        peer = RingPeer(self.payload)
        peer.model, peer.version = "Open Zilo", legacy
        original_write = peer.write

        async def legacy_write(data):
            if sdk.decode_packet(data).command == 0x0105:
                peer.emit(0x01FF, struct.pack(">HH", 0x0105, 5))
            else:
                await original_write(data)

        peer.write = legacy_write
        client = sdk.OpenZiloClient(transport=peer)
        await client.connect()
        try:
            result = await sdk.update_firmware(client, self.bundle(), trusted_public_key=self.public,
                                               timeout_s=.5, reboot_timeout_s=.5)
            self.assertEqual(result.firmware_version, TARGET)
            self.assertEqual(b"".join(data for _, data in peer.responses), self.payload)
        finally:
            await client.disconnect()

    async def test_rejections_never_start_ota(self):
        for mutation in ({"model": "Other"}, {"board": "other"}, {"source_versions": [TARGET]},
                         {"profile": "test"}):
            with self.subTest(mutation=mutation):
                previous = self.meta.copy()
                self.meta.update(mutation)
                peer = RingPeer(self.payload)
                client = sdk.OpenZiloClient(transport=peer)
                await client.connect()
                try:
                    with patch("openzilo._compatibility.get_device_capabilities", return_value=
                               sdk.DeviceCapabilities("device", OLD, "Test Ring", "synthetic/board")):
                        with self.assertRaises((ValueError, sdk.ProtocolError)):
                            await sdk.update_firmware(client, self.bundle(), trusted_public_key=self.public)
                    self.assertNotIn(1005, peer.commands)
                finally:
                    self.meta = previous
                    await client.disconnect()

    def test_real_publisher_interoperability(self):
        publisher_path = Path(__file__).resolve().parents[2] / "ring_sound/tools/firmware_bundle.py"
        if not publisher_path.exists():
            self.skipTest("Sibling firmware checkout unavailable")
        spec = importlib.util.spec_from_file_location("ring_bundle_publisher", publisher_path)
        publisher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(publisher)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ota.bin").write_bytes(self.payload)
            (root / "key.pem").write_bytes(self.key.private_bytes(serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            (root / "meta.json").write_text(json.dumps({k: self.meta[k] for k in
                ("version", "model", "board", "profile", "security_version", "source_versions")}))
            self.assertEqual(publisher.bundle_output_path(root / "ota.bin", root / "meta.json").name,
                             f"ring_sound-{TARGET}.ota.zip")
            publisher.bundle_release(SimpleNamespace(ota_input=root / "ota.bin", metadata=root / "meta.json",
                signing_key=root / "key.pem", output=root / "out.zip"))
            result = sdk.inspect_firmware_bundle((root / "out.zip").read_bytes(), trusted_public_key=self.public)
            self.assertEqual(result.payload, self.payload)
            self.assertEqual(set(zipfile.ZipFile(root / "out.zip").namelist()),
                             {"manifest.json", "manifest.sig", "app.ota.bin"})
