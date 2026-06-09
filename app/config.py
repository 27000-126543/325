from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    APP_NAME: str = "智慧流域水资源综合调度与生态保障系统"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True

    DATABASE_URL: str = "sqlite:///./smart_basin.db"
    SECRET_KEY: str = "smart-basin-secret-key-2024"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    ECOLOGICAL_FLOW_THRESHOLD: float = 0.3
    WATER_QUALITY_COD_LIMIT: float = 40.0
    WATER_QUALITY_NH3N_LIMIT: float = 2.0

    class Config:
        env_file = ".env"


settings = Settings()
