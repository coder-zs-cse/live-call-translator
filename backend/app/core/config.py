"""Application configuration.

One file per environment — `.env.local` and `.env.prod` — never a single `.env`
with overrides layered on top. `APP_ENV` picks the file and defaults to `local`,
so pointing the app at production config is always a deliberate act.

Settings are grouped into nested models; environment variables use a double
underscore to cross the boundary, e.g. `SARVAM__API_KEY`.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.enums import AppEnv, Language, OutputScript, PipelineMode

BACKEND_ROOT = Path(__file__).resolve().parents[2]

#: Read directly from the process environment rather than from a settings object,
#: because it is what decides which settings file to read in the first place.
CURRENT_ENV = AppEnv(os.getenv("APP_ENV", AppEnv.LOCAL))
ENV_FILE = BACKEND_ROOT / f".env.{CURRENT_ENV.value}"


class SarvamSettings(BaseModel):
    api_key: SecretStr
    base_url: str = "https://api.sarvam.ai"
    translate_model: str = "mayura:v1"
    stt_model: str = "saaras:v3-realtime"
    tts_model: str = "bulbul:v3"
    #: Native script, because the output is fed to TTS rather than shown to a human.
    output_script: OutputScript = OutputScript.FULLY_NATIVE
    #: mayura:v1 rejects longer input; the utterance assembler splits on this.
    max_input_chars: int = 1000
    request_timeout_seconds: float = 10.0


class VobizSettings(BaseModel):
    auth_id: str
    auth_token: SecretStr
    phone_number: str
    base_url: str = "https://api.vobiz.ai"
    #: Public origin Vobiz reaches this app on. Locally this is a tunnel URL.
    public_base_url: str

    @property
    def answer_url(self) -> str:
        return f"{self.public_base_url}/api/v1/xml/answer"

    @property
    def hangup_url(self) -> str:
        return f"{self.public_base_url}/api/v1/xml/hangup"

    @property
    def stream_url(self) -> str:
        origin = self.public_base_url.replace("https://", "wss://").replace("http://", "ws://")
        return f"{origin}/api/v1/ws/media"


class DatabaseSettings(BaseModel):
    url: str
    echo: bool = False
    pool_size: int = 10


class RedisSettings(BaseModel):
    url: str
    #: Room codes are short-lived by design; an abandoned room must not linger.
    room_ttl_seconds: int = 600


class AdminSettings(BaseModel):
    bypass_token: SecretStr


class CallSettings(BaseModel):
    """Defaults applied to a caller we have never seen before."""

    default_primary_language: Language = Language.ENGLISH
    default_secondary_language: Language = Language.ENGLISH
    room_code_min: int = 1000
    room_code_max: int = 9999
    room_code_allocation_attempts: int = 10


class PipelineSettings(BaseModel):
    """Phase 2 test-call behaviour.

    Disappears in Phase 4, when the room a caller joins decides the languages
    instead of a config file.
    """

    mode: PipelineMode = PipelineMode.TRANSLATE_LOOPBACK
    #: For TRANSLATE_LOOPBACK: speak this, hear it back as the target.
    loopback_source_language: Language = Language.HINDI
    loopback_target_language: Language = Language.TAMIL
    #: Silence before an utterance is considered finished. The single biggest
    #: latency lever in the whole system - see docs/PLAN.md section 7.1.
    vad_stop_seconds: float = 0.7


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    app_env: AppEnv = CURRENT_ENV
    log_level: str = "INFO"

    sarvam: SarvamSettings
    vobiz: VobizSettings
    database: DatabaseSettings
    redis: RedisSettings
    admin: AdminSettings
    call: CallSettings = Field(default_factory=CallSettings)
    pipeline: PipelineSettings = Field(default_factory=PipelineSettings)

    @property
    def is_production(self) -> bool:
        return self.app_env is AppEnv.PROD


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached accessor. Injected via `app.dependencies`, not imported ad hoc."""
    return Settings()
