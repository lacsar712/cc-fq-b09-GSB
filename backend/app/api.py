from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.auth import authenticate_user, create_access_token, get_current_user, require_bioops
from app.config import settings
from app.database import SessionLocal, get_db
from app.models import AppSetting, Job, JobStage, Sample
from app.pipeline.actors import compute_weak_positions
from app.pipeline.runner import create_job_stages, run_pipeline_sync
from app.schemas import (
    HealthOut,
    JobCreate,
    JobListItem,
    JobOut,
    LoginRequest,
    SampleOut,
    StageOut,
    TokenResponse,
    WeakThresholdConfigOut,
    WeakThresholdUpdate,
)
from app.settings_store import WEAK_THRESHOLD_KEY, get_weak_threshold, set_weak_threshold


router = APIRouter(prefix="/api")


def _run_job_background(job_id: int) -> None:
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            run_pipeline_sync(db, job)
    finally:
        db.close()


@router.get("/health", response_model=HealthOut)
def health():
    return HealthOut(status="ok", service="fastq-qc-pipeline")


@router.post("/auth/login", response_model=TokenResponse)
def login(body: LoginRequest):
    user = authenticate_user(body.username.strip(), body.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    token = create_access_token(user["username"], user["role"])
    return TokenResponse(
        access_token=token,
        username=user["username"],
        role=user["role"],
    )


@router.get("/samples", response_model=list[SampleOut])
def list_samples(_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(Sample).order_by(Sample.id).all()


@router.post("/jobs", response_model=JobOut, status_code=status.HTTP_201_CREATED)
def create_job(
    body: JobCreate,
    background: BackgroundTasks,
    user: dict = Depends(require_bioops),
    db: Session = Depends(get_db),
):
    sample_id = body.sampleId
    fastq_text = (body.fastqText or "").strip() if body.fastqText else ""
    sample_name = "自定义输入"
    sample = None

    if sample_id is not None:
        sample = db.query(Sample).filter(Sample.id == sample_id).first()
        if not sample:
            raise HTTPException(status_code=404, detail="样例不存在")
        fastq_text = sample.fastq_content
        sample_name = sample.name
    elif not fastq_text:
        raise HTTPException(status_code=400, detail="请提供 sampleId 或 fastqText")

    job = Job(
        sample_id=sample.id if sample else None,
        sample_name=sample_name,
        status="pending",
        created_by=user["username"],
        fastq_snapshot=fastq_text,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    create_job_stages(db, job.id)
    background.add_task(_run_job_background, job.id)

    job = (
        db.query(Job)
        .options(joinedload(Job.stages))
        .filter(Job.id == job.id)
        .first()
    )
    return job


@router.get("/jobs", response_model=list[JobListItem])
def list_jobs(_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(Job).order_by(Job.id.desc()).all()


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: int, _user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    job = (
        db.query(Job)
        .options(joinedload(Job.stages))
        .filter(Job.id == job_id)
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="作业不存在")
    return job


@router.get("/jobs/{job_id}/stages", response_model=list[StageOut])
def get_job_stages(
    job_id: int, _user: dict = Depends(get_current_user), db: Session = Depends(get_db)
):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="作业不存在")
    return (
        db.query(JobStage)
        .filter(JobStage.job_id == job_id)
        .order_by(JobStage.stage_order)
        .all()
    )


def _weak_config_out(db: Session) -> WeakThresholdConfigOut:
    row = db.get(AppSetting, WEAK_THRESHOLD_KEY)
    return WeakThresholdConfigOut(
        threshold=get_weak_threshold(db),
        default=settings.weak_quality_threshold,
        updated_by=row.updated_by if row else None,
        updated_at=row.updated_at if row else None,
    )


@router.get("/config/weak-threshold", response_model=WeakThresholdConfigOut)
def read_weak_threshold(
    _user: dict = Depends(get_current_user), db: Session = Depends(get_db)
):
    """当前弱位点阈值（所有登录用户可读，含审计员）。"""
    return _weak_config_out(db)


@router.put("/config/weak-threshold", response_model=WeakThresholdConfigOut)
def update_weak_threshold(
    body: WeakThresholdUpdate,
    user: dict = Depends(require_bioops),
    db: Session = Depends(get_db),
):
    """运维调整弱位点平均质量下限；审计员调用返回 403。"""
    set_weak_threshold(db, body.threshold, user["username"])
    return _weak_config_out(db)


@router.post("/jobs/{job_id}/recompute-weak", response_model=JobOut)
def recompute_weak_positions(
    job_id: int,
    _user: dict = Depends(require_bioops),
    db: Session = Depends(get_db),
):
    """按当前阈值对已成功作业重算弱位点清单（服务端计算，写回 metrics）。"""
    job = (
        db.query(Job)
        .options(joinedload(Job.stages))
        .filter(Job.id == job_id)
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="作业不存在")
    if job.status != "success":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="仅成功完成的作业可重算弱位点",
        )
    metrics = dict(job.metrics or {})
    per_position = metrics.get("per_position")
    if not per_position:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该作业无 per_position 数据，无法重算弱位点",
        )

    threshold = get_weak_threshold(db)
    weak = compute_weak_positions(per_position, threshold)
    metrics["weak_positions"] = weak
    metrics["weak_threshold"] = threshold
    if isinstance(metrics.get("report"), dict):
        metrics["report"] = {
            **metrics["report"],
            "weak_threshold": threshold,
            "weak_count": len(weak),
        }
    if isinstance(metrics.get("summary"), dict):
        metrics["summary"] = {**metrics["summary"], "weak_count": len(weak)}

    job.metrics = metrics
    db.commit()
    db.refresh(job)
    return job
