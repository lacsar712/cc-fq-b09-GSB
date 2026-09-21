"""端到端弱位点流程：FastAPI + SQLite（内存），无需 PostgreSQL。

覆盖迭代约定：
- 成功作业按可配置阈值由服务端算出 weak_positions 写入 metrics
- 运维可改阈值；对已成功作业提供重算入口，清单随之更新
- 失败作业无 per_position → 重算被拒绝，指标中无弱位点数据
- 审计员可见清单但不可改阈值 / 不可重算（403）
"""

import os
from pathlib import Path

# 避免 app.database 默认指向 PostgreSQL（本测试用内存 SQLite 全覆盖）
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.api as api_module
from app.database import get_db
from app.main import app
from app.models import Base

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)


def _override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db
# 后台任务用的是 api 模块内导入的 SessionLocal，替换为测试会话
api_module.SessionLocal = TestingSessionLocal

# 不以上下文管理器运行，避免 lifespan 连接默认数据库；表结构已在上方创建
client = TestClient(app)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
GOOD_FASTQ = (DATA_DIR / "good.fastq").read_text(encoding="utf-8")
BROKEN_FASTQ = (DATA_DIR / "broken.fastq").read_text(encoding="utf-8")


def _login(username: str, password: str) -> dict:
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _create_job(fastq: str, headers: dict) -> dict:
    res = client.post("/api/jobs", json={"fastqText": fastq}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


def test_weak_positions_full_flow():
    bioops = _login("bioops", "fastq123456")
    auditor = _login("auditor", "audit123456")

    # 1. 提交合格样例：成功结束时按默认阈值 30 算出 weak_positions 写入指标
    job = _create_job(GOOD_FASTQ, bioops)
    res = client.get(f"/api/jobs/{job['id']}", headers=auditor)  # 审计员可读
    assert res.status_code == 200
    done = res.json()
    assert done["status"] == "success"
    metrics = done["metrics"]
    assert metrics["weak_threshold"] == 30.0
    assert metrics["weak_positions"] == []  # 合格样例在默认阈值下无弱位点
    assert metrics["per_position"]

    # 2. 审计员不可改阈值、不可重算（403）
    res = client.put("/api/config/weak-threshold", json={"threshold": 41.0}, headers=auditor)
    assert res.status_code == 403
    res = client.post(f"/api/jobs/{job['id']}/recompute-weak", headers=auditor)
    assert res.status_code == 403

    # 3. 运维调高下限（自测场景：调高后对合格作业重算）
    res = client.put("/api/config/weak-threshold", json={"threshold": 41.0}, headers=bioops)
    assert res.status_code == 200
    assert res.json()["threshold"] == 41.0
    # 阈值越界被拒绝
    res = client.put("/api/config/weak-threshold", json={"threshold": 120}, headers=bioops)
    assert res.status_code == 422

    # 审计员可见当前阈值（只读）
    res = client.get("/api/config/weak-threshold", headers=auditor)
    assert res.status_code == 200
    assert res.json()["threshold"] == 41.0
    assert res.json()["updated_by"] == "bioops"

    # 4. 重算入口：弱位点清单非空且与阈值规则一致
    res = client.post(f"/api/jobs/{job['id']}/recompute-weak", headers=bioops)
    assert res.status_code == 200
    recomputed = res.json()["metrics"]
    assert recomputed["weak_threshold"] == 41.0
    weak = recomputed["weak_positions"]
    assert len(weak) > 0
    expected = [
        {"position": p["position"], "mean_quality": p["mean_quality"]}
        for p in recomputed["per_position"]
        if p["mean_quality"] < 41.0
    ]
    assert weak == expected
    assert all(w["mean_quality"] < 41.0 for w in weak)
    assert recomputed["report"]["weak_count"] == len(weak)
    assert recomputed["summary"]["weak_count"] == len(weak)

    # 5. 重算结果已落库：再次读取保持一致
    res = client.get(f"/api/jobs/{job['id']}", headers=auditor)
    assert res.json()["metrics"]["weak_positions"] == expected


def test_recompute_rejected_for_failed_job():
    bioops = _login("bioops", "fastq123456")

    job = _create_job(BROKEN_FASTQ, bioops)
    res = client.get(f"/api/jobs/{job['id']}", headers=bioops)
    done = res.json()
    assert done["status"] == "failed"
    # 失败作业无 per_position / weak_positions 数据
    assert not (done["metrics"] or {}).get("per_position")
    assert not (done["metrics"] or {}).get("weak_positions")

    res = client.post(f"/api/jobs/{job['id']}/recompute-weak", headers=bioops)
    assert res.status_code == 409
