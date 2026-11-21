from functools import lru_cache
from typing import Literal

from fastapi import Request
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    mongodb_uri: str = "mongodb://localhost:27017/"
    mongodb_database: str = "health_db"
    frontend_base_url: str = "http://localhost:5173"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    jwt_secret_key: str = ""
    jwt_access_token_minutes: int = Field(default=60, gt=0, le=1440)
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:3b"
    ollama_translation_model: str = "translategemma:4b"
    ollama_timeout_seconds: float = Field(default=60, gt=0, le=300)
    whisper_model: str = "tiny"
    bhashini_api_url: str = ""
    bhashini_user_id: str = ""
    bhashini_api_key: str = ""
    bhashini_pipeline_id: str = ""
    google_translate_api_key: str = ""
    translation_timeout_seconds: float = Field(default=20, gt=0, le=120)
    password_reset_mode: Literal["disabled", "development"] = "disabled"
    password_reset_otp_minutes: int = Field(default=5, gt=0, le=15)
    password_reset_max_attempts: int = Field(default=5, gt=0, le=10)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_request_settings(request: Request) -> Settings:
    return request.app.state.settings
