#!/usr/bin/env python3
"""
创建或提升管理员账号。

用法：
  python scripts/create_admin.py                          # 交互式输入
  python scripts/create_admin.py --username admin --password mypass
  python scripts/create_admin.py --username admin --password mypass --email admin@example.com
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main() -> None:
    parser = argparse.ArgumentParser(description="创建或提升管理员账号")
    parser.add_argument("--username", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--email", default="")
    args = parser.parse_args()

    username = args.username.strip() or input("用户名: ").strip()
    if not username:
        sys.exit("用户名不能为空")

    password = args.password.strip()
    if not password:
        password = getpass.getpass("密码: ").strip()
        if not password:
            sys.exit("密码不能为空")
    if len(password) < 6:
        sys.exit("密码至少6位")

    email = args.email.strip() or f"{username}@localhost"

    # 加载项目环境变量（如果有 .env）
    env_file = os.path.join(ROOT, ".env")
    if os.path.exists(env_file):
        from dotenv import load_dotenv
        load_dotenv(env_file, override=False)

    from backend.shared.database import SessionLocal, init_db
    from backend.shared.models import User, UserQuota
    from backend.shared.security import hash_password

    init_db()
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == username).first()
        if existing:
            existing.role = "admin"
            existing.is_active = True
            db.commit()
            print(f"[ok] 已将现有用户 '{username}' 提升为管理员")
            return

        user = User(
            username=username,
            email=email,
            password_hash=hash_password(password),
            nickname=username,
            role="admin",
            is_active=True,
        )
        db.add(user)
        db.flush()
        quota = db.query(UserQuota).filter(UserQuota.user_id == user.id).first()
        if not quota:
            db.add(UserQuota(user_id=user.id, daily_limit=999999, monthly_limit=999999))
        db.commit()
        print(f"[ok] 管理员账号 '{username}' 创建成功")
    except Exception as exc:
        db.rollback()
        sys.exit(f"[error] {exc}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
