#!/usr/bin/env python3
"""Konzisztens SQLite-mentés és személyes adat nélküli migrációs ellenőrzés."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import tempfile
from pathlib import Path


CORE_TABLES = ("users", "work_entries", "leave_allowances")


def connect_readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=30)


def check(connection: sqlite3.Connection) -> None:
    result = connection.execute("PRAGMA quick_check").fetchone()
    if not result or result[0] != "ok":
        raise RuntimeError(f"SQLite quick_check hiba: {result!r}")


def summary(path: Path) -> dict[str, int]:
    if not path.is_file():
        raise FileNotFoundError(path)
    connection = connect_readonly(path)
    try:
        check(connection)
        existing = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        return {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in CORE_TABLES
            if table in existing
        }
    finally:
        connection.close()


def backup(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        source_db = connect_readonly(source)
        target_db = sqlite3.connect(temporary)
        try:
            source_db.backup(target_db)
            target_db.commit()
            check(target_db)
        finally:
            target_db.close()
            source_db.close()
        os.chmod(temporary, 0o600)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    check_parser = subparsers.add_parser("check")
    check_parser.add_argument("database", type=Path)
    backup_parser = subparsers.add_parser("backup")
    backup_parser.add_argument("source", type=Path)
    backup_parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    if args.command == "backup":
        backup(args.source, args.destination)
        print(args.destination)
    else:
        print(json.dumps(summary(args.database), sort_keys=True))


if __name__ == "__main__":
    main()
