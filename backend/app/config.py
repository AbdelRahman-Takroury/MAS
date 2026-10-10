from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    groq_api_key: str | None = None
    groq_model: str = "openai/gpt-oss-20b"
    azure_speech_key: str | None = None
    azure_speech_region: str | None = None
    cors_origins: str = "http://localhost:5173"
    weather_snapshot_path: str = "/app/data/sample_weather.json"  # Legacy direct-service callers only.
    weather_cache_dir: str = "data/weather-cache"
    demo_user_id: str = "demo_user_001"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def allowed_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
