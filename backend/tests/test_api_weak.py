"""弱位点 API 自测：阈值配置、重算入口、权限映射、失败无数据。"""

import time

import pytest

from app.models import AppSetting, Job, JobStage, Sample

GOOD_FASTQ = """@SEQ1
ACGTACGT
+
IIIIHHHH
@SEQ2
NNNNACGT
+
IIIIIIII
"""

BROKEN_FASTQ = """@SEQ1
ACGT
NOTPLUS
IIII
"""

BIOOPS = ("bioops", "fastq123456")
AUDITOR = ("auditor", "audit123456")


@pytest.fixture(autouse=True)
def clean_tables(db):
    db.query(JobStage).delete()
    db.query(Job).delete()
    db.query(Sample).delete()
    db.query(AppSetting).delete()
    db.commit()
    yield


def _token(client, creds):
    r = client.post("/api/auth/login", json={"username": creds[0], "password": creds[1]})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _submit_and_wait(client, token, text, timeout=10.0):
    r = client.post("/api/jobs", json={"fastqText": text}, headers=_auth(token))
    assert r.status_code == 201, r.text
    job_id = r.json()["id"]
    deadline = time.time() + timeout
    while time.time() < deadline:
        got = client.get(f"/api/jobs/{job_id}", headers=_auth(token)).json()
        if got["status"] in ("success", "failed"):
            return got
        time.sleep(0.05)
    raise AssertionError("作业未在时限内结束")


def test_successful_job_writes_weak_positions_with_default_floor(client):
    token = _token(client, BIOOPS)
    job = _submit_and_wait(client, token, GOOD_FASTQ)
    assert job["status"] == "success"
    m = job["metrics"]
    assert len(m["per_position"]) == 8
    # 默认下限 28，质量 39.5/40 全部达标 → 空清单
    assert m["weak_positions"] == []
    assert m["weak_quality_floor"] == pytest.approx(28.0)


def test_raise_floor_and_recompute_gives_nonempty_consistent_list(client):
    """迭代自测：把下限调高后对合格作业重算，清单非空且与阈值规则一致。"""
    token = _token(client, BIOOPS)
    job = _submit_and_wait(client, token, GOOD_FASTQ)
    assert job["metrics"]["weak_positions"] == []

    # 运维调高下限
    r = client.put(
        "/api/quality-config",
        json={"weak_quality_floor": 39.7},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    cfg = r.json()
    assert cfg["weak_quality_floor"] == pytest.approx(39.7)
    assert cfg["source"] == "db"

    # 对已成功作业提供重算入口
    r = client.post(f"/api/jobs/{job['id']}/recompute-weak", headers=_auth(token))
    assert r.status_code == 200, r.text
    updated = r.json()["metrics"]
    weak = updated["weak_positions"]
    assert [w["position"] for w in weak] == [5, 6, 7, 8]
    assert all(w["mean_quality"] == 39.5 for w in weak)
    assert updated["weak_quality_floor"] == pytest.approx(39.7)
    # 清单每一项都严格低于阈值，且 per_position 中低于阈值的位点全部在清单内
    per_pos = {p["position"]: p["mean_quality"] for p in updated["per_position"]}
    weak_positions = {w["position"] for w in weak}
    assert all(w["mean_quality"] < 39.7 for w in weak)
    assert weak_positions == {pos for pos, q in per_pos.items() if q < 39.7}


def test_auditor_can_view_but_cannot_change_floor_or_recompute(client):
    token = _token(client, BIOOPS)
    job = _submit_and_wait(client, token, GOOD_FASTQ)
    auditor = _token(client, AUDITOR)

    # 审计员可见作业、指标、弱位点清单与当前配置
    r = client.get(f"/api/jobs/{job['id']}", headers=_auth(auditor))
    assert r.status_code == 200
    assert "weak_positions" in r.json()["metrics"]
    r = client.get("/api/quality-config", headers=_auth(auditor))
    assert r.status_code == 200

    # 不可改阈值
    r = client.put(
        "/api/quality-config",
        json={"weak_quality_floor": 39.7},
        headers=_auth(auditor),
    )
    assert r.status_code == 403
    # 不可重算
    r = client.post(f"/api/jobs/{job['id']}/recompute-weak", headers=_auth(auditor))
    assert r.status_code == 403


def test_failed_job_has_no_per_position_and_recompute_rejected(client):
    token = _token(client, BIOOPS)
    job = _submit_and_wait(client, token, BROKEN_FASTQ)
    assert job["status"] == "failed"
    assert not job["metrics"]
    r = client.post(f"/api/jobs/{job['id']}/recompute-weak", headers=_auth(token))
    assert r.status_code == 409
    assert "per_position" in r.json()["detail"]


def test_update_floor_can_apply_to_all_successful_jobs(client):
    token = _token(client, BIOOPS)
    job = _submit_and_wait(client, token, GOOD_FASTQ)
    assert job["metrics"]["weak_positions"] == []

    r = client.put(
        "/api/quality-config",
        json={"weak_quality_floor": 39.7, "apply_to_successful_jobs": True},
        headers=_auth(token),
    )
    assert r.status_code == 200
    got = client.get(f"/api/jobs/{job['id']}", headers=_auth(token)).json()
    assert [w["position"] for w in got["metrics"]["weak_positions"]] == [5, 6, 7, 8]

    # 调低阈值并批量重算 → 清单清空
    client.put(
        "/api/quality-config",
        json={"weak_quality_floor": 28.0, "apply_to_successful_jobs": True},
        headers=_auth(token),
    )
    got = client.get(f"/api/jobs/{job['id']}", headers=_auth(token)).json()
    assert got["metrics"]["weak_positions"] == []
    assert got["metrics"]["weak_quality_floor"] == pytest.approx(28.0)


def test_floor_validation_rejects_out_of_range(client):
    token = _token(client, BIOOPS)
    r = client.put(
        "/api/quality-config",
        json={"weak_quality_floor": 999},
        headers=_auth(token),
    )
    assert r.status_code == 422


def test_config_default_source_before_override(client):
    token = _token(client, BIOOPS)
    r = client.get("/api/quality-config", headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "default"
    assert body["weak_quality_floor"] == pytest.approx(28.0)
