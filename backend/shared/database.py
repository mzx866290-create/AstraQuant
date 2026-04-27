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

# 检测是否使用 SQLite
def _should_use_sqlite() -> bool:
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
        # 尝试找到项目根目录（包含 stock_platform.db 或 backend 目录）
        _candidates = [
            os.getcwd(),
            os.path.dirname(os.path.abspath(__file__)),  # backend/shared
        ]
        for _c in _candidates:
            _test = os.path.join(_c, _db_path)
            if os.path.exists(_test):
                _db_path = _test
                break
        else:
            # 默认放在当前工作目录
            _db_path = os.path.join(os.getcwd(), _db_path)

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
    """初始化数据库表"""
    from .models import Base
    Base.metadata.create_all(bind=engine)

