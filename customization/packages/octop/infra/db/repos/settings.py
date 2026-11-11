"""Settings KV store — lightweight key/value pairs backed by SQLite."""

from __future__ import annotations

from octop.infra.db.pool import DatabasePool


class SettingsRepo:
    _KEY_ACTIVE_MODEL = "active_model"

    def __init__(self, db: DatabasePool):
        self._db = db

    def get(self, key: str) -> str | None:
        with self._db.connect() as conn:
            r = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return r["value"] if r else None

    def set(self, key: str, value: str) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def delete(self, key: str) -> None:
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM settings WHERE key = ?", (key,))

    def set_if_missing(self, key: str, value: str) -> str:
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO NOTHING",
                (key, value),
            )
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return str(row["value"])

    def compare_and_set(self, key: str, expected_value: str | None, value: str) -> bool:
        """Atomically insert an absent key or replace exactly the expected value."""
        with self._db.transaction() as conn:
            if expected_value is None:
                row = conn.execute(
                    "INSERT INTO settings(key, value) VALUES (?, ?)"
                    " ON CONFLICT(key) DO NOTHING RETURNING key",
                    (key, value),
                ).fetchone()
            else:
                row = conn.execute(
                    "UPDATE settings SET value = ? WHERE key = ? AND value = ? RETURNING key",
                    (value, key, expected_value),
                ).fetchone()
        return row is not None

    def get_active_model(self) -> tuple[str, str]:
        """Return (provider_name, model_id); empty strings if not set."""
        raw = self.get(self._KEY_ACTIVE_MODEL) or ""
        name, _, model = raw.partition("/")
        return name, model

    def set_active_model(self, provider_name: str, model_id: str) -> None:
        self.set(self._KEY_ACTIVE_MODEL, f"{provider_name}/{model_id}")
