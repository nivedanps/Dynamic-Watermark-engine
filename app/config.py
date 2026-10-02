import os
from pathlib import Path
from pydantic import BaseModel, Field

class Settings(BaseModel):
    JWT_SECRET_KEY: str = Field(
        default_factory=lambda: os.getenv(
            "JWT_SECRET_KEY",
            "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7"
        )
    )
    JWT_ALGORITHM: str = Field(
        default_factory=lambda: os.getenv("JWT_ALGORITHM", "HS256")
    )
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default_factory=lambda: int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
    )
    INPUT_DIR: Path = Field(
        default_factory=lambda: Path(
            os.getenv("INPUT_DIR", str(Path(__file__).resolve().parent.parent / "input"))
        ).resolve()
    )
    STATIC_DIR: Path = Field(
        default_factory=lambda: Path(
            os.getenv("STATIC_DIR", str(Path(__file__).resolve().parent.parent / "static"))
        ).resolve()
    )
    WATERMARK_OPACITY: float = Field(
        default_factory=lambda: float(os.getenv("WATERMARK_OPACITY", "0.20"))
    )
    MAX_UPLOAD_SIZE_MB: int = Field(
        default_factory=lambda: int(os.getenv("MAX_UPLOAD_SIZE_MB", "20"))
    )

settings = Settings()
