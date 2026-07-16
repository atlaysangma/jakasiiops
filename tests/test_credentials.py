from __future__ import annotations

import unittest

from jakasii_ops.credentials import (
    WindowsCredentialVault,
    configure_manifest_credentials,
    hydrate_manifest_environment,
    manifest_secret_names,
)


class _Vault:
    def __init__(self) -> None:
        self.values = {}

    def write(self, store_id, name, secret):
        self.values[(store_id, name)] = secret

    def read(self, store_id, name):
        return self.values.get((store_id, name))


class CredentialTests(unittest.TestCase):
    def test_interactive_setup_and_hydration_return_names_not_values(self) -> None:
        manifest = {
            "required_environment": ["CAMERA_ACCESS_SECRET"],
        }
        vault = _Vault()
        setup = configure_manifest_credentials(
            "shop_1",
            manifest,
            vault=vault,
            prompt=lambda _message: "private-value-never-returned",
        )
        environment = {}
        hydration = hydrate_manifest_environment(
            "shop_1", manifest, vault=vault, environment=environment
        )

        self.assertEqual(["CAMERA_ACCESS_SECRET"], setup["stored_names"])
        self.assertEqual(
            ["CAMERA_ACCESS_SECRET"], hydration["available_names"]
        )
        self.assertEqual("private-value-never-returned", environment["CAMERA_ACCESS_SECRET"])
        self.assertNotIn("private-value-never-returned", str(setup))
        self.assertNotIn("private-value-never-returned", str(hydration))
        self.assertFalse(setup["secret_values_returned"])
        self.assertFalse(hydration["secret_values_returned"])

    def test_missing_credential_stays_missing(self) -> None:
        result = hydrate_manifest_environment(
            "shop_1",
            {"required_environment": ["CAMERA_ACCESS_SECRET"]},
            vault=_Vault(),
            environment={},
        )
        self.assertEqual(["CAMERA_ACCESS_SECRET"], result["missing_names"])
        self.assertEqual([], result["available_names"])

    def test_invalid_manifest_credential_name_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            manifest_secret_names({"required_environment": ["--password"]})

    def test_credential_target_contains_only_sanitized_identifiers(self) -> None:
        vault = WindowsCredentialVault()
        target = vault._target("Shop One/../../", "CAMERA_ACCESS_SECRET")
        prefix, store, name = target.split("/")
        self.assertEqual("JAKASII_OPS", prefix)
        self.assertEqual("CAMERA_ACCESS_SECRET", name)
        self.assertNotIn(" ", store)
        self.assertNotIn("\\", store)


if __name__ == "__main__":
    unittest.main()
