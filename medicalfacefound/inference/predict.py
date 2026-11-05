"""Load released weights and run biomarker predictions."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

DEFAULT_REPO = "MedicalFaceFound/medicalfacefound"


def _task_folder(task: str, repo: str, local_dir: Path | None) -> Path:
    if local_dir is not None:
        folder = Path(local_dir) / "tasks" / task
        if not folder.is_dir():
            raise FileNotFoundError(f"{folder} does not exist")
        return folder

    from huggingface_hub import hf_hub_download

    hf_hub_download(repo, f"tasks/{task}/config.json")
    weights = hf_hub_download(repo, f"tasks/{task}/model.safetensors")
    return Path(weights).parent


def load_task(task: str, repo: str = DEFAULT_REPO, local_dir: str | Path | None = None,
              device: str = "cpu", half: bool = False):
    """Load one biomarker model from the Hugging Face weights repository.

    Args:
        task: folder name in the repository, e.g. ``"Age"``.
        repo: Hugging Face repository id.
        local_dir: optional path to a downloaded copy of the repository.
        device: ``"cpu"`` or ``"cuda"``.
        half: run in fp16 on CUDA.

    Returns:
        ``(model, config)``
    """
    from safetensors.torch import load_file

    from medicalfacefound.utils.models_swin import swin_large_512to256

    folder = _task_folder(task, repo, None if local_dir is None else Path(local_dir))
    cfg = json.loads((folder / "config.json").read_text(encoding="utf-8"))

    model = swin_large_512to256(num_classes=cfg["num_classes"])
    model.load_state_dict(load_file(str(folder / "model.safetensors")), strict=True)
    model.to(device).eval()
    if half and device == "cuda":
        model.half()
    return model, cfg


def predict_values(model, cfg: dict, images: list[np.ndarray], batch_size: int = 8,
                   device: str = "cpu", half: bool = False) -> list[dict]:
    """Run one model on a list of RGB uint8 crops and return values in clinical units."""
    import torch

    from medicalfacefound.inference.face import to_model_input

    outputs = []
    with torch.inference_mode():
        for start in range(0, len(images), batch_size):
            batch = np.stack([to_model_input(img) for img in images[start:start + batch_size]])
            x = torch.from_numpy(batch).to(device)
            if half and device == "cuda":
                x = x.half()
            outputs.append(model(x).float().cpu())
    out = torch.cat(outputs).numpy()

    if cfg["task_type"] == "regression":
        values = out[:, 0] * cfg["target_std"] + cfg["target_mean"]
        return [{"task": cfg["task"], "value": float(v), "unit": cfg.get("unit")} for v in values]

    probs = 1.0 / (1.0 + np.exp(-(out[:, 1] - out[:, 0])))
    return [{"task": cfg["task"], "value": float(p), "unit": "prob"} for p in probs]


def load_tasks_index(repo: str = DEFAULT_REPO, local_dir: str | Path | None = None) -> dict:
    """Read ``tasks.json`` from the weights repository."""
    if local_dir is not None:
        return json.loads((Path(local_dir) / "tasks.json").read_text(encoding="utf-8"))
    from huggingface_hub import hf_hub_download

    return json.loads(Path(hf_hub_download(repo, "tasks.json")).read_text(encoding="utf-8"))
