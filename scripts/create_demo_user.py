"""Quick helper: create a single user from CLI args."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.database import AsyncSessionLocal
from app.auth import hash_password
from app.models.user import User, UserRole
from sqlalchemy import select


async def create_user(name: str, email: str, password: str, role: str, venue_id: int = 1):
    async with AsyncSessionLocal() as db:
        existing = await db.execute(select(User).where(User.email == email))
        if existing.scalar_one_or_none():
            print(f"User {email} already exists.")
            return
        user = User(
            name=name, email=email, password_hash=hash_password(password),
            role=UserRole(role), venue_id=venue_id,
        )
        db.add(user)
        await db.commit()
        print(f"Created {role}: {email}")


if __name__ == "__main__":
    if len(sys.argv) < 5:
        print("Usage: python create_demo_user.py <name> <email> <password> <manager|staff> [venue_id]")
        sys.exit(1)
    asyncio.run(create_user(
        sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4],
        int(sys.argv[5]) if len(sys.argv) > 5 else 1,
    ))
