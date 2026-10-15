from __future__ import annotations

import hashlib
import json
from binascii import Error as Base64Error
from typing import Any
from urllib.parse import urlparse

from webauthn import (
    base64url_to_bytes,
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)


def validate_webauthn_config(origin: str, rp_id: str) -> None:
    parsed = urlparse(origin)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("A WEBAUTHN_ORIGIN nem érvényes webcím.")
    if parsed.scheme != "https" and parsed.hostname != "localhost":
        raise ValueError("A WebAuthn csak HTTPS-en vagy localhoston használható.")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("A WEBAUTHN_ORIGIN csak sémát és gépnevet tartalmazhat.")
    if not (
        parsed.hostname == rp_id or parsed.hostname.endswith(f".{rp_id}")
    ):
        raise ValueError("A WEBAUTHN_RP_ID nem tartozik a beállított originhez.")


def user_handle(user_id: int) -> bytes:
    """Stable, non-identifying WebAuthn user handle."""
    return hashlib.sha256(f"munkaido:user:{int(user_id)}".encode("utf-8")).digest()


def registration_options_json(
    *,
    origin: str,
    rp_id: str,
    user: dict,
    challenge: bytes,
    existing_credential_ids: list[bytes],
) -> dict[str, Any]:
    validate_webauthn_config(origin, rp_id)
    options = generate_registration_options(
        rp_id=rp_id,
        rp_name="Munkaidő-nyilvántartó",
        user_id=user_handle(int(user["id"])),
        user_name=str(user["login"]),
        user_display_name=str(user["display_name"]),
        challenge=bytes(challenge),
        timeout=60_000,
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=credential_id)
            for credential_id in existing_credential_ids
        ],
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    return json.loads(options_to_json(options))


def authentication_options_json(
    *, origin: str, rp_id: str, challenge: bytes
) -> dict[str, Any]:
    """Create a discoverable-credential request with no username or allow-list."""
    validate_webauthn_config(origin, rp_id)
    options = generate_authentication_options(
        rp_id=rp_id,
        challenge=bytes(challenge),
        timeout=60_000,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    return json.loads(options_to_json(options))


def credential_id_from_json(credential: dict[str, Any]) -> bytes:
    value = credential.get("id")
    if not isinstance(value, str) or not value:
        raise ValueError("A passkey azonosítója hiányzik.")
    try:
        credential_id = base64url_to_bytes(value)
    except (Base64Error, ValueError) as exc:
        raise ValueError("A passkey azonosítója érvénytelen.") from exc
    if not credential_id:
        raise ValueError("A passkey azonosítója érvénytelen.")
    return credential_id


def verify_registration(
    *, origin: str, rp_id: str, credential: dict[str, Any], challenge: bytes
):
    return verify_registration_response(
        credential=credential,
        expected_challenge=bytes(challenge),
        expected_rp_id=rp_id,
        expected_origin=origin,
        require_user_verification=True,
    )


def verify_authentication(
    *,
    origin: str,
    rp_id: str,
    credential: dict[str, Any],
    challenge: bytes,
    public_key: bytes,
    sign_count: int,
):
    return verify_authentication_response(
        credential=credential,
        expected_challenge=bytes(challenge),
        expected_rp_id=rp_id,
        expected_origin=origin,
        credential_public_key=bytes(public_key),
        credential_current_sign_count=int(sign_count),
        require_user_verification=True,
    )


def enum_value(value: object) -> str:
    return str(getattr(value, "value", value))
