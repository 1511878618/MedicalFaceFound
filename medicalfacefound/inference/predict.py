"""Load released weights and run biomarker predictions."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

DEFAULT_REPO = "MedicalFaceFound/medicalfacefound"

# Release parts shipped side by side in the weights repository. ``tasks`` holds the original
# full models, ``tasks_binary`` the calibrated binary endpoints (head-only and full models mixed),
# ``tasks_part3`` the late regression models.
TASK_GROUPS = ("tasks", "tasks_binary", "tasks_part3")


def _task_folder(task: str, repo: str, local_dir: Path | None,
                 task_group: str = "tasks") -> Path:
    if local_dir is not None:
        folder = Path(local_dir) / task_group / task
        if not folder.is_dir():
            raise FileNotFoundError(f"{folder} does not exist")
        return folder

    from huggingface_hub import hf_hub_download

    # Resolve the config only; weight downloads are decided after the format is known.
    return Path(hf_hub_download(repo, f"{task_group}/{task}/config.json")).parent


def load_task(task: str, repo: str = DEFAULT_REPO, local_dir: str | Path | None = None,
              device: str = "cpu", half: bool = False, task_group: str = "tasks"):
    """Load one biomarker model from the Hugging Face weights repository.

    Args:
        task: folder name in the repository, e.g. ``"Age"``.
        repo: Hugging Face repository id.
        local_dir: optional path to a downloaded copy of the repository.
        device: ``"cpu"`` or ``"cuda"``.
        half: run original full models in fp16 on CUDA. MLP heads use CUDA
            autocast with fp32 parameters regardless of this flag.
        task_group: release part to load from: ``"tasks"`` (default, original full models),
            ``"tasks_binary"`` (calibrated endpoints) or ``"tasks_part3"``.

    Returns:
        ``(model, config)``
    """
    _validate_task_group(task_group)
    if not task or Path(task).name != task or task in (".", "..") or "\\" in task:
        raise ValueError("task must be a folder name, not a path")
    folder = _task_folder(task, repo, None if local_dir is None else Path(local_dir), task_group)
    cfg = json.loads((folder / "config.json").read_text(encoding="utf-8"))

    # One group can mix packed head-only heads and self-contained full models; the config decides.
    if cfg.get("format") == "head_only":
        from medicalfacefound.inference.head_only import load_mlp_task
        return load_mlp_task(task, repo, local_dir, device, task_group=task_group, cfg=cfg)

    from safetensors.torch import load_file

    from medicalfacefound.utils.models_swin import swin_large_512to256

    weights = folder / "model.safetensors"
    if not weights.is_file():
        from huggingface_hub import hf_hub_download
        weights = Path(hf_hub_download(repo, f"{task_group}/{task}/model.safetensors"))

    model = swin_large_512to256(num_classes=cfg["num_classes"])
    model.load_state_dict(load_file(str(weights)), strict=True)
    model.to(device).eval()
    if half and device == "cuda":
        model.half()
    return model, cfg


def predict_values(model, cfg: dict, images: list[np.ndarray], batch_size: int = 8,
                   device: str = "cpu", half: bool = False) -> list[dict]:
    """Run one model on a list of RGB uint8 crops and return values in clinical units."""
    import torch

    from medicalfacefound.inference.face import to_model_input

    if not images:
        return []
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    head_only = cfg.get("format") == "head_only"
    preprocess = to_model_input
    if head_only:
        from medicalfacefound.inference.head_only import prepare_input
        preprocess = prepare_input

    outputs = []
    with torch.inference_mode():
        for start in range(0, len(images), batch_size):
            batch = np.stack([preprocess(img) for img in images[start:start + batch_size]])
            x = torch.from_numpy(batch).to(device)
            if head_only:
                # Match feature extraction + head evaluation; retain fp32 parameters.
                with torch.autocast("cuda", dtype=torch.float16, enabled=str(device).startswith("cuda")):
                    outputs.append(model(x).float().cpu())
            else:
                if half and device == "cuda":
                    x = x.half()
                outputs.append(model(x).float().cpu())
    out = torch.cat(outputs).numpy()

    if cfg["task_type"] == "regression":
        values = out[:, 0] * cfg["target_std"] + cfg["target_mean"]
        return [{"task": cfg["task"], "value": float(v), "unit": cfg.get("unit")} for v in values]

    if head_only:
        # Softmax avoids cancellation for a rare class-0 event probability.
        probs = torch.softmax(torch.from_numpy(out), dim=1)[:, cfg["output_class_index"]].numpy()
    else:
        probs = 1.0 / (1.0 + np.exp(-(out[:, 1] - out[:, 0])))

    rows = [{"task": cfg["task"], "value": float(p), "unit": "prob"} for p in probs]

    # Optional calibrated decision layer: only for configs that carry calibration/stratification
    # blocks. ``value`` stays the model's own event probability so existing consumers are
    # unaffected; the calibrated score and tier are added beside it, per image.
    from medicalfacefound.inference.risk import (
        assign_tiers, calibrate_probabilities, has_calibration, has_stratification)

    if has_calibration(cfg):
        calibrated = np.asarray(calibrate_probabilities(probs, cfg), dtype=float)
        tiers = assign_tiers(calibrated, cfg) if has_stratification(cfg) else None
        for i, row in enumerate(rows):
            row["value_calibrated"] = float(calibrated[i])
            if tiers is not None:
                row["risk_tier"] = tiers[i]
    return rows


def _validate_task_group(task_group: str):
    if task_group not in TASK_GROUPS:
        raise ValueError(f"task_group must be one of {TASK_GROUPS}")


def load_tasks_index(repo: str = DEFAULT_REPO, local_dir: str | Path | None = None,
                     task_group: str = "tasks") -> dict:
    """Read the original index (default) or the separate downstream MLP index."""
    _validate_task_group(task_group)
    from medicalfacefound.inference.head_only import resolve_file
    relative = "tasks.json" if task_group == "tasks" else f"{task_group}/tasks.json"
    return json.loads(resolve_file(repo, local_dir, relative).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Locally trained checkpoints (external validation)
# --------------------------------------------------------------------------- #

SWIN_MODELS = ("swin_large_512to256", "swin_large_256", "swin_large_512", "swin_tiny_256")
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}


def _read_checkpoint(path: Path):
    """Return ``(state_dict, train_args, config)`` for .pth/.pt/.safetensors checkpoints.

    ``train_args`` is the ``argparse.Namespace`` stored by ``misc.save_model`` (``None`` for bare
    state_dicts and safetensors); ``config`` is a sibling ``config.json`` when present, which is
    how the released Hugging Face task folders describe their scaling and task.
    """
    import json

    import torch

    config = {}
    config_path = path.parent / "config.json"
    if config_path.is_file():
        config = json.loads(config_path.read_text(encoding="utf-8"))

    if path.suffix.lower() == ".safetensors":
        from safetensors.torch import load_file

        return load_file(str(path)), None, config

    checkpoint = torch.load(path, map_location="cpu", weights_only=False)
    if isinstance(checkpoint, dict) and isinstance(checkpoint.get("model"), dict):
        return checkpoint["model"], checkpoint.get("args"), config
    return checkpoint, None, config


def _stats_from_run_dir(checkpoint_path: Path):
    """Recover target_mean/target_std from ``<run_dir>/output_validation/epoch_0.csv``."""
    import re

    csv_path = checkpoint_path.parent / "output_validation" / "epoch_0.csv"
    if not csv_path.is_file():
        return None, None
    with csv_path.open(newline="", encoding="utf-8") as fh:
        header = fh.readline()
    match = re.search(r"std([0-9eE+\-.]+)_mean([0-9eE+\-.]+)", header)
    if match is None:
        return None, None
    return float(match.group(2)), float(match.group(1))  # mean, std


def load_checkpoint(path: str | Path, model_name: str | None = None, task: str | None = None,
                    task_type: str | None = None, nb_classes: int | None = None,
                    target_mean: float | None = None, target_std: float | None = None,
                    device: str = "cpu", half: bool = False):
    """Load a checkpoint written by ``main_finetune`` into ``(model, cfg)``.

    Accepts the ``misc.save_model`` layout (``{"model": state, "args": Namespace}``), a bare
    state_dict (as written by the early-stopping callback), and ``.safetensors``. Model
    architecture, task type and target scaling are recovered from the checkpoint ``args`` when
    present; the run directory's ``output_validation/epoch_0.csv`` is used as a fallback for the
    target mean/std, and explicit arguments win over both.
    """
    import torch

    from medicalfacefound.utils import models_swin

    path = Path(path)
    state, train_args, config = _read_checkpoint(path)
    finetune_args = config.get("finetune_args", {})
    state = {k[len("module."):] if k.startswith("module.") else k: v for k, v in state.items()}

    model_name = (model_name or getattr(train_args, "model", None)
                  or finetune_args.get("model") or "swin_large_512to256")
    if model_name not in SWIN_MODELS:
        raise ValueError(f"unsupported model {model_name!r}; available: {SWIN_MODELS}")

    task_type = (task_type or getattr(train_args, "type", None)
                 or config.get("task_type") or "regression")
    if task_type not in ("regression", "classification"):
        raise ValueError(f"unsupported task type {task_type!r}")

    if nb_classes is None:
        nb_classes = getattr(train_args, "nb_classes", None) or config.get("num_classes")
    if nb_classes is None and task_type == "regression":
        nb_classes = 1
    if nb_classes is None:
        nb_classes = int(state["head.weight"].shape[0])
    if task_type == "classification" and nb_classes != 2:
        raise NotImplementedError(
            f"predictions are defined for binary classification, got nb_classes={nb_classes}")

    if target_mean is None:
        target_mean = getattr(train_args, "target_mean", None)
        if target_mean is None:
            target_mean = config.get("target_mean")
    if target_std is None:
        target_std = getattr(train_args, "target_std", None)
        if target_std is None:
            target_std = config.get("target_std")
    if target_mean is None or target_std is None:
        run_mean, run_std = _stats_from_run_dir(path)
        target_mean = run_mean if target_mean is None else target_mean
        target_std = run_std if target_std is None else target_std
    if task_type == "regression" and (target_mean is None or target_std is None):
        raise ValueError(
            f"target_mean/target_std not found for {path}; pass --target-mean/--target-std "
            f"or point --checkpoint at a checkpoint saved by a training run")

    model = getattr(models_swin, model_name)(num_classes=nb_classes)
    model.load_state_dict(state, strict=True)
    model.to(device).eval()
    if half and str(device).startswith("cuda"):
        model.half()

    cfg = {
        "task": (task or getattr(train_args, "label", None)
                 or config.get("task") or path.parent.name),
        "task_type": task_type,
        "num_classes": int(nb_classes),
        "target_mean": 0.0 if target_mean is None else float(target_mean),
        "target_std": 1.0 if target_std is None else float(target_std),
        "unit": config.get("unit"),
    }
    return model, cfg


def collect_images(inputs: list[str | Path]) -> list[tuple[str, Path]]:
    """Expand files/directories into ``(eid, path)`` pairs.

    ``eid`` is the parent folder name for ``root/<eid>/photo.jpg`` layouts and the file stem
    for images that sit directly in the given directory.
    """
    items: list[tuple[str, Path]] = []
    for item in inputs:
        root = Path(item)
        if root.is_dir():
            for path in sorted(p for p in root.rglob("*") if p.suffix.lower() in IMAGE_SUFFIXES):
                items.append((path.stem if path.parent == root else path.parent.name, path))
        elif root.exists():
            items.append((root.stem, root))
        else:
            raise FileNotFoundError(root)
    if not items:
        raise FileNotFoundError(f"no images found under {[str(i) for i in inputs]}")
    return items


def predict_folder(model, cfg: dict, inputs: list[str | Path], out: str | Path = "predictions.csv",
                   batch_size: int = 8, device: str = "cpu", half: bool = False,
                   crop: bool = False, size: int = 256, ratio: float = 1.2,
                   with_normed: bool = False, limit: int | None = None, log=print) -> dict:
    """Batch predict every image under ``inputs`` and write ``eid,path,value[,value_normed]``.

    By default the images are expected to be 256 x 256 face crops; pass ``crop=True`` to run
    RetinaFace detection and cropping on raw photographs. Rows are written and flushed batch by
    batch, so a long external-validation run keeps partial results; images without a detected
    face are counted as skipped.
    """
    import csv

    from medicalfacefound.inference.face import FaceCropper, load_image

    items = collect_images(inputs)
    if limit is not None:
        items = items[:limit]
    cropper = FaceCropper(size=size, ratio=ratio) if crop else None

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    keep_normed = with_normed and cfg["task_type"] == "regression"
    fieldnames = ["eid", "path", "value"] + (["value_normed"] if keep_normed else [])
    written = skipped = 0
    buffer: list[tuple[str, Path, np.ndarray]] = []

    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()

        def flush() -> None:
            nonlocal written
            if not buffer:
                return
            preds = predict_values(model, cfg, [crop_img for _, _, crop_img in buffer],
                                   batch_size=batch_size, device=device, half=half)
            for (eid, path, _), pred in zip(buffer, preds):
                row = {"eid": eid, "path": str(path), "value": pred["value"]}
                if keep_normed:
                    row["value_normed"] = (pred["value"] - cfg["target_mean"]) / cfg["target_std"]
                writer.writerow(row)
            written += len(preds)
            buffer.clear()
            fh.flush()

        for index, (eid, path) in enumerate(items, 1):
            crop_img = cropper.crop_path(path) if cropper is not None else load_image(path)
            if crop_img is None:
                skipped += 1
                log(f"  no face: {path}")
                continue
            if crop_img.shape[:2] != (size, size):
                raise ValueError(
                    f"{path} is {crop_img.shape[1]}x{crop_img.shape[0]}, expected "
                    f"{size}x{size}; pass --crop to detect faces or provide {size}x{size} crops")
            buffer.append((eid, path, crop_img))
            if len(buffer) >= batch_size:
                flush()
            if index % 200 == 0:
                log(f"  {index}/{len(items)} images, {written} prediction(s)")

        flush()

    return {"images": len(items), "written": written, "skipped": skipped, "out": out}
