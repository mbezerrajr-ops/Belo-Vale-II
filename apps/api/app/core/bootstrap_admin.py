import argparse
import asyncio
import getpass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.models import User
from app.db.session import get_session_factory


async def create_first_admin(
    session: AsyncSession,
    email: str,
    password: str,
) -> User:
    if await session.scalar(select(User.id).limit(1)) is not None:
        raise RuntimeError("a user already exists; bootstrap is only for the first admin")
    normalized_email = email.strip().lower()
    if normalized_email.count("@") != 1:
        raise ValueError("a valid email is required")
    if len(password) < 12:
        raise ValueError("password must contain at least 12 characters")
    admin = User(
        email=normalized_email,
        password_hash=hash_password(password),
        role="admin",
        is_active=True,
    )
    session.add(admin)
    await session.commit()
    return admin


async def _run(email: str) -> None:
    password = getpass.getpass("Initial admin password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise RuntimeError("password confirmation does not match")
    async with get_session_factory()() as session:
        admin = await create_first_admin(session, email, password)
    print(f"Initial admin created for {admin.email}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create the first admin without exposing its password in arguments or logs."
    )
    parser.add_argument("--email", required=True)
    args = parser.parse_args()
    asyncio.run(_run(args.email))


if __name__ == "__main__":
    main()
