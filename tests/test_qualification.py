"""Tests for the rule that decides whether a volunteer may serve in a role.

``is_qualified`` is what the scheduling board and the auto-scheduler rely on to
keep untrained people out of live services, so it's worth locking down. These
use stdlib ``unittest`` against a throwaway SQLite database — no extra
dependencies, run with::

    python -m unittest discover tests
"""

import os
import sys
import tempfile
import unittest

# Point the DB layer at a throwaway SQLite file and force the SQLite backend
# *before* importing db (it reads these at import time).
_TMP = tempfile.mkdtemp()
os.environ["DATABASE_PATH"] = os.path.join(_TMP, "test.db")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db  # noqa: E402
from helpers import is_qualified, role_training_status  # noqa: E402


class QualificationTests(unittest.TestCase):
    def setUp(self):
        db.init_db()
        self.conn = db.get_db()
        self.uid = db.execute_returning_id(
            self.conn,
            "INSERT INTO users (name, email, password_hash, created_at)"
            " VALUES (?, ?, ?, ?)",
            ("Tester", f"t{os.urandom(4).hex()}@x.test", "x", db.now_iso()),
        )
        self.rid = db.execute_returning_id(
            self.conn, "INSERT INTO roles (name) VALUES (?)",
            (f"Role {os.urandom(4).hex()}",),
        )

    def tearDown(self):
        self.conn.close()

    def _add_training(self, required):
        return db.execute_returning_id(
            self.conn,
            "INSERT INTO trainings (title, role_id, required, created_at)"
            " VALUES (?, ?, ?, ?)",
            ("T", self.rid, required, db.now_iso()),
        )

    def _assign_role(self):
        self.conn.execute(
            "INSERT INTO user_roles (user_id, role_id, assigned_at) VALUES (?, ?, ?)",
            (self.uid, self.rid, db.now_iso()),
        )

    def _complete(self, training_id):
        self.conn.execute(
            "INSERT INTO user_training (user_id, training_id, status, assigned_at,"
            " completed_at) VALUES (?, ?, 'completed', ?, ?)",
            (self.uid, training_id, db.now_iso(), db.now_iso()),
        )

    def test_not_qualified_until_required_training_done(self):
        self._add_training(required=1)
        self._assign_role()
        self.assertEqual(role_training_status(self.conn, self.uid, self.rid), (1, 0))
        self.assertFalse(is_qualified(self.conn, self.uid, self.rid))

    def test_qualified_once_required_training_completed(self):
        t1 = self._add_training(required=1)
        self._assign_role()
        self._complete(t1)
        self.assertEqual(role_training_status(self.conn, self.uid, self.rid), (1, 1))
        self.assertTrue(is_qualified(self.conn, self.uid, self.rid))

    def test_optional_training_does_not_gate(self):
        t1 = self._add_training(required=1)
        self._add_training(required=0)  # optional — must be ignored
        self._assign_role()
        self._complete(t1)
        # Only the one required training counts, and it's done.
        self.assertEqual(role_training_status(self.conn, self.uid, self.rid), (1, 1))
        self.assertTrue(is_qualified(self.conn, self.uid, self.rid))

    def test_role_with_no_required_training_is_qualified_when_assigned(self):
        self._assign_role()
        self.assertEqual(role_training_status(self.conn, self.uid, self.rid), (0, 0))
        self.assertTrue(is_qualified(self.conn, self.uid, self.rid))

    def test_not_qualified_without_the_role_even_if_trained(self):
        t1 = self._add_training(required=1)
        self._complete(t1)  # trained, but the role was never assigned
        self.assertFalse(is_qualified(self.conn, self.uid, self.rid))


if __name__ == "__main__":
    unittest.main()
