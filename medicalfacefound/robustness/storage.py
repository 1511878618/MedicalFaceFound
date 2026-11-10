from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path


def digest_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(4*1024*1024), b""):
            h.update(block)
    return h.hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".{os.getpid()}.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temp.replace(path)


def write_csv(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(k for row in rows for k in row))
    temp = path.with_name(path.name + f".{os.getpid()}.tmp")
    with temp.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    temp.replace(path)


def discover_models(weights, requested=None):
    tasks = Path(weights) / "tasks"
    if not tasks.is_dir():
        raise FileNotFoundError(tasks)
    models, issues = [], []
    names = requested or [p.name for p in sorted(tasks.iterdir()) if p.is_dir()]
    for name in names:
        if Path(name).name != name or name in {".", ".."}:
            raise ValueError(f"Invalid model name: {name}")
        folder = tasks / name
        try:
            cfg = json.loads((folder / "config.json").read_text())
            if not (folder / "model.safetensors").is_file():
                raise ValueError("missing model.safetensors")
            if cfg.get("task") != name or cfg.get("img_size", 256) != 256:
                raise ValueError("task name or image size incompatible with package inference")
            kind = cfg.get("task_type")
            if kind == "regression":
                if cfg.get("num_classes") != 1:
                    raise ValueError("only scalar regression is supported by predict_values")
                import math
                if not all(math.isfinite(float(cfg[k])) for k in ("target_mean", "target_std")) or cfg["target_std"] <= 0:
                    raise ValueError("invalid regression target statistics")
            elif kind == "classification":
                if cfg.get("num_classes") != 2:
                    raise ValueError("only binary classification is supported by predict_values")
            else:
                raise ValueError(f"unsupported task_type: {kind}")
            models.append({"task": name, "config": cfg})
        except (ValueError, KeyError, OSError, TypeError) as exc:
            issues.append({"task": name, "error": str(exc)})
    return models, issues
