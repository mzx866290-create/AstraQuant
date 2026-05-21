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
            s.settimeout(2)
            result = s.connect_ex((db_host, int(os.getenv("DB_PORT", "5432"))))
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
    if USE_SQLITE:
        _apply_sqlite_compat_migrations()
    _bootstrap_admin()


def _apply_sqlite_compat_migrations() -> None:
    """Keep local SQLite databases compatible with the current ORM model.

    PostgreSQL deployments should use Alembic. This is only a local fallback so
    older demo databases do not fail at runtime when code reads newer columns.
    """
    migrations = {
        "research_observations": [
            ("summary_text", "summary_text TEXT"),
        ],
        "pipeline_run_logs": [
            ("industries_collected", "industries_collected INTEGER DEFAULT 0"),
            ("after_screening", "after_screening INTEGER DEFAULT 0"),
            ("after_hard_veto", "after_hard_veto INTEGER DEFAULT 0"),
            ("after_scoring", "after_scoring INTEGER DEFAULT 0"),
            ("vetoed_by_industry", "vetoed_by_industry INTEGER DEFAULT 0"),
            ("vetoed_by_acceleration", "vetoed_by_acceleration INTEGER DEFAULT 0"),
            ("vetoed_by_peer", "vetoed_by_peer INTEGER DEFAULT 0"),
            ("vetoed_by_fundamental", "vetoed_by_fundamental INTEGER DEFAULT 0"),
            ("vetoed_by_valuation", "vetoed_by_valuation INTEGER DEFAULT 0"),
            ("vetoed_by_risk", "vetoed_by_risk INTEGER DEFAULT 0"),
            ("duration_seconds", "duration_seconds INTEGER"),
        ],
        "industry_health_scores": [
            ("score_5d_ago", "score_5d_ago INTEGER"),
            ("score_change_5d", "score_change_5d INTEGER"),
            ("is_accelerating_down", "is_accelerating_down BOOLEAN DEFAULT 0"),
        ],
    }
    try:
        with engine.begin() as conn:
            table_names = {
                row[0]
                for row in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            for table, columns in migrations.items():
                if table not in table_names:
                    continue
                existing = {
                    row[1]
                    for row in conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
                }
                for column, ddl in columns:
                    if column in existing:
                        continue
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {ddl}")
                    logger.info("sqlite compat migration: added %s.%s", table, column)
    except Exception as exc:
        logger.warning("sqlite compat migration skipped: %s", exc)


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

