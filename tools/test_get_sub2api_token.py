import json
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


SCRIPT = Path(__file__).with_name("get_sub2api_token.py")


class GetSub2ApiTokenTest(unittest.TestCase):
    def test_login_mode(self) -> None:
        class LoginHandler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                if payload["email"] != "admin@example.com" or payload["password"] != "secret":
                    self.send_response(401)
                    self.end_headers()
                    self.wfile.write(b'{"code":401,"message":"invalid credentials"}')
                    return

                body = {
                    "code": 0,
                    "message": "success",
                    "data": {
                        "access_token": "access-demo-token",
                        "refresh_token": "refresh-demo-token",
                        "expires_in": 3600,
                        "token_type": "Bearer",
                        "user": {"id": 1, "email": "admin@example.com", "role": "admin"},
                    },
                }
                encoded = json.dumps(body).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, format: str, *args) -> None:
                return

        server = HTTPServer(("127.0.0.1", 0), LoginHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 1)
        self.addCleanup(server.shutdown)

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--mode",
                "login",
                "--base-url",
                f"http://127.0.0.1:{server.server_port}",
                "--email",
                "admin@example.com",
                "--password",
                "secret",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["access_token"], "access-demo-token")
        self.assertEqual(payload["refresh_token"], "refresh-demo-token")
        self.assertEqual(payload["source"], "login")

    def test_localstorage_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "localstorage.json"
            path.write_text(
                json.dumps(
                    {
                        "auth_token": "browser-token",
                        "refresh_token": "browser-refresh-token",
                        "token_expires_at": "1770000000000",
                        "auth_user": json.dumps(
                            {"id": 1, "email": "admin@example.com", "role": "admin"}
                        ),
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--mode",
                    "localstorage",
                    "--localstorage-json",
                    str(path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["access_token"], "browser-token")
            self.assertEqual(payload["refresh_token"], "browser-refresh-token")
            self.assertEqual(payload["source"], "localstorage")

    def test_raw_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "localstorage.json"
            path.write_text(
                json.dumps({"auth_token": "raw-browser-token"}),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--mode",
                    "localstorage",
                    "--localstorage-json",
                    str(path),
                    "--raw-only",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
            self.assertEqual(result.stdout.strip(), "raw-browser-token")


if __name__ == "__main__":
    unittest.main()
