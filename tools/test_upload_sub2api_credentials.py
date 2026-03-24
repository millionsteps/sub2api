import json
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


SCRIPT = Path(__file__).with_name("upload_sub2api_credentials.py")


class _UploadHandler(BaseHTTPRequestHandler):
    requests = []

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        self.__class__.requests.append(
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "body": json.loads(body),
            }
        )
        payload = {
            "code": 0,
            "data": {
                "requested_files": len(self.__class__.requests[-1]["body"]["file_names"]),
                "matched_files": 0,
                "deleted_accounts": 0,
                "not_found_files": len(self.__class__.requests[-1]["body"]["file_names"]),
                "proxy_created": 0,
                "proxy_reused": 0,
                "proxy_failed": 0,
                "account_created": len(
                    self.__class__.requests[-1]["body"]["data"]["accounts"]
                ),
                "account_failed": 0,
                "results": [],
            },
        }
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args) -> None:
        return


class UploadSub2ApiCredentialsTest(unittest.TestCase):
    def test_upload_raw_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "source"
            source_dir.mkdir()
            codex_payload = {
                "type": "codex",
                "access_token": "codex-access",
                "refresh_token": "codex-refresh",
                "account_id": "acct-123",
                "email": "codex@example.com",
                "expired": "2026-04-03T21:12:14+08:00",
                "websockets": True,
            }
            antigravity_payload = {
                "type": "antigravity",
                "access_token": "ag-access",
                "refresh_token": "ag-refresh",
                "email": "ag@example.com",
                "project_id": "project-123",
                "expired": "2026-03-24T21:26:23+08:00",
            }
            (source_dir / "codex.json").write_text(
                json.dumps(codex_payload), encoding="utf-8"
            )
            (source_dir / "antigravity.json").write_text(
                json.dumps(antigravity_payload), encoding="utf-8"
            )

            _UploadHandler.requests = []
            server = HTTPServer(("127.0.0.1", 0), _UploadHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.server_close)
            self.addCleanup(thread.join, 1)
            self.addCleanup(server.shutdown)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--base-url",
                    f"http://127.0.0.1:{server.server_port}",
                    "--token",
                    "demo-token",
                    "--source",
                    str(source_dir),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
            self.assertEqual(len(_UploadHandler.requests), 1)
            req = _UploadHandler.requests[0]
            self.assertEqual(req["path"], "/api/v1/admin/accounts/replace-by-file-names")
            self.assertEqual(req["authorization"], "Bearer demo-token")
            self.assertEqual(req["body"]["data"]["type"], "sub2api-data")
            self.assertEqual(len(req["body"]["data"]["accounts"]), 2)
            self.assertEqual(req["body"]["file_names"], ["antigravity.json", "codex.json"])

    def test_dry_run_prebuilt_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle_path = Path(tmp) / "bundle.json"
            bundle = {
                "data": {
                    "type": "sub2api-data",
                    "version": 1,
                    "exported_at": "2026-03-24T00:00:00Z",
                    "proxies": [],
                    "accounts": [
                        {
                            "name": "demo",
                            "platform": "openai",
                            "type": "oauth",
                            "credentials": {"access_token": "token"},
                            "concurrency": 3,
                            "priority": 50,
                        }
                    ],
                },
                "skip_default_group_bind": True,
            }
            bundle_path.write_text(json.dumps(bundle), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--base-url",
                    "http://127.0.0.1:8080",
                    "--token",
                    "demo-token",
                    "--source",
                    str(bundle_path),
                    "--dry-run",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
            self.assertIn("Dry run enabled; upload skipped.", result.stdout)

    def test_delete_before_upload(self) -> None:
        class DeleteAwareHandler(BaseHTTPRequestHandler):
            calls = []

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                self.__class__.calls.append(("POST", self.path, body))
                if self.path == "/api/v1/admin/accounts/get-by-file-names":
                    payload = {
                        "code": 0,
                        "data": {
                            "requested_files": 2,
                            "matched_files": 2,
                            "not_found_files": 0,
                            "results": [
                                {
                                    "file_name": "codex.json",
                                    "matched_account_ids": [101],
                                    "matched_accounts": [
                                        {
                                            "id": 101,
                                            "name": "codex-codex@example.com",
                                            "platform": "openai",
                                            "type": "oauth",
                                        }
                                    ],
                                },
                                {
                                    "file_name": "antigravity.json",
                                    "matched_account_ids": [202],
                                    "matched_accounts": [
                                        {
                                            "id": 202,
                                            "name": "antigravity-ag@example.com",
                                            "platform": "antigravity",
                                            "type": "oauth",
                                        }
                                    ],
                                },
                            ],
                        },
                    }
                elif self.path == "/api/v1/admin/accounts/delete-by-file-names":
                    payload = {
                        "code": 0,
                        "data": {
                            "requested_files": 2,
                            "matched_files": 2,
                            "deleted_accounts": 2,
                            "not_found_files": 0,
                            "dry_run": False,
                            "results": [
                                {
                                    "file_name": "codex.json",
                                    "matched_account_ids": [101],
                                    "deleted_account_ids": [101],
                                },
                                {
                                    "file_name": "antigravity.json",
                                    "matched_account_ids": [202],
                                    "deleted_account_ids": [202],
                                },
                            ],
                        },
                    }
                else:
                    payload = {"code": 0, "data": {"account_created": 2}}
                encoded = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, format: str, *args) -> None:
                return

        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "source"
            source_dir.mkdir()
            (source_dir / "codex.json").write_text(
                json.dumps(
                    {
                        "type": "codex",
                        "access_token": "codex-access",
                        "refresh_token": "codex-refresh",
                        "account_id": "acct-123",
                        "email": "codex@example.com",
                    }
                ),
                encoding="utf-8",
            )
            (source_dir / "antigravity.json").write_text(
                json.dumps(
                    {
                        "type": "antigravity",
                        "access_token": "ag-access",
                        "refresh_token": "ag-refresh",
                        "email": "ag@example.com",
                        "project_id": "project-123",
                    }
                ),
                encoding="utf-8",
            )

            DeleteAwareHandler.calls = []
            server = HTTPServer(("127.0.0.1", 0), DeleteAwareHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.server_close)
            self.addCleanup(thread.join, 1)
            self.addCleanup(server.shutdown)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--base-url",
                    f"http://127.0.0.1:{server.server_port}",
                    "--token",
                    "demo-token",
                    "--source",
                    str(source_dir),
                    "--delete-before-upload",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
            self.assertTrue(
                any(
                    method == "POST"
                    and path == "/api/v1/admin/accounts/get-by-file-names"
                    and body["file_names"] == ["antigravity.json", "codex.json"]
                    for method, path, body in DeleteAwareHandler.calls
                )
            )
            self.assertTrue(
                any(
                    method == "POST"
                    and path == "/api/v1/admin/accounts/delete-by-file-names"
                    and body["file_names"] == ["antigravity.json", "codex.json"]
                    for method, path, body in DeleteAwareHandler.calls
                )
            )
            self.assertTrue(
                any(
                    method == "POST" and path == "/api/v1/admin/accounts/data"
                    for method, path, _ in DeleteAwareHandler.calls
                )
            )

    def test_replace_by_file_names_used_for_raw_credentials(self) -> None:
        class ReplaceHandler(BaseHTTPRequestHandler):
            calls = []

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                self.__class__.calls.append(("POST", self.path, body))
                payload = {
                    "code": 0,
                    "data": {
                        "requested_files": 2,
                        "matched_files": 1,
                        "deleted_accounts": 1,
                        "not_found_files": 1,
                        "proxy_created": 0,
                        "proxy_reused": 0,
                        "proxy_failed": 0,
                        "account_created": 2,
                        "account_failed": 0,
                        "results": [],
                    },
                }
                encoded = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, format: str, *args) -> None:
                return

        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "source"
            source_dir.mkdir()
            (source_dir / "codex.json").write_text(
                json.dumps(
                    {
                        "type": "codex",
                        "access_token": "codex-access",
                        "refresh_token": "codex-refresh",
                        "account_id": "acct-123",
                        "email": "codex@example.com",
                    }
                ),
                encoding="utf-8",
            )
            (source_dir / "antigravity.json").write_text(
                json.dumps(
                    {
                        "type": "antigravity",
                        "access_token": "ag-access",
                        "refresh_token": "ag-refresh",
                        "email": "ag@example.com",
                        "project_id": "project-123",
                    }
                ),
                encoding="utf-8",
            )

            ReplaceHandler.calls = []
            server = HTTPServer(("127.0.0.1", 0), ReplaceHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.server_close)
            self.addCleanup(thread.join, 1)
            self.addCleanup(server.shutdown)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--base-url",
                    f"http://127.0.0.1:{server.server_port}",
                    "--token",
                    "demo-token",
                    "--source",
                    str(source_dir),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
            self.assertTrue(
                any(
                    method == "POST"
                    and path == "/api/v1/admin/accounts/replace-by-file-names"
                    and body["file_names"] == ["antigravity.json", "codex.json"]
                    for method, path, body in ReplaceHandler.calls
                )
            )


if __name__ == "__main__":
    unittest.main()
