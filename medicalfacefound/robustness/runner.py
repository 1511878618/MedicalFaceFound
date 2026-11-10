from __future__ import annotations

import gc
import importlib.metadata
import json
import os
import platform
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .datasets import build_pairs, inventory, subset_pairs
from .storage import digest_file, discover_models, fingerprint, write_csv, write_json


def version_info():
    versions = {"python": platform.python_version()}
    # Module versions reflect imported conda packages even if stale pip metadata exists.
    import torch, torchvision, timm, scipy, PIL, retinaface
    for module in (np, torch, torchvision, timm, scipy, PIL, retinaface):
        versions[module.__name__] = module.__version__
    return versions


def source_fingerprint():
    root = Path(__file__).resolve().parents[1]
    sources = [p for folder in ("robustness", "inference", "utils") for p in (root/folder).glob("*.py")]
    return fingerprint({str(p.relative_to(root)): digest_file(p) for p in sorted(sources)})


def audit(args):
    mapping = json.loads(args.fei_mapping.read_text()) if args.fei_mapping else None
    all_pairs, issues = build_pairs(args.data_root, args.protocol, mapping)
    if args.dataset:
        all_pairs = [p for p in all_pairs if p["dataset"] in args.dataset]
        issues = [p for p in issues if p["dataset"] in args.dataset]
    pairs = subset_pairs(all_pairs, args.limit_per_group, args.seed)
    models, model_issues = discover_models(args.weights_dir, args.task)
    result = {"protocol": args.protocol, "full_inventory": inventory(all_pairs),
              "selected_inventory": inventory(pairs), "data_issues": issues,
              "models": [{"task": m["task"], "type": m["config"]["task_type"], "unit": m["config"].get("unit")} for m in models],
              "model_issues": model_issues, "smoke_test": args.limit_per_group is not None}
    args.output.mkdir(parents=True, exist_ok=True)
    write_json(args.output / "audit.json", result)
    write_csv(args.output / "pairs.csv", pairs)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return pairs, models, result


def run(args):
    import torch
    from medicalfacefound.inference.face import load_image
    from medicalfacefound.inference.predict import load_task, predict_values
    from .preprocess import prepare, save_crop

    started = time.perf_counter()
    torch.set_num_threads(args.threads)
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    torch.use_deterministic_algorithms(True)
    if args.device.startswith("cuda"):
        torch.backends.cudnn.benchmark = False
        os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    os.environ["DEEPFACE_BACKEND_ENGINE"] = "pytorch"
    os.environ["DEEPFACE_HOME"] = str(args.detector_home.resolve())
    detector_weights = args.detector_home / ".deepface/weights/retinaface.pth"
    if not detector_weights.is_file():
        raise FileNotFoundError(f"RetinaFace weights missing: {detector_weights}. See ROBUSTNESS.md; no implicit download.")
    pairs, models, audit_result = audit(args)
    if not models:
        raise ValueError("No runnable local models; see audit.json")
    thresholds = json.loads(args.thresholds.read_text()) if args.thresholds else {}
    for task, spec in thresholds.items():
        if not isinstance(spec, dict) or set(spec)-{"decision_threshold", "absolute_tolerance"}:
            raise ValueError(f"Invalid threshold configuration: {task}")
        if any(not np.isfinite(float(v)) for v in spec.values()) or spec.get("absolute_tolerance", 0) < 0:
            raise ValueError(f"Non-finite/negative tolerance: {task}")
    versions = version_info()
    prep_spec = dict(mode=args.preprocess, threshold=args.face_threshold, ratio=args.ratio,
                     detector_max_side=args.detector_max_side, allow_upscaling=args.allow_upscaling,
                     multi_face=args.multi_face, detector_sha256=digest_file(detector_weights),
                     versions=versions, source_sha256=source_fingerprint())
    prep_id = fingerprint(prep_spec)
    cache = args.cache.resolve()
    crops_dir = cache / "crops" / prep_id
    crops_dir.mkdir(parents=True, exist_ok=True)
    paths = sorted({p[k] for p in pairs for k in ("baseline", "variant")})
    qc, crop_paths, keys = {}, {}, {}
    print(f"Preprocessing {len(paths)} unique images ({args.preprocess}); cache={cache}", flush=True)
    for i, path in enumerate(paths, 1):
        source_sha = digest_file(path)
        key = fingerprint([path, source_sha, prep_id]); keys[path] = key
        metadata_path, crop_path = crops_dir/f"{key}.json", crops_dir/f"{key}.png"
        entry = json.loads(metadata_path.read_text()) if metadata_path.exists() else None
        if entry and entry["status"] == "ok" and (not crop_path.exists() or digest_file(crop_path) != entry.get("crop_sha256")):
            entry = None
        if args.retry_failures and entry and entry["status"] != "ok":
            entry = None
        if entry is None:
            try:
                crop, entry = prepare(path, mode=args.preprocess, threshold=args.face_threshold,
                                      ratio=args.ratio, multi_face=args.multi_face,
                                      detector_max_side=args.detector_max_side, allow_upscaling=args.allow_upscaling)
                if crop is not None:
                    save_crop(crop_path, crop)
                    entry["crop_sha256"] = digest_file(crop_path)
            except Exception as exc:
                entry = dict(status="preprocess_error", error=f"{type(exc).__name__}: {exc}")
            entry.update(path=path, source_sha256=source_sha, cache_key=key)
            write_json(metadata_path, entry)
        qc[path] = entry
        if entry["status"] == "ok":
            crop_paths[path] = crop_path
        if i % 50 == 0 or i == len(paths):
            print(f"  preprocessing {i}/{len(paths)}, usable {len(crop_paths)}", flush=True)
    write_csv(args.output / "image_qc.csv", list(qc.values()))
    predictions, model_status = [], list(audit_result["model_issues"])
    for model_info in models:
        task, cfg = model_info["task"], model_info["config"]
        folder = args.weights_dir / "tasks" / task
        model_sha = digest_file(folder/"model.safetensors")
        if cfg.get("sha256") and cfg["sha256"] != model_sha:
            model_status.append(dict(task=task, error="weight SHA256 differs from config"))
            continue
        spec = dict(task=task, config=cfg, weights_sha256=model_sha, preprocess=prep_id,
                    device=args.device, batch_size=args.batch_size, half=args.half, threads=args.threads)
        pred_dir = cache/"predictions"/fingerprint(spec)
        pred_dir.mkdir(parents=True, exist_ok=True)
        pending, task_predictions = [], []
        for path in paths:
            prediction_path = pred_dir/f"{keys[path]}.json"
            if path not in crop_paths:
                task_predictions.append(dict(task=task, path=path, status=qc[path]["status"], value=None))
            elif prediction_path.exists():
                entry = json.loads(prediction_path.read_text())
                if entry["status"] != "ok" and args.retry_failures:
                    pending.append(path)
                else:
                    task_predictions.append(entry)
            else:
                pending.append(path)
        print(f"Model {task}: {len(pending)} images pending", flush=True)
        model = None
        error = None
        try:
            if pending:
                model, loaded_cfg = load_task(task, local_dir=args.weights_dir, device=args.device, half=args.half)
                for start in range(0, len(pending), args.batch_size):
                    batch = pending[start:start+args.batch_size]
                    try:
                        results = predict_values(model, loaded_cfg, [load_image(crop_paths[p]) for p in batch],
                                                 batch_size=args.batch_size, device=args.device, half=args.half)
                        if len(results) != len(batch):
                            raise ValueError("prediction count mismatch")
                        entries = []
                        for path, result in zip(batch, results):
                            value = float(result["value"])
                            if not np.isfinite(value):
                                raise ValueError("non-finite model prediction")
                            entries.append(dict(task=task, path=path, status="ok", value=value, unit=result.get("unit")))
                    except Exception as exc:
                        entries = [dict(task=task, path=p, status="inference_error", value=None,
                                        error=f"{type(exc).__name__}: {exc}") for p in batch]
                    for entry in entries:
                        write_json(pred_dir/f"{keys[entry['path']]}.json", entry)
                    task_predictions.extend(entries)
                    if start % (args.batch_size*10) == 0 or start+args.batch_size >= len(pending):
                        print(f"  {task} {min(start+args.batch_size, len(pending))}/{len(pending)}", flush=True)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            recorded = {p["path"] for p in task_predictions}
            task_predictions.extend(dict(task=task, path=p, status="model_error", value=None, error=error)
                                    for p in paths if p not in recorded)
        finally:
            del model
            gc.collect()
            if args.device.startswith("cuda"):
                torch.cuda.empty_cache()
        predictions.extend(task_predictions)
        model_status.append(dict(task=task, weights_sha256=model_sha, config=cfg, error=error,
                                 predicted=sum(p["status"] == "ok" for p in task_predictions), total=len(paths)))
        write_csv(args.output/"predictions.csv", predictions)
    image_hashes = {path: row["source_sha256"] for path, row in qc.items()}
    paired, summaries = summarize(pairs, predictions, models, args, thresholds, image_hashes=image_hashes)
    write_csv(args.output/"paired_results.csv", paired)
    write_csv(args.output/"summary.csv", summaries)
    write_json(args.output/"summary.json", summaries)
    complete = not audit_result["data_issues"] and not any(m.get("error") for m in model_status)
    complete = complete and all(p["status"] not in {"inference_error", "model_error", "preprocess_error"} for p in predictions)
    complete = complete and bool(summaries) and all(r.get("n", 0) > 0 for r in summaries)
    metadata = dict(created_utc=datetime.now(timezone.utc).isoformat(), elapsed_seconds=time.perf_counter()-started,
                    status="complete" if complete else "partial", smoke_test=args.limit_per_group is not None,
                    protocol=args.protocol, data_root=str(args.data_root.resolve()), weights_dir=str(args.weights_dir.resolve()),
                    selected_inventory=inventory(pairs), preprocess=prep_spec, models=model_status,
                    seed=args.seed, bootstrap=args.bootstrap, thresholds=thresholds,
                    duplicate_pairs=duplicate_pairs(pairs, image_hashes),
                    duplicate_pair_policy="Exclude repeated ordered image-SHA256 pairs within each dataset/contrast; retain raw denominator and exclusion records.",
                    methods_sources={"published_doi": "10.1016/j.landig.2026.101056",
                                     "published_pdf_reviewed": "PIIS2589750026000798 (1).pdf, 17 pages; robustness p12, data/code p17",
                                     "published_appendix_available": False,
                                     "statistical_details": "https://arxiv.org/pdf/2506.14909, p26",
                                     "preprocessing_code": "https://github.com/AIM-Harvard/FAHR-Face/blob/main/other/face_crop_align.py"},
                    command_options={k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
                    limitations=["Prediction stability only; no disease AUC or clinical validity assessment.",
                                 "Paper filename indices are unavailable; FEI pose mapping is a documented working assumption.",
                                 "Non-significant paired tests do not establish equivalence or robustness.",
                                 "RetinaFace backend/crop settings may differ from the paper."])
    write_json(args.output/"run.json", metadata)
    from .report import write_report
    write_report(args.output, metadata, summaries, paired)
    print(f"{metadata['status']}: report={args.output/'report.html'} ({metadata['elapsed_seconds']:.1f}s)", flush=True)
    return 0 if complete else 2


def duplicate_pairs(pairs, image_hashes):
    """Find exact repeated pairs without guessing identity from facial appearance."""
    seen, duplicates = {}, {}
    for pair in sorted(pairs, key=lambda p: p["pair_id"]):
        key = (pair["dataset"], pair["contrast"], image_hashes[pair["baseline"]], image_hashes[pair["variant"]])
        if key in seen:
            duplicates[pair["pair_id"]] = seen[key]
        else:
            seen[key] = pair["pair_id"]
    return duplicates


def summarize(pairs, predictions, models, args, thresholds, image_hashes=None):
    from .statistics import paired_statistics, adjust_bh
    lookup = {(p["task"], p["path"]): p for p in predictions}
    duplicates = duplicate_pairs(pairs, image_hashes) if image_hashes is not None else {}
    paired, summaries = [], []
    for model in models:
        task, cfg = model["task"], model["config"]
        groups = defaultdict(list)
        for pair in pairs:
            a, b = (lookup.get((task, pair[k]), {"status": "missing_prediction", "value": None}) for k in ("baseline", "variant"))
            valid = a["status"] == b["status"] == "ok"
            row = {**pair, "task": task, "baseline_status": a["status"], "variant_status": b["status"],
                   "status": "ok" if valid else "excluded", "baseline_value": a["value"], "variant_value": b["value"],
                   "difference": b["value"]-a["value"] if valid else None}
            if pair["pair_id"] in duplicates:
                row.update(status="duplicate_pair", duplicate_of=duplicates[pair["pair_id"]])
            paired.append(row); groups[pair["dataset"], pair["contrast"]].append(row)
        for (dataset, contrast), rows in sorted(groups.items()):
            valid = [r for r in rows if r["status"] == "ok"]
            if len({r["subject"] for r in rows}) != len(rows):
                raise ValueError("Repeated subject within a contrast; requires cluster inference")
            spec = thresholds.get(task, {})
            stats = paired_statistics([r["baseline_value"] for r in valid], [r["variant_value"] for r in valid],
                                      bootstrap=args.bootstrap, seed=args.seed,
                                      threshold=spec.get("decision_threshold"), tolerance=spec.get("absolute_tolerance"))
            row = dict(task=task, task_type=cfg["task_type"], unit="prob" if cfg["task_type"] == "classification" else cfg.get("unit"),
                       dataset=dataset, contrast=contrast, n_expected=len(rows), n_excluded=len(rows)-len(valid),
                       n_duplicate_pairs=sum(r["status"] == "duplicate_pair" for r in rows),
                       retention_rate=len(valid)/len(rows),
                       baseline_failure_rate=sum(r["baseline_status"] != "ok" for r in rows)/len(rows),
                       variant_failure_rate=sum(r["variant_status"] != "ok" for r in rows)/len(rows), **stats)
            if valid and cfg["task_type"] == "regression":
                row["mad_in_training_sd"] = row["mean_absolute_difference"]/cfg["target_std"]
            summaries.append(row)
    adjust_bh(summaries)
    return paired, summaries


def reanalyse(output):
    """Recompute statistics from immutable image-QC/prediction exports, without inference."""
    import csv
    from types import SimpleNamespace
    from .report import write_report

    output = Path(output)
    def read_csv(name):
        with (output/name).open(encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    metadata = json.loads((output/"run.json").read_text())
    pairs = read_csv("pairs.csv")
    predictions = read_csv("predictions.csv")
    qc = read_csv("image_qc.csv")
    for row in predictions:
        row["value"] = float(row["value"]) if row["value"] else None
        if row["status"] == "ok" and (row["value"] is None or not np.isfinite(row["value"])):
            raise ValueError("Nonfinite or missing successful prediction")
    image_hashes = {r["path"]: r["source_sha256"] for r in qc}
    models = [{"task": m["task"], "config": m["config"]} for m in metadata["models"] if "config" in m]
    args = SimpleNamespace(bootstrap=metadata["bootstrap"], seed=metadata["seed"])
    paired, summaries = summarize(pairs, predictions, models, args, metadata["thresholds"], image_hashes=image_hashes)
    metadata["duplicate_pairs"] = duplicate_pairs(pairs, image_hashes)
    metadata["duplicate_pair_policy"] = "Exclude repeated ordered image-SHA256 pairs within each dataset/contrast; retain raw denominator and exclusion records."
    metadata["analysis_revision"] = dict(updated_utc=datetime.now(timezone.utc).isoformat(),
                                         source_sha256=source_fingerprint(),
                                         input_sha256={name: digest_file(output/name) for name in ("pairs.csv", "predictions.csv", "image_qc.csv")},
                                         note="Recomputed statistics from saved full-run predictions, excluding byte-identical duplicate pairs. Original inference provenance is preserved.")
    if any(r["n"] == 0 for r in summaries):
        metadata["status"] = "partial"
    write_csv(output/"paired_results.csv", paired)
    write_csv(output/"summary.csv", summaries)
    write_json(output/"summary.json", summaries)
    write_json(output/"run.json", metadata)
    write_report(output, metadata, summaries, paired)
    print(f"Reanalysed {len(pairs)} raw pairs; excluded {len(metadata['duplicate_pairs'])} exact duplicate pair(s).")
    return 0 if metadata["status"] == "complete" else 2
