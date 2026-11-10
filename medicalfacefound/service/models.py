from __future__ import annotations

import importlib.util
import logging
import re
from threading import RLock

import numpy as np

from medicalfacefound.inference.predict import load_task, predict_values
from medicalfacefound.service.explain import ExplanationVariant
from medicalfacefound.service.heatmap_settings import PACKAGE_METHODS
from medicalfacefound.service.settings import Settings

logger = logging.getLogger(__name__)
TASK_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
INFERENCE_MODULES = ("torch", "torchvision", "timm", "einops", "safetensors")


class ModelStore:
    """Discover local tasks; load on first use and keep at most one model in memory."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._lock = RLock()
        self._loaded = None
        self._loaded_name: str | None = None
        self._errors: dict[str, str] = {}
        self.available: list[str] = []
        task_root = settings.weights_dir / "tasks"
        names = settings.tasks
        if not names and task_root.is_dir():
            names = tuple(p.name for p in sorted(task_root.iterdir()) if p.is_dir())
        for name in names:
            if not TASK_NAME.fullmatch(name):
                raise ValueError(f"Invalid task name: {name}")
            folder = task_root / name
            if all((folder / filename).is_file() for filename in ("config.json", "model.safetensors")):
                self.available.append(name)
            else:
                self._errors[name] = "缺少 config.json 或 model.safetensors"

    def status(self) -> dict:
        with self._lock:
            missing = [name for name in INFERENCE_MODULES if importlib.util.find_spec(name) is None]
            return {
                "available_models": list(self.available),
                "loaded_models": [self._loaded_name] if self._loaded_name else [],
                "load_errors": dict(self._errors),
                "missing_dependencies": missing,
                "inference_ready": bool(self.available) and not missing and not self._errors,
            }

    def predict(self, name: str, image: np.ndarray) -> dict:
        with self._lock:
            if name not in self.available:
                raise KeyError(f"未找到可用的本地模型: {name}")
            try:
                model, config = self._load(name)
                result = predict_values(model, config, [image], batch_size=1, device=self.settings.device)[0]
                self._errors.pop(name, None)
                return result
            except Exception as exc:
                self._errors[name] = "模型加载或推理失败，请检查依赖、权重和服务日志"
                logger.exception("MedicalFaceFound inference failed for %s", name)
                raise RuntimeError(self._errors[name]) from exc

    def explain(self, name: str, image: np.ndarray, *, variant: ExplanationVariant = "block") -> bytes:
        """Return a Grad-CAM overlay PNG for one model input image."""
        with self._lock:
            if name not in self.available:
                raise KeyError(f"未找到可用的本地模型: {name}")
            try:
                model, config = self._load(name)
                if variant in PACKAGE_METHODS:
                    from medicalfacefound.service.cam_comparison import age_cam_maps
                    from medicalfacefound.service.explain import cam_overlay_png

                    maps, _ = age_cam_maps(model, config, image, (variant,))
                    return cam_overlay_png(maps[variant], image)
                from medicalfacefound.service.explain import gradcam_png

                return gradcam_png(model, config, image, variant=variant)
            except Exception as exc:
                logger.exception("MedicalFaceFound Grad-CAM failed for %s", name)
                raise RuntimeError("热力图生成失败") from exc

    def _load(self, name):
        """Load under the store lock, releasing the previous model first."""
        if self._loaded_name != name:
            self._loaded = None
            self._loaded_name = None
            self._loaded = load_task(name, local_dir=self.settings.weights_dir, device=self.settings.device)
            self._loaded_name = name
        return self._loaded

    def compare_age_cams(self, image: np.ndarray, *, evaluate: bool = False) -> dict:
        from medicalfacefound.service.cam_comparison import compare_age_cams

        with self._lock:
            model, config = self._load("Age")
            return compare_age_cams(model, config, image, evaluate=evaluate)
