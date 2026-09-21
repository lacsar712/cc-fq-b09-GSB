from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False)

    database_url: str = "postgresql+psycopg2://fastq:fastq@localhost:54384/fastq_qc"
    jwt_secret: str = "fastq-qc-pipeline-dev-secret"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 480
    # 弱位点判定下限：位点平均质量严格低于该值即计入 weak_positions（运维可在运行时改）
    weak_quality_floor: float = 28.0


settings = Settings()
