from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import tomllib


@lru_cache(maxsize=1)
def get_version() -> str:
    try:
        return version("comfyui_api")
    except PackageNotFoundError:
        pyproject_path = Path(__file__).resolve().parents[2] / "pyproject.toml"
        with pyproject_path.open("rb") as f:
            return tomllib.load(f)["project"]["version"]


__version__ = get_version()
