"""Command line entry point: python -m djin.cli <command>"""

from __future__ import annotations

import argparse
import getpass
import sys

from djin import auth
from djin.config import get_settings
from djin.storage import db, secrets


def _login() -> int:
    db.init_db()
    from djin.integrations import google_auth

    print(f"Connected Google account: {google_auth.run_login()}")
    return 0


def _logout(service: str) -> int:
    db.init_db()
    secrets.delete_token(service)
    print(f"Removed stored credentials for '{service}'.")
    return 0


def _status() -> int:
    db.init_db()
    settings = get_settings()
    schedules = db.list_schedules()
    from djin.integrations import google_auth

    def mark(value: bool) -> str:
        return "yes" if value else "no"

    print(f"Provider        : {settings.llm_provider} ({settings.llm_model})")
    print(f"LLM key present : {mark(bool(settings.llm_api_key))}")
    print(f"Google config   : {mark(settings.google_configured)}   connected: {mark(google_auth.is_connected())}")
    print(f"Search          : {settings.search_provider} (configured: {mark(settings.search_configured)})")
    print(f"Notes folder    : {settings.notes_dir}")
    print(
        f"Scheduler       : {mark(settings.scheduler_enabled)}"
        f" ({sum(item['enabled'] for item in schedules)} enabled, {len(schedules)} saved;"
        f" timezone: {settings.scheduler_timezone})"
    )
    print(f"ntfy push       : configured: {mark(settings.ntfy_configured)}")
    print(f"Database        : {settings.db_path}")
    print(f"Auto-approve write actions: {mark(settings.auto_approve_write)}")
    return 0


def _serve() -> int:
    from djin.server import run

    db.init_db()
    settings = get_settings()
    print(f"Djin is running at http://{settings.host}:{settings.port}")
    run()
    return 0


def _create_owner() -> int:
    db.init_db()
    if db.count_users() != 0:
        print("The owner account has already been created.")
        return 1

    username = auth.normalize_username(input("Owner username: "))
    password = getpass.getpass("Password (12-128 characters): ")
    confirmation = getpass.getpass("Confirm password: ")
    auth.validate_new_password(password)
    if password != confirmation:
        raise ValueError("Passwords do not match.")

    db.create_first_user(username, auth.hash_password(password))
    print(f"Created owner account '{username}'.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="djin", description="Djin personal assistant")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("serve", help="Start the local web UI")
    sub.add_parser("status", help="Show configuration and connection status")
    sub.add_parser("create-owner", help="Create the owner account interactively")

    login = sub.add_parser("login", help="Connect an account")
    login.add_argument("service", choices=["google"])

    logout = sub.add_parser("logout", help="Remove stored credentials for an account")
    logout.add_argument("service", choices=["google"])

    args = parser.parse_args(argv)
    try:
        if args.command == "serve":
            return _serve()
        if args.command == "status":
            return _status()
        if args.command == "create-owner":
            return _create_owner()
        if args.command == "login":
            return _login()
        if args.command == "logout":
            return _logout(args.service)
    except KeyboardInterrupt:
        print("\nCancelled.")
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
