from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


PACKAGE_ROOT = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="COMFYUI_API_",
        env_file=".env",
        extra="ignore",
    )

    api_host: str = "0.0.0.0"
    api_port: int = 8888
    api_key: str | None = None

    comfyui_base_url: str = "http://127.0.0.1:8188"
    comfyui_output_dir: Path | None = None
    delete_generated_files: bool = True

    max_pending_jobs: int = 5
    default_workflow_id: str = "flux-dev-simple"
    # If None, keep the checkpoint embedded in the workflow JSON.
    default_checkpoint_name: str | None = None

    wait_timeout_seconds: int = 900
    poll_interval_seconds: float = 0.5

    cassette_dir: Path = PACKAGE_ROOT / "Cassettes"
    cassette_schema_path: Path = PACKAGE_ROOT / "Schemas" / "cassette.schema.json"

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
