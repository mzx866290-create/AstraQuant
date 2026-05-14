"""
数据库连接管理 - SQLAlchemy 连接池
支持 PostgreSQL 和 SQLite (本地开发 fallback)
"""
import os
import sys
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool, StaticPool
from typing import Generator
import logging

logger = logging.getLogger(__name__)
from .config import is_production

# 检测是否使用 SQLite
def _should_use_sqlite() -> bool:
    if is_production():
        if os.getenv("USE_SQLITE", "").lower() == "true":
            raise RuntimeError("USE_SQLITE=true is forbidden in production")
        return False
    if os.getenv("USE_SQLITE", "").lower() == "true":
        return True
    db_host = os.getenv("DB_HOST", "postgres")
    if db_host in ("", "localhost", None):
        return True
    # 检查是否能连上 PostgreSQL，连不上就回退 SQLite
    if db_host == "postgres":
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1)
            result = s.connect_ex(("localhost", 5432))
            s.close()
            if result != 0:
                logger.info("PostgreSQL 不可用，切换到 SQLite 模式")
                return True
        except Exception:
            logger.info("PostgreSQL 检测失败，切换到 SQLite 模式")
            return True
    return False

USE_SQLITE = _should_use_sqlite()

if USE_SQLITE:
    # 确保 DB_PATH 是相对于项目根目录的绝对路径
    _db_path = os.getenv("DB_PATH", "stock_platform.db")
    if not os.path.isabs(_db_path):
        _project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        # 本地多服务启动时 cwd 会分别落在各服务目录，优先使用项目根目录的同一个 SQLite。
        _candidates = [
            _project_root,
            os.getcwd(),
            os.path.dirname(os.path.abspath(__file__)),  # backend/shared
        ]
        for _c in _candidates:
            _test = os.path.join(_c, _db_path)
            if os.path.exists(_test):
                _db_path = _test
                break
        else:
            _db_path = os.path.join(_project_root, _db_path)

    DATABASE_URL = f"sqlite:///{_db_path}"
    logger.info(f"使用 SQLite 数据库: {_db_path}")
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=os.getenv('LOG_LEVEL') == 'DEBUG',
    )
else:
    # PostgreSQL 配置
    DATABASE_URL = (
        f"postgresql://{os.getenv('DB_USER', '')}:"
        f"{os.getenv('DB_PASS', '')}@"
        f"{os.getenv('DB_HOST', 'postgres')}:"
        f"{os.getenv('DB_PORT', '5432')}/"
        f"{os.getenv('DB_NAME', 'stock_platform')}"
    )

    # 验证必要环境变量
    required_env_vars = ['DB_USER', 'DB_PASS']
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    if missing_vars:
        raise ValueError(f"缺少必要的数据库环境变量: {', '.join(missing_vars)}")

    engine = create_engine(
        DATABASE_URL,
        poolclass=QueuePool,
        pool_size=20,
        max_overflow=40,
        pool_pre_ping=True,
        echo=os.getenv('LOG_LEVEL') == 'DEBUG',
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """依赖注入: 获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """初始化数据库表，并按环境变量创建初始管理员账号（幂等）"""
    import logging
    import os
    from .models import Base
    Base.metadata.create_all(bind=engine)
    _bootstrap_admin()


def _bootstrap_admin() -> None:
    import logging
    import os
    username = os.getenv("ADMIN_USERNAME", "").strip()
    password = os.getenv("ADMIN_PASSWORD", "").strip()
    if not username or not password:
        return
    from .models import User, UserQuota
    from .security import hash_password
    logger = logging.getLogger(__name__)
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == username).first()
        if existing:
            if existing.role != "admin":
                existing.role = "admin"
                db.commit()
                logger.info("bootstrap: promoted existing user '%s' to admin", username)
            return
        user = User(
            username=username,
            email=os.getenv("ADMIN_EMAIL", f"{username}@localhost"),
            password_hash=hash_password(password),
            nickname=username,
            role="admin",
            is_active=True,
        )
        db.add(user)
        db.flush()
        quota = UserQuota(user_id=user.id, daily_limit=999999, monthly_limit=999999)
        db.add(quota)
        db.commit()
        logger.info("bootstrap: admin user '%s' created", username)
    except Exception as exc:
        db.rollback()
        logging.getLogger(__name__).warning("bootstrap admin failed: %s", exc)
    finally:
        db.close()

