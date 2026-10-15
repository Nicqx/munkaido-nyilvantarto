from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import timedelta

from .core import utc_now


CHALLENGE_TTL = timedelta(minutes=5)


def create_challenge(
    db: sqlite3.Connection, *, purpose: str, user_id: int | None
) -> tuple[str, bytes]:
    now = utc_now()
    ceremony_id = secrets.token_urlsafe(24)
    challenge = secrets.token_bytes(32)
    db.execute("DELETE FROM webauthn_challenges WHERE expires_at <= ?", (now.isoformat(),))
    db.execute(
        """
        INSERT INTO webauthn_challenges(
            id, user_id, purpose, challenge, expires_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            ceremony_id,
            user_id,
            purpose,
            challenge,
            (now + CHALLENGE_TTL).isoformat(),
            now.isoformat(),
        ),
    )
    db.commit()
    return ceremony_id, challenge


def consume_challenge(
    db: sqlite3.Connection, *, ceremony_id: str, purpose: str
) -> sqlite3.Row | None:
    row = db.execute(
        """
        DELETE FROM webauthn_challenges
        WHERE id = ? AND purpose = ? AND expires_at > ?
        RETURNING *
        """,
        (ceremony_id, purpose, utc_now().isoformat()),
    ).fetchone()
    if row is None:
        db.execute("DELETE FROM webauthn_challenges WHERE id = ?", (ceremony_id,))
    db.commit()
    return row


def list_passkeys(db: sqlite3.Connection, user_id: int):
    return db.execute(
        """
        SELECT id, name, device_type, backed_up, created_at, last_used_at
        FROM passkeys WHERE user_id = ? ORDER BY created_at DESC
        """,
        (user_id,),
    ).fetchall()


def add_passkey(
    db: sqlite3.Connection,
    *,
    user_id: int,
    name: str,
    credential_id: bytes,
    public_key: bytes,
    sign_count: int,
    transports: list[str],
    device_type: str,
    backed_up: bool,
) -> None:
    db.execute(
        """
        INSERT INTO passkeys(
            user_id, name, credential_id, public_key, sign_count,
            transports_json, device_type, backed_up, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            name,
            credential_id,
            public_key,
            sign_count,
            json.dumps(transports),
            device_type,
            int(backed_up),
            utc_now().isoformat(),
        ),
    )
    db.commit()
