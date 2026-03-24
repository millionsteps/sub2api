#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import json
import os
import ssl
import sys
from pathlib import Path
from typing import Any
from urllib import error, request


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Get a sub2api auth token by logging in, or read the current "
            "token from an exported browser localStorage JSON file."
        )
    )
    parser.add_argument(
        "--mode",
        choices=("login", "localstorage"),
        default="login",
        help="Token source mode.",
    )
    parser.add_argument(
        "--base-url",
        help="sub2api base URL, required in login mode.",
    )
    parser.add_argument(
        "--email",
        help="Login email, required in login mode.",
    )
    parser.add_argument(
        "--password",
        help="Login password. If omitted in login mode, prompt securely.",
    )
    parser.add_argument(
        "--turnstile-token",
        default="",
        help="Optional turnstile_token for login.",
    )
    parser.add_argument(
        "--localstorage-json",
        help=(
            "Path to an exported localStorage JSON file. "
            "Expected keys: auth_token / refresh_token / token_expires_at."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="HTTP timeout in seconds for login mode.",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Skip TLS certificate verification for HTTPS in login mode.",
    )
    parser.add_argument(
        "--raw-only",
        action="store_true",
        help="Only print the access token value.",
    )
    return parser.parse_args()


def build_ssl_context(insecure: bool) -> ssl.SSLContext | None:
    if not insecure:
        return None
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def http_post_json(
    url: str,
    payload: dict[str, Any],
    timeout: int,
    insecure: bool,
) -> tuple[int, str]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    context = build_ssl_context(insecure)
    try:
        with request.urlopen(req, timeout=timeout, context=context) as resp:
            return resp.getcode(), resp.read().decode("utf-8", errors="replace")
    except error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


def parse_login_response(status_code: int, response_body: str) -> dict[str, Any]:
    if status_code < 200 or status_code >= 300:
        raise ValueError(f"HTTP {status_code}: {response_body}")

    try:
        payload = json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON response: {response_body}") from exc

    if payload.get("code") != 0:
        raise ValueError(f"sub2api login failed: {response_body}")

    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError(f"invalid login response: {response_body}")

    if data.get("requires_2fa") is True:
        raise ValueError("login requires 2FA; this script does not handle /auth/login/2fa yet")

    token = str(data.get("access_token", "")).strip()
    if not token:
        raise ValueError(f"login response missing access_token: {response_body}")
    return data


def get_token_via_login(args: argparse.Namespace) -> dict[str, Any]:
    if not args.base_url:
        raise ValueError("--base-url is required in login mode")
    if not args.email:
        raise ValueError("--email is required in login mode")

    password = args.password
    if not password:
        password = getpass.getpass("Password: ")
    if not password:
        raise ValueError("password is required in login mode")

    endpoint = args.base_url.rstrip("/") + "/api/v1/auth/login"
    status_code, response_body = http_post_json(
        endpoint,
        {
            "email": args.email,
            "password": password,
            "turnstile_token": args.turnstile_token,
        },
        args.timeout,
        args.insecure,
    )
    data = parse_login_response(status_code, response_body)
    return {
        "source": "login",
        "access_token": data.get("access_token"),
        "refresh_token": data.get("refresh_token"),
        "expires_in": data.get("expires_in"),
        "token_type": data.get("token_type"),
        "user": data.get("user"),
    }


def parse_localstorage_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload

    # Support exports like: [{"key":"auth_token","value":"..."}, ...]
    if isinstance(payload, list):
        result: dict[str, Any] = {}
        for item in payload:
            if not isinstance(item, dict):
                continue
            key = item.get("key")
            if isinstance(key, str):
                result[key] = item.get("value")
        return result

    raise ValueError("unsupported localStorage JSON format")


def get_token_from_localstorage(args: argparse.Namespace) -> dict[str, Any]:
    if not args.localstorage_json:
        raise ValueError("--localstorage-json is required in localstorage mode")

    path = Path(args.localstorage_json).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"localStorage JSON not found: {path}")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"failed to read localStorage JSON: {path}") from exc

    data = parse_localstorage_payload(payload)
    token = str(data.get("auth_token", "")).strip()
    if not token:
        raise ValueError("auth_token not found in localStorage JSON")

    user = data.get("auth_user")
    if isinstance(user, str):
        try:
            user = json.loads(user)
        except json.JSONDecodeError:
            pass

    return {
        "source": "localstorage",
        "access_token": token,
        "refresh_token": data.get("refresh_token"),
        "token_expires_at": data.get("token_expires_at"),
        "user": user,
        "file": str(path),
    }


def main() -> int:
    args = parse_args()

    try:
        if args.mode == "login":
            result = get_token_via_login(args)
        else:
            result = get_token_from_localstorage(args)
    except (FileNotFoundError, ValueError) as exc:
        sys.stderr.write(f"{exc}\n")
        return 1

    access_token = str(result.get("access_token", "")).strip()
    if args.raw_only:
        print(access_token)
        return 0

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
