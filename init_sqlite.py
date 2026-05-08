#!/usr/bin/env python
"""初始化 SQLite 数据库表"""
import os
import sys

os.environ["USE_SQLITE"] = "true"

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from backend.shared.database import engine
from backend.shared.models import Base
from backend.shared.security import hash_password

def init_db():
    """创建所有表"""
    print("创建数据库表...")
    Base.metadata.create_all(bind=engine)
    print("[OK] Table created")

def create_sample_data():
    """创建示例数据"""
    from backend.shared.models import Stock, User, UserQuota
    from backend.shared.database import SessionLocal

    db = SessionLocal()
    try:
        # 检查是否已有数据
        if db.query(Stock).count() == 0:
            print("添加示例股票...")
            stocks = [
                Stock(symbol="600519.SS", name="贵州茅台", market="SH", sector="食品饮料"),
                Stock(symbol="000858.SZ", name="五粮液", market="SZ", sector="食品饮料"),
                Stock(symbol="000651.SZ", name="格力电器", market="SZ", sector="家电"),
                Stock(symbol="600036.SS", name="招商银行", market="SH", sector="银行"),
                Stock(symbol="601398.SS", name="工商银行", market="SH", sector="银行"),
                Stock(symbol="000333.SZ", name="美的集团", market="SZ", sector="家电"),
                Stock(symbol="601888.SS", name="中国国旅", market="SH", sector="旅游"),
                Stock(symbol="603259.SS", name="药明康德", market="SH", sector="医药"),
            ]
            db.add_all(stocks)
            print(f"[OK] Added {len(stocks)} sample stocks")

        if db.query(User).count() == 0:
            seed_demo_users = os.getenv("SEED_DEMO_USERS", "false").lower() == "true"
            bootstrap_admin_password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "").strip()
            seed_users = []

            if seed_demo_users:
                print("创建演示用户...")
                test_user = User(
                    username="test",
                    email="test@example.com",
                    password_hash=hash_password("DemoUser123"),
                    nickname="测试用户",
                    role="free"
                )
                db.add(test_user)
                seed_users.append(test_user)
                print("[OK] Created demo user (username: test, password: DemoUser123)")

            if bootstrap_admin_password:
                print("创建启动管理员...")
                admin_user = User(
                    username=os.getenv("BOOTSTRAP_ADMIN_USERNAME", "admin"),
                    email=os.getenv("BOOTSTRAP_ADMIN_EMAIL", "admin@example.com"),
                    password_hash=hash_password(bootstrap_admin_password),
                    nickname="管理员",
                    role="admin"
                )
                db.add(admin_user)
                seed_users.append(admin_user)
                print("[OK] Created bootstrap admin from BOOTSTRAP_ADMIN_PASSWORD")

            if not seed_users:
                print("[INFO] No default users created. Use registration or set BOOTSTRAP_ADMIN_PASSWORD explicitly.")

            db.flush()

            # 为用户创建默认配额
            for user in seed_users:
                quota = UserQuota(
                    user_id=user.id,
                    daily_limit=10 if user.role == "free" else 1000,
                    monthly_limit=100 if user.role == "free" else 10000,
                )
                db.add(quota)
            if seed_users:
                print("[OK] Created default quotas")

        db.commit()
        print("[OK] Sample data created")
    except Exception as e:
        db.rollback()
        print("[FAIL] Create sample data failed: {}".format(e))
    finally:
        db.close()

if __name__ == "__main__":
    print("=" * 50)
    print("初始化 SQLite 数据库")
    print("=" * 50)
    init_db()
    create_sample_data()
    print()
    print("完成! 数据库文件: stock_platform.db")
