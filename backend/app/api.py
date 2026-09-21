from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.auth import authenticate_user, create_access_token, get_current_user, require_bioops
from app.database import SessionLocal, get_db
from app.models import AppSetting, Job, JobStage, Sample
from app.pipeline.runner import create_job_stages, recompute_weak_positions, run_pipeline_sync
from app.schemas import (
    HealthOut,
    JobCreate,
    JobListItem,
    JobOut,
    LoginRequest,
    QualityConfigOut,
    QualityConfigUpdate,
    SampleOut,
    StageOut,
    TokenResponse,
)
from app.settings_service import (
    WEAK_FLOOR_KEY,
    get_weak_quality_floor,
    set_weak_quality_floor,
)


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


@router.post("/jobs/{job_id}/recompute-weak", response_model=JobOut)
def recompute_job_weak(
    job_id: int,
    user: dict = Depends(require_bioops),
    db: Session = Depends(get_db),
):
    """对已成功作业按当前阈值重算 weak_positions（不重跑流水线）。仅运维。"""
    job = (
        db.query(Job)
        .options(joinedload(Job.stages))
        .filter(Job.id == job_id)
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="作业不存在")
    if job.status != "success":
        if job.status == "failed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="作业失败，无 per_position 数据，无法重算弱位点清单",
            )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="仅成功作业可重算弱位点清单")
    try:
        recompute_weak_positions(db, job)
    except LookupError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return job


@router.get("/quality-config", response_model=QualityConfigOut)
def get_quality_config(_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    has_override = (
        db.query(AppSetting).filter(AppSetting.key == WEAK_FLOOR_KEY).first() is not None
    )
    return QualityConfigOut(
        weak_quality_floor=get_weak_quality_floor(db),
        source="db" if has_override else "default",
    )


@router.put("/quality-config", response_model=QualityConfigOut)
def update_quality_config(
    body: QualityConfigUpdate,
    user: dict = Depends(require_bioops),
    db: Session = Depends(get_db),
):
    """修改弱位点平均质量下限（仅运维；审计员只读，调用返回 403）。"""
    try:
        value = set_weak_quality_floor(db, body.weak_quality_floor)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if body.apply_to_successful_jobs:
        for job in db.query(Job).filter(Job.status == "success").all():
            try:
                recompute_weak_positions(db, job, value)
            except LookupError:
                # 历史成功作业理论上都有 per_position；缺失则跳过，不阻断配置更新
                continue
    return QualityConfigOut(weak_quality_floor=value, source="db")
