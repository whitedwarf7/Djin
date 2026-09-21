from __future__ import annotations

import os
import tempfile
import unittest
import uuid
from unittest.mock import patch


class AuthenticationApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data_dir = tempfile.TemporaryDirectory()
        cls.environment = patch.dict(
            os.environ,
            {
                "DJIN_DATA_DIR": cls.data_dir.name,
                "DJIN_NOTES_DIR": os.path.join(cls.data_dir.name, "notes"),
                "DJIN_SCHEDULER_ENABLED": "false",
            },
        )
        cls.environment.start()

        from fastapi.testclient import TestClient

        from djin import auth
        from djin.config import get_settings
        from djin.server import app
        from djin.storage import db

        get_settings.cache_clear()
        auth._signing_key.cache_clear()
        cls.TestClient = TestClient
        cls.app = app
        cls.auth = auth
        cls.db = db
        cls.client_context = TestClient(
            app,
            base_url="http://127.0.0.1:8765",
            client=("127.0.0.1", 50000),
        )
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        from djin.config import get_settings

        cls.client_context.__exit__(None, None, None)
        cls.auth._signing_key.cache_clear()
        get_settings.cache_clear()
        cls.environment.stop()
        cls.data_dir.cleanup()

    def test_authentication_and_authorization_flow(self) -> None:
        self.assertEqual(
            self.client.get("/api/auth/setup").json(),
            {"registration_required": True, "registration_allowed": True},
        )
        protected_requests = [
            ("GET", "/api/auth/me", None),
            ("POST", "/api/auth/logout", None),
            ("GET", "/api/status", None),
            ("POST", "/api/chat", {"message": "hello"}),
            ("POST", "/api/chat/stream", {"message": "hello"}),
            ("POST", "/api/actions/missing/decision", {"approve": False}),
            ("POST", "/api/actions/missing/decision/stream", {"approve": False}),
            ("GET", "/api/voice/config", None),
            ("POST", "/api/voice/transcribe", None),
            ("POST", "/api/voice/speak", {"text": "hello"}),
            ("GET", "/api/conversations", None),
            ("GET", "/api/conversations/missing", None),
            ("DELETE", "/api/conversations/missing", None),
            ("GET", "/api/audit", None),
        ]
        for method, path, body in protected_requests:
            with self.subTest(method=method, path=path):
                response = self.client.request(method, path, json=body)
                self.assertEqual(response.status_code, 401, response.text)

        registration = {
            "username": "owner",
            "password": "correct horse battery staple",
        }
        remote_client = self.TestClient(
            self.app,
            base_url="http://djin.example",
            client=("203.0.113.8", 50001),
        )
        try:
            remote_setup_state = remote_client.get("/api/auth/setup")
            remote_setup = remote_client.post(
                "/api/auth/register",
                json=registration,
                headers={"Origin": "http://djin.example"},
            )
        finally:
            remote_client.close()
        self.assertEqual(
            remote_setup_state.json(),
            {"registration_required": True, "registration_allowed": False},
        )
        self.assertEqual(remote_setup.status_code, 403)

        for header in self.auth.PROXY_HEADERS:
            with self.subTest(proxy_header=header):
                proxied_setup = self.client.post(
                    "/api/auth/register",
                    json=registration,
                    headers={
                        header: "proxy-value",
                        "Origin": "http://127.0.0.1:8765",
                    },
                )
                self.assertEqual(proxied_setup.status_code, 403)

        foreign_origin = self.client.post(
            "/api/auth/register",
            json=registration,
            headers={"Origin": "http://malicious.local"},
        )
        self.assertEqual(foreign_origin.status_code, 403)

        weak_password = self.client.post(
            "/api/auth/register",
            json={
                "username": "owner",
                "password": "too-short",
            },
        )
        self.assertEqual(weak_password.status_code, 422)
        self.assertNotIn("too-short", weak_password.text)

        created = self.client.post(
            "/api/auth/register",
            json={
                "username": "Owner",
                "password": "correct horse battery staple",
            },
            headers={"Origin": "http://127.0.0.1:8765"},
        )
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["user"]["role"], "admin")
        self.assertIn("httponly", created.headers["set-cookie"].lower())
        self.assertIn("samesite=strict", created.headers["set-cookie"].lower())
        owner_token = created.json()["access_token"]

        self.assertEqual(self.client.get("/api/status").status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me").json()["username"], "owner")
        duplicate = self.client.post(
            "/api/auth/register",
            json={
                "username": "other",
                "password": "another secure password",
            },
        )
        self.assertEqual(duplicate.status_code, 409)

        cross_origin_logout = self.client.post(
            "/api/auth/logout", headers={"Origin": "http://malicious.local"}
        )
        self.assertEqual(cross_origin_logout.status_code, 403)
        self.assertEqual(self.client.get("/api/status").status_code, 200)
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 204)
        self.assertEqual(self.client.get("/api/status").status_code, 401)
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 401)
        invalid = self.client.post(
            "/api/auth/login",
            json={"username": "owner", "password": "wrong"},
        )
        self.assertEqual(invalid.status_code, 401)
        valid = self.client.post(
            "/api/auth/login",
            json={"username": "OWNER", "password": "correct horse battery staple"},
        )
        self.assertEqual(valid.status_code, 200)

        bearer_headers = {"Authorization": f"Bearer {owner_token}"}
        self.assertEqual(
            self.client.get("/api/status", headers=bearer_headers).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(
                "/api/status",
                headers={"Authorization": f"Bearer {owner_token}x"},
            ).status_code,
            401,
        )

        user_id = uuid.uuid4().hex
        with self.db.connect() as connection:
            connection.execute(
                "INSERT INTO users"
                " (id, username, password_hash, role, is_active, created_at)"
                " VALUES (?, ?, ?, 'user', 1, ?)",
                (
                    user_id,
                    "reader",
                    self.auth.hash_password("reader secure password"),
                    self.db.utcnow(),
                ),
            )
        user_token = self.auth.create_access_token(
            self.auth.AuthenticatedUser(id=user_id, username="reader", role="user")
        )
        user_headers = {"Authorization": f"Bearer {user_token}"}
        self.assertEqual(
            self.client.get("/api/audit", headers=user_headers).status_code,
            403,
        )

        with self.db.connect() as connection:
            connection.execute("UPDATE users SET is_active = 0 WHERE id = ?", (user_id,))
        self.assertEqual(
            self.client.get("/api/status", headers=user_headers).status_code,
            401,
        )

        for _ in range(self.auth.LOGIN_ATTEMPT_LIMIT):
            response = self.client.post(
                "/api/auth/login",
                json={"username": "missing", "password": "incorrect-password"},
            )
            self.assertEqual(response.status_code, 401)
        throttled = self.client.post(
            "/api/auth/login",
            json={"username": "missing", "password": "incorrect-password"},
        )
        self.assertEqual(throttled.status_code, 429)
        self.assertGreater(int(throttled.headers["retry-after"]), 0)

        original_limit = self.auth.MAX_LOGIN_SOURCES
        try:
            self.auth.MAX_LOGIN_SOURCES = 3
            self.auth._login_attempts.clear()
            for source in ("one", "two", "three", "four"):
                self.auth.register_login_attempt(source)
            self.assertLessEqual(len(self.auth._login_attempts), 3)
        finally:
            self.auth._login_attempts.clear()
            self.auth.MAX_LOGIN_SOURCES = original_limit


if __name__ == "__main__":
    unittest.main()