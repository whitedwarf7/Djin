from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent

REDDIT_REDIRECT_PORT = 8912
REDDIT_REDIRECT_URI = f"http://localhost:{REDDIT_REDIRECT_PORT}/reddit/callback"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_prefix="DJIN_",
        extra="ignore",
    )

    llm_provider: Literal["openai", "openrouter"] = "openrouter"
    openai_api_key: str = ""
    openrouter_api_key: str = ""
    llm_model: str = "openai/gpt-4o-mini"
    llm_timeout: float = 120.0
    max_tool_iterations: int = 8

    google_client_id: str = ""
    google_client_secret: str = ""

    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "windows:djin-assistant:0.1.0 (personal use)"

    search_provider: Literal["brave", "tavily", "none"] = "none"
    brave_api_key: str = ""
    tavily_api_key: str = ""

    voice_enabled: bool = True
    # "browser" uses the Web Speech API in the page; "openai" posts audio to voice_base_url.
    stt_provider: Literal["browser", "openai"] = "browser"
    tts_provider: Literal["browser", "openai"] = "browser"
    voice_base_url: str = "https://api.openai.com/v1"
    voice_api_key: str = ""
    stt_model: str = "whisper-1"
    tts_model: str = "gpt-4o-mini-tts"
    tts_voice: str = "alloy"
    voice_language: str = "en-US"
    voice_timeout: float = 60.0
    max_audio_bytes: int = 15_000_000

    data_dir: Path = PROJECT_ROOT / "data"
    notes_dir: Path = PROJECT_ROOT / "data" / "notes"
    encryption_key: str = ""

    auto_approve_write: bool = True

    host: str = "127.0.0.1"
    port: int = 8765

    @field_validator("data_dir", "notes_dir")
    @classmethod
    def _absolute(cls, value: Path) -> Path:
        return value if value.is_absolute() else (PROJECT_ROOT / value).resolve()

    @property
    def db_path(self) -> Path:
        return self.data_dir / "djin.sqlite3"

    @property
    def llm_base_url(self) -> str:
        if self.llm_provider == "openai":
            return "https://api.openai.com/v1"
        return "https://openrouter.ai/api/v1"

    @property
    def llm_api_key(self) -> str:
        return self.openai_api_key if self.llm_provider == "openai" else self.openrouter_api_key

    @property
    def google_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def reddit_configured(self) -> bool:
        return bool(self.reddit_client_id and self.reddit_client_secret)

    @property
    def search_configured(self) -> bool:
        if self.search_provider == "brave":
            return bool(self.brave_api_key)
        if self.search_provider == "tavily":
            return bool(self.tavily_api_key)
        return False

    @property
    def voice_key(self) -> str:
        return self.voice_api_key or self.openai_api_key

    @property
    def server_stt_ready(self) -> bool:
        return self.stt_provider == "openai" and bool(self.voice_key)

    @property
    def server_tts_ready(self) -> bool:
        return self.tts_provider == "openai" and bool(self.voice_key)

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.notes_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
