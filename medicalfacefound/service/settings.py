from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    weights_dir: Path
    database_path: Path
    frontend_dir: Path | None = None
    tasks: tuple[str, ...] = ()
    device: str = "cpu"
    admin_token: str = ""
    fahr_faceage_checkpoint: Path | None = None
    fahr_faceage_source: Path | None = None
    fahr_faceage_python: Path | None = None
    cam_comparison_enabled: bool = False

    @classmethod
    def from_environment(cls) -> Settings:
        root = Path(__file__).resolve().parents[2]
        frontend = os.getenv("MFF_FRONTEND_DIR")
        default_frontend = Path(__file__).resolve().parent / "static"
        frontend_dir = Path(frontend).expanduser().resolve() if frontend else (default_frontend if default_frontend.is_dir() else None)
        def optional_path(name):
            value = os.getenv(name)
            return Path(value).expanduser().resolve() if value else None

        return cls(
            weights_dir=Path(os.getenv("MFF_WEIGHTS_DIR", str(root / "weights"))).expanduser().resolve(),
            database_path=Path(os.getenv("MEDICALFACE_DB_PATH", str(root / "data" / "medicalface.sqlite3"))).expanduser().resolve(),
            frontend_dir=frontend_dir,
            tasks=tuple(dict.fromkeys(t.strip() for t in os.getenv("MFF_TASKS", "").split(",") if t.strip())),
            device=os.getenv("MFF_DEVICE", "cpu"),
            admin_token=os.getenv("MFF_ADMIN_TOKEN", ""),
            fahr_faceage_checkpoint=optional_path("MFF_FAHR_FACEAGE_CHECKPOINT"),
            fahr_faceage_source=optional_path("MFF_FAHR_FACEAGE_SOURCE"),
            fahr_faceage_python=optional_path("MFF_FAHR_FACEAGE_PYTHON"),
            cam_comparison_enabled=os.getenv("MFF_ENABLE_CAM_COMPARISON") == "1",
        )
