from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", protected_namespaces=("settings_",))

    app_name: str = "Vogi"
    host: str = "127.0.0.1"
    port: int = 3000
    root_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parents[1])
    model_provider: str = Field(default="ollama", validation_alias="VOGI_MODEL_PROVIDER")
    ollama_url: str = Field(default="http://127.0.0.1:11434", validation_alias="OLLAMA_URL")
    openai_api_base: str = Field(default="https://api.openai.com/v1", validation_alias="OPENAI_API_BASE")
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    agent_model: str = Field(default="gemma3:1b", validation_alias="VOGI_AGENT_MODEL")
    gpu_layers: int = Field(default=8, validation_alias="OLLAMA_NUM_GPU")
    max_agent_steps: int = Field(default=50, validation_alias="GEMMA_AGENT_MAX_STEPS")
    edge_channel: str = Field(default="msedge", validation_alias="VOGI_EDGE_CHANNEL")
    edge_profile: str = Field(default="Default", validation_alias="VOGI_EDGE_PROFILE")
    edge_user_data_dir: Path = Field(
        default_factory=lambda: Path.home() / "AppData" / "Local" / "Microsoft" / "Edge" / "User Data",
        validation_alias="VOGI_EDGE_USER_DATA_DIR",
    )
    tesseract_path: Path = Field(
        default_factory=lambda: Path("C:/Program Files/Tesseract-OCR/tesseract.exe"),
        validation_alias="VOGI_TESSERACT_PATH",
    )
    database_url: str = "postgresql+psycopg://postgres:password@localhost:5432/create_new_db"

    @property
    def public_dir(self) -> Path:
        return self.root_dir / "Frontend"

    @property
    def reports_dir(self) -> Path:
        return self.root_dir / "reports"

    @property
    def projects_dir(self) -> Path:
        return self.root_dir / "projects"

    @property
    def tools_dir(self) -> Path:
        return self.root_dir / ".gemma-tools"

    @property
    def schemas_dir(self) -> Path:
        return self.tools_dir / "schemas"

    @property
    def state_dir(self) -> Path:
        return self.root_dir / ".vogi-state"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.root_dir = settings.root_dir.resolve()
    settings.ollama_url = settings.ollama_url.rstrip("/")
    return settings
