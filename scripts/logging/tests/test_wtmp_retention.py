import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

import test_retention as fixture


class OsLoginRetentionTests(unittest.TestCase):
    def test_only_closed_expired_login_pairs_are_removed(self):
        m = fixture.RetentionTests().module()
        now = datetime(2026, 11, 18, tzinfo=UTC)
        cutoff = int((now - timedelta(days=90)).timestamp() * 1_000_000)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "wtmp.db"
            with sqlite3.connect(path) as c:
                c.execute(
                    "CREATE TABLE wtmp(ID INTEGER PRIMARY KEY,Type INTEGER,User TEXT NOT NULL,Login INTEGER,Logout INTEGER,TTY TEXT,RemoteHost TEXT,Service TEXT) STRICT"
                )
                for index, login, logout in (
                    (1, cutoff - 1, cutoff),
                    (2, cutoff - 1, cutoff + 1),
                    (3, cutoff - 1, None),
                    (4, cutoff - 1, 0),
                    (5, cutoff + 1, cutoff + 2),
                ):
                    c.execute(
                        "INSERT INTO wtmp(ID,Type,User,Login,Logout) VALUES(?,3,'synthetic',?,?)",
                        (index, login, logout),
                    )
            path.chmod(0o600)
            self.assertEqual(m.prune_wtmp(path, now)["expired_closed_records"], 1)
            with sqlite3.connect(path) as c:
                self.assertEqual(
                    c.execute("SELECT count(*) FROM wtmp").fetchone()[0], 5
                )
            self.assertEqual(m.prune_wtmp(path, now, True)["expired_closed_records"], 1)
            with sqlite3.connect(path) as c:
                self.assertEqual(
                    [v[0] for v in c.execute("SELECT ID FROM wtmp ORDER BY ID")],
                    [2, 3, 4, 5],
                )
            self.assertEqual(m.prune_wtmp(path, now, True)["expired_closed_records"], 0)

    def test_wrong_schema_and_symlink_are_rejected(self):
        m = fixture.RetentionTests().module()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "wtmp.db"
            with sqlite3.connect(path) as c:
                c.execute("CREATE TABLE unrelated(value TEXT)")
            path.chmod(0o600)
            with self.assertRaises(ValueError):
                m.prune_wtmp(path, datetime.now(UTC), True)
            link = Path(folder) / "linked.db"
            link.symlink_to(path)
            with self.assertRaises(PermissionError):
                m.prune_wtmp(link, datetime.now(UTC), True)
