"""Environment configuration without side effects or secret logging."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_PATH = REPOSITORY_ROOT / ".env"


def load_local_env(path: str | Path = DEFAULT_ENV_PATH) -> Path:
    """Load a small dotenv file without overriding an existing process environment."""
    env_path = Path(path).expanduser().resolve()
    if not env_path.is_file():
        return env_path
    for line_number, raw_line in enumerate(
        env_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Invalid .env entry at line {line_number}: expected NAME=value")
        name, value = line.split("=", 1)
        name = name.strip()
        if not name or not name.replace("_", "").isalnum():
            raise ValueError(f"Invalid .env variable name at line {line_number}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(name, value)
    return env_path


class Settings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sure_for_sure_dataset: Path | None = None
    sure_for_sure_provider: str = "stub"
    anthropic_api_key: str | None = None
    sure_for_sure_anthropic_model: str | None = None

    @classmethod
    def from_environment(cls) -> Settings:
        dataset = os.getenv("SURE_FOR_SURE_DATASET")
        return cls(
            sure_for_sure_dataset=Path(dataset).expanduser() if dataset else None,
            sure_for_sure_provider=os.getenv("SURE_FOR_SURE_PROVIDER", "stub"),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
            sure_for_sure_anthropic_model=os.getenv("SURE_FOR_SURE_ANTHROPIC_MODEL"),
        )
