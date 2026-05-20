"""One-off admin tool: list users and promote to admin."""
from __future__ import annotations

import sys

from app.db.connection import SessionLocal
from app.db.models import User


def list_users(db):
    users = db.query(User).order_by(User.id).all()
    print(f"\n{'ID':<5} {'Username':<30} {'Role':<10} {'Email'}")
    print("-" * 75)
    for u in users:
        print(f"{u.id:<5} {u.username:<30} {u.role:<10} {u.email or ''}")
    print()


def promote(db, username: str):
    user = db.query(User).filter(User.username == username).first()
    if not user:
        print(f"User '{username}' not found.")
        return
    user.role = "admin"
    db.commit()
    print(f"'{username}' promoted to admin.")


def demote(db, username: str):
    user = db.query(User).filter(User.username == username).first()
    if not user:
        print(f"User '{username}' not found.")
        return
    user.role = "user"
    db.commit()
    print(f"'{username}' demoted to user.")


def main():
    db = SessionLocal()
    try:
        if len(sys.argv) == 1:
            list_users(db)
            print("Usage: python manage_users.py promote <username>")
            print("       python manage_users.py demote  <username>")
        elif sys.argv[1] == "promote" and len(sys.argv) == 3:
            promote(db, sys.argv[2])
            list_users(db)
        elif sys.argv[1] == "demote" and len(sys.argv) == 3:
            demote(db, sys.argv[2])
            list_users(db)
        else:
            print("Usage: python manage_users.py [promote|demote] <username>")
    finally:
        db.close()


if __name__ == "__main__":
    main()
