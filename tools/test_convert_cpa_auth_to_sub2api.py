import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("convert_cpa_auth_to_sub2api.py")


class ConvertCpaAuthToSub2ApiTest(unittest.TestCase):
    def test_convert_codex_and_antigravity_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "source"
            source_dir.mkdir()
            output_path = Path(tmp) / "sub2api-import.json"

            codex_payload = {
                "type": "codex",
                "access_token": "codex-access",
                "refresh_token": "codex-refresh",
                "id_token": "codex-id-token",
                "account_id": "acct-123",
                "email": "codex@example.com",
                "expired": "2026-04-03T21:12:14+08:00",
                "websockets": True,
                "disabled": False,
            }
            antigravity_payload = {
                "type": "antigravity",
                "access_token": "ag-access",
                "refresh_token": "ag-refresh",
                "email": "ag@example.com",
                "project_id": "project-123",
                "expired": "2026-03-24T21:26:23+08:00",
                "disabled": False,
            }
            ignored_payload = {"hello": "world"}

            (source_dir / "codex@example.com.json").write_text(
                json.dumps(codex_payload), encoding="utf-8"
            )
            (source_dir / "antigravity-ag@example.com.json").write_text(
                json.dumps(antigravity_payload), encoding="utf-8"
            )
            (source_dir / "ignore.json").write_text(
                json.dumps(ignored_payload), encoding="utf-8"
            )

            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--source",
                    str(source_dir),
                    "--output",
                    str(output_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            bundle = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(bundle["data"]["type"], "sub2api-data")
            self.assertEqual(bundle["data"]["version"], 1)
            self.assertEqual(bundle["data"]["proxies"], [])
            self.assertTrue(bundle["skip_default_group_bind"])

            accounts = bundle["data"]["accounts"]
            self.assertEqual(len(accounts), 2)

            openai_account = next(
                item for item in accounts if item["platform"] == "openai"
            )
            self.assertEqual(openai_account["type"], "oauth")
            self.assertEqual(
                openai_account["credentials"]["chatgpt_account_id"], "acct-123"
            )
            self.assertEqual(
                openai_account["credentials"]["expires_at"],
                "2026-04-03T21:12:14+08:00",
            )
            self.assertTrue(
                openai_account["extra"]["openai_oauth_responses_websockets_v2_enabled"]
            )

            antigravity_account = next(
                item for item in accounts if item["platform"] == "antigravity"
            )
            self.assertEqual(antigravity_account["type"], "oauth")
            self.assertEqual(
                antigravity_account["credentials"]["project_id"], "project-123"
            )
            self.assertEqual(
                antigravity_account["credentials"]["expires_at"],
                "2026-03-24T21:26:23+08:00",
            )

    def test_skip_disabled_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "source"
            source_dir.mkdir()
            output_path = Path(tmp) / "sub2api-import.json"

            disabled_payload = {
                "type": "codex",
                "access_token": "codex-access",
                "refresh_token": "codex-refresh",
                "email": "disabled@example.com",
                "disabled": True,
            }
            (source_dir / "disabled.json").write_text(
                json.dumps(disabled_payload), encoding="utf-8"
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--source",
                    str(source_dir),
                    "--output",
                    str(output_path),
                ],
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("No supported codex/antigravity credential files found.", result.stderr)


if __name__ == "__main__":
    unittest.main()
