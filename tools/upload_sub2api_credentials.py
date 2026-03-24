#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import urllib.parse
import ssl
import sys
from pathlib import Path
from typing import Any
from urllib import error, request

from convert_cpa_auth_to_sub2api import (
    convert_sources,
    infer_provider,
    is_sub2api_bundle,
    iter_json_files,
    load_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Upload credential files to sub2api via /api/v1/admin/accounts/data."
        )
    )
    parser.add_argument(
        "--base-url",
        required=True,
        help="sub2api base URL, for example http://127.0.0.1:8080",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("SUB2API_ADMIN_TOKEN", ""),
        help="Admin Bearer token. Defaults to SUB2API_ADMIN_TOKEN.",
    )
    parser.add_argument(
        "--source",
        nargs="+",
        required=True,
        help=(
            "Source credential JSON files/directories, or a prebuilt "
            "sub2api import bundle."
        ),
    )
    parser.add_argument(
        "--default-concurrency",
        type=int,
        default=3,
        help="Default account concurrency when converting raw credentials.",
    )
    parser.add_argument(
        "--default-priority",
        type=int,
        default=50,
        help="Default account priority when converting raw credentials.",
    )
    parser.add_argument(
        "--include-disabled",
        action="store_true",
        help="Include disabled source credentials when converting raw files.",
    )
    parser.add_argument(
        "--save-bundle",
        help="Optional path to save the generated bundle before upload.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Skip TLS certificate verification for HTTPS.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate the bundle only and do not send the HTTP request.",
    )
    parser.add_argument(
        "--delete-before-upload",
        action="store_true",
        help="Delete matching remote sub2api accounts before upload.",
    )
    parser.add_argument(
        "--delete-only",
        action="store_true",
        help="Delete matching remote sub2api accounts only and skip upload.",
    )
    return parser.parse_args()


def load_bundle_or_convert(args: argparse.Namespace) -> tuple[dict[str, Any], list[str]]:
    if len(args.source) == 1:
        source_path = Path(args.source[0]).expanduser().resolve()
        payload = load_json(source_path)
        if payload is not None and is_sub2api_bundle(payload):
            return payload, []

    bundle, warnings = convert_sources(
        args.source,
        args.default_concurrency,
        args.default_priority,
        args.include_disabled,
    )
    return bundle, warnings


def collect_supported_file_names(raw_sources: list[str]) -> list[str]:
    file_names: list[str] = []
    seen: set[str] = set()

    for path in iter_json_files(raw_sources):
        payload = load_json(path)
        if payload is None or is_sub2api_bundle(payload):
            continue
        if infer_provider(path, payload) is None:
            continue
        name = path.name
        if name in seen:
            continue
        seen.add(name)
        file_names.append(name)
    return file_names


def maybe_save_bundle(bundle: dict[str, Any], save_path: str | None) -> Path | None:
    if not save_path:
        return None
    output_path = Path(save_path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(bundle, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return output_path


def build_ssl_context(insecure: bool) -> ssl.SSLContext | None:
    if not insecure:
        return None
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def build_headers(token: str) -> dict[str, str]:
    if not token.strip():
        raise ValueError("token is required; pass --token or set SUB2API_ADMIN_TOKEN")
    return {
        "Authorization": f"Bearer {token.strip()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def http_request(
    method: str,
    url: str,
    token: str,
    timeout: int,
    insecure: bool,
    body: dict[str, Any] | None = None,
) -> tuple[int, str]:
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")

    req = request.Request(
        url,
        data=data,
        method=method,
        headers=build_headers(token),
    )
    context = build_ssl_context(insecure)

    try:
        with request.urlopen(req, timeout=timeout, context=context) as resp:
            response_body = resp.read().decode("utf-8", errors="replace")
            return resp.getcode(), response_body
    except error.HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        return exc.code, response_body


def parse_json_response(status_code: int, response_body: str) -> dict[str, Any]:
    if status_code < 200 or status_code >= 300:
        raise ValueError(f"HTTP {status_code}: {response_body}")
    try:
        payload = json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON response: {response_body}") from exc
    if payload.get("code") != 0:
        raise ValueError(f"sub2api error response: {response_body}")
    return payload


def collect_remote_account_matches(
    base_url: str,
    token: str,
    bundle: dict[str, Any],
    timeout: int,
    insecure: bool,
) -> list[dict[str, Any]]:
    targets = {
        (
            str(account.get("name", "")).strip(),
            str(account.get("platform", "")).strip(),
            str(account.get("type", "")).strip(),
        )
        for account in bundle.get("data", {}).get("accounts", [])
    }
    targets = {item for item in targets if all(item)}
    if not targets:
        return []

    matches: list[dict[str, Any]] = []
    seen_ids: set[int] = set()

    for name, platform, account_type in sorted(targets):
        page = 1
        page_size = 100
        while True:
            query = urllib.parse.urlencode(
                {
                    "page": page,
                    "page_size": page_size,
                    "platform": platform,
                    "type": account_type,
                    "search": name,
                }
            )
            url = base_url.rstrip("/") + "/api/v1/admin/accounts?" + query
            status_code, response_body = http_request(
                "GET",
                url,
                token,
                timeout,
                insecure,
            )
            payload = parse_json_response(status_code, response_body)
            data = payload.get("data") or {}
            items = data.get("items") or []
            if not isinstance(items, list):
                break

            for item in items:
                if not isinstance(item, dict):
                    continue
                if (
                    str(item.get("name", "")).strip() == name
                    and str(item.get("platform", "")).strip() == platform
                    and str(item.get("type", "")).strip() == account_type
                ):
                    account_id = item.get("id")
                    if isinstance(account_id, int) and account_id not in seen_ids:
                        seen_ids.add(account_id)
                        matches.append(item)

            total = data.get("total", 0)
            if not isinstance(total, int):
                break
            if page * page_size >= total or not items:
                break
            page += 1

    return matches


def delete_remote_accounts(
    base_url: str,
    token: str,
    accounts: list[dict[str, Any]],
    timeout: int,
    insecure: bool,
) -> list[tuple[int, str]]:
    deleted: list[tuple[int, str]] = []
    for item in accounts:
        account_id = item["id"]
        name = str(item.get("name", "")).strip() or f"account-{account_id}"
        url = base_url.rstrip("/") + f"/api/v1/admin/accounts/{account_id}"
        status_code, response_body = http_request(
            "DELETE",
            url,
            token,
            timeout,
            insecure,
        )
        parse_json_response(status_code, response_body)
        deleted.append((account_id, name))
    return deleted


def delete_remote_accounts_by_file_names(
    base_url: str,
    token: str,
    file_names: list[str],
    timeout: int,
    insecure: bool,
    dry_run: bool,
) -> dict[str, Any]:
    if not file_names:
        return {
            "requested_files": 0,
            "matched_files": 0,
            "deleted_accounts": 0,
            "not_found_files": 0,
            "dry_run": dry_run,
            "results": [],
        }

    endpoint = base_url.rstrip("/") + "/api/v1/admin/accounts/delete-by-file-names"
    status_code, response_body = http_request(
        "POST",
        endpoint,
        token,
        timeout,
        insecure,
        body={"file_names": file_names, "dry_run": dry_run},
    )
    payload = parse_json_response(status_code, response_body)
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError(f"invalid delete response: {response_body}")
    return data


def upload_bundle(
    base_url: str,
    token: str,
    bundle: dict[str, Any],
    timeout: int,
    insecure: bool,
) -> tuple[int, str]:
    endpoint = base_url.rstrip("/") + "/api/v1/admin/accounts/data"
    return http_request(
        "POST",
        endpoint,
        token,
        timeout,
        insecure,
        body=bundle,
    )


def main() -> int:
    args = parse_args()
    if args.default_concurrency < 0:
        raise SystemExit("--default-concurrency must be >= 0")
    if args.default_priority < 0:
        raise SystemExit("--default-priority must be >= 0")

    try:
        bundle, warnings = load_bundle_or_convert(args)
    except (FileNotFoundError, ValueError) as exc:
        sys.stderr.write(f"{exc}\n")
        return 1

    saved = maybe_save_bundle(bundle, args.save_bundle)
    if saved is not None:
        print(f"Saved bundle -> {saved}")

    account_count = len(bundle.get("data", {}).get("accounts", []))
    print(f"Prepared {account_count} account(s) for upload.")
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)

    if args.delete_before_upload or args.delete_only:
        file_names = collect_supported_file_names(args.source)
        if file_names:
            try:
                delete_result = delete_remote_accounts_by_file_names(
                    args.base_url,
                    args.token,
                    file_names,
                    args.timeout,
                    args.insecure,
                    args.dry_run,
                )
            except ValueError as exc:
                sys.stderr.write(f"{exc}\n")
                return 1

            print(
                "Delete by file names: "
                f"requested={delete_result.get('requested_files', 0)} "
                f"matched={delete_result.get('matched_files', 0)} "
                f"deleted={delete_result.get('deleted_accounts', 0)} "
                f"not_found={delete_result.get('not_found_files', 0)}"
            )
            for item in delete_result.get("results", []):
                if not isinstance(item, dict):
                    continue
                print(
                    "delete-result: "
                    f"file={item.get('file_name')} "
                    f"matched_ids={item.get('matched_account_ids', [])} "
                    f"deleted_ids={item.get('deleted_account_ids', [])} "
                    f"error={item.get('error', '')}"
                )
        else:
            try:
                matches = collect_remote_account_matches(
                    args.base_url,
                    args.token,
                    bundle,
                    args.timeout,
                    args.insecure,
                )
            except ValueError as exc:
                sys.stderr.write(f"{exc}\n")
                return 1

            print(f"Matched {len(matches)} remote account(s) for deletion.")
            for item in matches:
                print(
                    "delete-match: "
                    f"id={item.get('id')} "
                    f"name={item.get('name')} "
                    f"platform={item.get('platform')} "
                    f"type={item.get('type')}"
                )

            if not args.dry_run and matches:
                try:
                    deleted = delete_remote_accounts(
                        args.base_url,
                        args.token,
                        matches,
                        args.timeout,
                        args.insecure,
                    )
                except ValueError as exc:
                    sys.stderr.write(f"{exc}\n")
                    return 1
                print(f"Deleted {len(deleted)} remote account(s).")

    if args.dry_run:
        print("Dry run enabled; upload skipped.")
        return 0

    if args.delete_only:
        print("Delete only mode enabled; upload skipped.")
        return 0

    try:
        status_code, response_body = upload_bundle(
            args.base_url,
            args.token,
            bundle,
            args.timeout,
            args.insecure,
        )
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1

    print(f"HTTP {status_code}")
    print(response_body)

    try:
        parse_json_response(status_code, response_body)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
