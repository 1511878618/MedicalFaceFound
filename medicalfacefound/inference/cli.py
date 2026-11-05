"""Command line interface: ``mff crop`` and ``mff predict``."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from medicalfacefound.inference.face import FaceCropper, load_image
from medicalfacefound.inference.predict import DEFAULT_REPO, load_task, load_tasks_index, predict_values

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}


def collect_images(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for item in paths:
        p = Path(item)
        if p.is_dir():
            files.extend(sorted(q for q in p.rglob("*") if q.suffix.lower() in IMAGE_SUFFIXES))
        elif p.exists():
            files.append(p)
        else:
            raise FileNotFoundError(p)
    if not files:
        raise SystemExit("no images found")
    return files


def cmd_crop(args: argparse.Namespace) -> int:
    from PIL import Image

    crop = FaceCropper(size=args.size, ratio=args.ratio).crop_path(args.image)
    if crop is None:
        raise SystemExit("no face detected")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(crop).save(out, quality=95)
    print(f"saved {out} ({crop.shape[1]}x{crop.shape[0]})")
    return 0


def cmd_predict(args: argparse.Namespace) -> int:
    if not args.task and not args.all_tasks:
        raise SystemExit("pass --task <name> or --all-tasks")

    images = collect_images(args.input)
    print(f"{len(images)} image(s)")

    if args.no_crop:
        crops = [load_image(p) for p in images]
    else:
        cropper = FaceCropper(size=args.size, ratio=args.ratio)
        crops, kept = [], []
        for path in images:
            crop = cropper.crop_path(path)
            if crop is None:
                print(f"  no face: {path}")
                continue
            crops.append(crop)
            kept.append(path)
        images = kept
        print(f"{len(crops)} face(s) detected")

    tasks = args.task or [t["task"] for t in load_tasks_index(args.repo, args.local_dir)["tasks"]]

    rows = []
    for i, task in enumerate(tasks, 1):
        model, cfg = load_task(task, args.repo, args.local_dir, args.device, args.half)
        preds = predict_values(model, cfg, crops, args.batch_size, args.device, args.half)
        rows.extend({"file": str(path), **pred} for path, pred in zip(images, preds))
        print(f"[{i}/{len(tasks)}] {task}: " + ", ".join(f"{p['value']:.2f}" for p in preds[:3]))
        del model

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["file", "task", "value", "unit"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {out} ({len(rows)} rows)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    import torch

    parser = argparse.ArgumentParser(prog="mff", description="MedicalFaceFound inference")
    sub = parser.add_subparsers(dest="command", required=True)

    crop = sub.add_parser("crop", help="detect and crop a face with RetinaFace")
    crop.add_argument("image")
    crop.add_argument("--out", default="face_crop.jpg")
    crop.add_argument("--size", type=int, default=256)
    crop.add_argument("--ratio", type=float, default=1.2)
    crop.set_defaults(func=cmd_crop)

    pred = sub.add_parser("predict", help="predict biomarkers")
    pred.add_argument("--input", nargs="+", required=True, help="image files or directories")
    pred.add_argument("--task", action="append", help="biomarker folder name (repeatable)")
    pred.add_argument("--all-tasks", action="store_true", help="run every task in tasks.json")
    pred.add_argument("--repo", default=DEFAULT_REPO)
    pred.add_argument("--local-dir", type=Path, help="downloaded copy of the weights repository")
    pred.add_argument("--out", type=Path, default=Path("predictions.csv"))
    pred.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    pred.add_argument("--batch-size", type=int, default=8)
    pred.add_argument("--half", action="store_true", help="fp16 inference on CUDA")
    pred.add_argument("--no-crop", action="store_true", help="images are already 256x256 crops")
    pred.add_argument("--size", type=int, default=256)
    pred.add_argument("--ratio", type=float, default=1.2)
    pred.set_defaults(func=cmd_predict)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
