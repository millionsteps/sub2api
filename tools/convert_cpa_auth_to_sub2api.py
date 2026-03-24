#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DATA_TYPE = "sub2api-data"
DATA_VERSION = 1
PROVIDER_ANTIGRAVITY = "antigravity"
PROVIDER_CODEX = "codex"
PLATFORM_ANTIGRAVITY = "antigravity"
PLATFORM_OPENAI = "openai"
ACCOUNT_TYPE_OAUTH = "oauth"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert CLIProxyAPIPlus auth JSON files into a sub2api "
            "account import bundle."
        )
    )
    parser.add_argument(
        "--source",
        nargs="+",
        required=True,
        help="Source directories or JSON files from CLIProxyAPIPlus.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output JSON file path for sub2api import data.",
    )
    parser.add_argument(
        "--default-concurrency",
        type=int,
        default=3,
        help="Default account concurrency for generated accounts.",
    )
    parser.add_argument(
        "--default-priority",
        type=int,
        default=50,
        help="Default account priority for generated accounts.",
    )
    parser.add_argument(
        "--include-disabled",
        action="store_true",
        help="Include source credentials with disabled=true.",
    )
    return parser.parse_args()


def iter_json_files(raw_sources: list[str]) -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()

    for raw_source in raw_sources:
        path = Path(raw_source).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"source path not found: {path}")

        candidates = [path] if path.is_file() else sorted(path.rglob("*.json"))
        for candidate in candidates:
            if not candidate.is_file():
                continue
            if candidate in seen:
                continue
            seen.add(candidate)
            files.append(candidate)

    return files


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def is_sub2api_bundle(payload: dict[str, Any]) -> bool:
    data = payload.get("data")
    if not isinstance(data, dict):
        return False
    data_type = clean_string(data.get("type"))
    return data_type == DATA_TYPE


def clean_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)
    return ""


def clean_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    return None


def clean_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            return int(float(raw))
        except ValueError:
            return None
    return None


def infer_provider(path: Path, payload: dict[str, Any]) -> str | None:
    raw_type = clean_string(payload.get("type")).lower()
    if raw_type == PROVIDER_ANTIGRAVITY:
        return PROVIDER_ANTIGRAVITY
    if raw_type == PROVIDER_CODEX:
        return PROVIDER_CODEX

    file_name = path.name.lower()
    if file_name.startswith("antigravity-") and clean_string(payload.get("refresh_token")):
        return PROVIDER_ANTIGRAVITY

    return None


def infer_expires_at(payload: dict[str, Any]) -> str:
    for key in ("expires_at", "expired"):
        value = clean_string(payload.get(key))
        if value:
            return value

    timestamp = clean_int(payload.get("timestamp"))
    expires_in = clean_int(payload.get("expires_in"))
    if timestamp is None or expires_in is None:
        return ""

    # CLIProxyAPIPlus usually stores milliseconds since epoch.
    if timestamp > 10**12:
        base = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc)
    else:
        base = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    expires_at = base + timedelta(seconds=expires_in)
    return expires_at.isoformat().replace("+00:00", "Z")


def make_note(path: Path) -> str:
    return f"Imported from CLIProxyAPIPlus: {path.name}"


def build_openai_account(
    path: Path,
    payload: dict[str, Any],
    default_concurrency: int,
    default_priority: int,
) -> dict[str, Any]:
    email = clean_string(payload.get("email"))
    account_id = clean_string(payload.get("chatgpt_account_id")) or clean_string(
        payload.get("account_id")
    )

    credentials: dict[str, Any] = {}
    for source_key, target_key in (
        ("access_token", "access_token"),
        ("refresh_token", "refresh_token"),
        ("id_token", "id_token"),
        ("email", "email"),
        ("client_id", "client_id"),
        ("chatgpt_user_id", "chatgpt_user_id"),
        ("organization_id", "organization_id"),
        ("plan_type", "plan_type"),
    ):
        value = clean_string(payload.get(source_key))
        if value:
            credentials[target_key] = value

    if account_id:
        credentials["chatgpt_account_id"] = account_id

    expires_at = infer_expires_at(payload)
    if expires_at:
        credentials["expires_at"] = expires_at

    extra: dict[str, Any] = {}
    if clean_bool(payload.get("websockets")) or clean_bool(payload.get("websocket")):
        extra["openai_oauth_responses_websockets_v2_enabled"] = True

    name_suffix = email or path.stem
    account: dict[str, Any] = {
        "name": f"codex-{name_suffix}",
        "notes": make_note(path),
        "platform": PLATFORM_OPENAI,
        "type": ACCOUNT_TYPE_OAUTH,
        "credentials": credentials,
        "concurrency": default_concurrency,
        "priority": default_priority,
    }
    if extra:
        account["extra"] = extra
    return account


def build_antigravity_account(
    path: Path,
    payload: dict[str, Any],
    default_concurrency: int,
    default_priority: int,
) -> dict[str, Any]:
    credentials: dict[str, Any] = {}
    for key in ("access_token", "refresh_token", "email", "project_id", "token_type"):
        value = clean_string(payload.get(key))
        if value:
            credentials[key] = value

    expires_at = infer_expires_at(payload)
    if expires_at:
        credentials["expires_at"] = expires_at

    name_suffix = clean_string(payload.get("email")) or path.stem
    return {
        "name": f"antigravity-{name_suffix}",
        "notes": make_note(path),
        "platform": PLATFORM_ANTIGRAVITY,
        "type": ACCOUNT_TYPE_OAUTH,
        "credentials": credentials,
        "concurrency": default_concurrency,
        "priority": default_priority,
    }


def convert_payload(
    path: Path,
    payload: dict[str, Any],
    default_concurrency: int,
    default_priority: int,
    include_disabled: bool,
) -> tuple[dict[str, Any] | None, str | None]:
    disabled = clean_bool(payload.get("disabled"))
    if disabled and not include_disabled:
        return None, f"skip disabled credential: {path}"

    provider = infer_provider(path, payload)
    if provider == PROVIDER_CODEX:
        account = build_openai_account(
            path, payload, default_concurrency, default_priority
        )
    elif provider == PROVIDER_ANTIGRAVITY:
        account = build_antigravity_account(
            path, payload, default_concurrency, default_priority
        )
    else:
        return None, None

    if disabled and include_disabled:
        return (
            account,
            "source credential is disabled=true; sub2api import will create it as active: "
            f"{path}",
        )
    return account, None


def build_bundle(accounts: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "data": {
            "type": DATA_TYPE,
            "version": DATA_VERSION,
            "exported_at": datetime.now(tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "proxies": [],
            "accounts": accounts,
        },
        "skip_default_group_bind": True,
    }


def convert_sources(
    raw_sources: list[str],
    default_concurrency: int,
    default_priority: int,
    include_disabled: bool,
) -> tuple[dict[str, Any], list[str]]:
    files = iter_json_files(raw_sources)
    accounts: list[dict[str, Any]] = []
    warnings: list[str] = []

    for path in files:
        payload = load_json(path)
        if payload is None:
            continue

        account, warning = convert_payload(
            path,
            payload,
            default_concurrency,
            default_priority,
            include_disabled,
        )
        if account is not None:
            accounts.append(account)
        if warning:
            warnings.append(warning)

    if not accounts:
        raise ValueError("No supported codex/antigravity credential files found.")

    return build_bundle(accounts), warnings


def main() -> int:
    args = parse_args()
    if args.default_concurrency < 0:
        raise SystemExit("--default-concurrency must be >= 0")
    if args.default_priority < 0:
        raise SystemExit("--default-priority must be >= 0")

    try:
        bundle, warnings = convert_sources(
            args.source,
            args.default_concurrency,
            args.default_priority,
            args.include_disabled,
        )
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1

    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(bundle, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"Converted {len(bundle['data']['accounts'])} account(s) -> {output_path}")
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
