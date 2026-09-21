"""Pytest 配置：用 SQLite（NullPool，允许后台任务线程建连）跑 API 测试。"""

import os
import tempfile
from pathlib import Path

_TMP_DB = Path(tempfile.gettempdir()) / "fq_qc_pytest.sqlite"
if _TMP_DB.exists():
    _TMP_DB.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB}"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

import app.database as database  # noqa: E402
import app.main as main_pkg  # noqa: E402

# 替换引擎：文件 SQLite + 每连接独立池，后台任务线程可自行建连
_test_engine = create_engine(
    f"sqlite:///{_TMP_DB}",
    connect_args={"check_same_thread": False},
    poolclass=NullPool,
)
database.engine = _test_engine
database.SessionLocal.configure(bind=_test_engine)
main_pkg.engine = _test_engine


@pytest.fixture(scope="session")
def client():
    database.Base.metadata.create_all(bind=_test_engine)
    with TestClient(main_pkg.app) as c:
        yield c


@pytest.fixture
def db():
    session = database.SessionLocal()
    try:
        yield session
    finally:
        session.close()
