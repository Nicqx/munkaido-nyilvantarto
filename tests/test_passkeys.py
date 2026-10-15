import unittest

from worktime.passkeys import (
    authentication_options_json,
    credential_id_from_json,
    registration_options_json,
    user_handle,
    validate_webauthn_config,
)


class PasskeyOptionsTests(unittest.TestCase):
    ORIGIN = "https://pmqxyz.hopto.org"
    RP_ID = "pmqxyz.hopto.org"

    def test_authentication_is_username_free(self):
        options = authentication_options_json(
            origin=self.ORIGIN,
            rp_id=self.RP_ID,
            challenge=b"a" * 32,
        )
        self.assertEqual(options["rpId"], self.RP_ID)
        self.assertEqual(options["allowCredentials"], [])
        self.assertEqual(options["userVerification"], "required")

    def test_registration_requires_a_resident_verified_credential(self):
        options = registration_options_json(
            origin=self.ORIGIN,
            rp_id=self.RP_ID,
            user={"id": 7, "login": "user@example.test", "display_name": "User"},
            challenge=b"b" * 32,
            existing_credential_ids=[],
        )
        selection = options["authenticatorSelection"]
        self.assertEqual(selection["residentKey"], "required")
        self.assertTrue(selection["requireResidentKey"])
        self.assertEqual(selection["userVerification"], "required")
        self.assertEqual(len(user_handle(7)), 32)

    def test_origin_must_match_rp_id(self):
        with self.assertRaises(ValueError):
            validate_webauthn_config("https://example.org", self.RP_ID)
        with self.assertRaises(ValueError):
            validate_webauthn_config("http://pmqxyz.hopto.org", self.RP_ID)

    def test_malformed_credential_id_is_rejected(self):
        for value in ("", "!!!", "a", "é"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                credential_id_from_json({"id": value})


if __name__ == "__main__":
    unittest.main()
