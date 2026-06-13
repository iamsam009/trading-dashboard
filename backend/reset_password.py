#!/usr/bin/env python3
"""
Reset a user's password directly in the database.

Usage (on EC2):
  docker exec trading_backend python reset_password.py <email> <new_password>

Example:
  docker exec trading_backend python reset_password.py admin@trading.com Admin@12345678
"""

import asyncio
import sys

from sqlalchemy import select
from app.core.security import hash_password
from app.db.base import async_session
from app.models.user import User


async def reset_password(email: str, new_password: str) -> None:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if user is None:
            print(f"ERROR: No user found with email '{email}'")
            return

        user.hashed_password = hash_password(new_password)
        await session.commit()
        print(f"SUCCESS: Password reset for '{email}'")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python reset_password.py <email> <new_password>")
        sys.exit(1)

    email = sys.argv[1]
    password = sys.argv[2]

    if len(password) < 8:
        print("ERROR: Password must be at least 8 characters")
        sys.exit(1)

    asyncio.run(reset_password(email, password))