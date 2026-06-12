#!/usr/bin/env python3
"""
Generate a cryptographically-secure random secret key.

Usage:
    python generate_secret_key.py          # print a new key
    python generate_secret_key.py --write  # write directly to .env (WSL / Linux friendly)
"""

from __future__ import annotations

import secrets
import sys


def generate_key(length: int = 64) -> str:
    """Return a URL-safe, base64-encoded random string."""
    return secrets.token_urlsafe(length)


def main() -> None:
    key = generate_key()
    print(f"\n🔑  SECRET_KEY={key}\n")

    if "--write" in sys.argv or "-w" in sys.argv:
        env_path = __file__.rsplit("/", 1)[0] + "/.env" if "/" in __file__ else ".env"
        try:
            with open(env_path, "r") as fh:
                lines = fh.readlines()

            replaced = False
            new_lines: list[str] = []
            for line in lines:
                if line.startswith("SECRET_KEY="):
                    new_lines.append(f"SECRET_KEY={key}\n")
                    replaced = True
                else:
                    new_lines.append(line)

            if not replaced:
                new_lines.append(f"\nSECRET_KEY={key}\n")

            with open(env_path, "w") as fh:
                fh.writelines(new_lines)

            print(f"✅  Written to {env_path}\n")
        except FileNotFoundError:
            print("⚠️   .env file not found.  Copy the key above manually.\n")


if __name__ == "__main__":
    main()