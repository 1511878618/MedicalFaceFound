"""Batch prediction with a locally fine-tuned checkpoint (external validation).

    python -m medicalfacefound.predict_folder --checkpoint runs/Height/checkpoint-best_val.pth \
        --input /data/external_cohort/ --out external_Height.csv

The checkpoint may be a ``.pth``/``.pt`` file written by ``main_finetune``
(``checkpoint-best_val.pth``, ``checkpoint-best_test.pth``, ``checkpoint-<epoch>.pth``), the bare
``state_dict`` written by the early-stopping callback (``checkpoint.pth``), or a
``.safetensors`` file (e.g. one of the released task folders). Model name, task type and target
mean/std are read from the checkpoint, from a sibling ``config.json``, or from the training run
directory, in that order; explicit options win over all of them.

Images are expected to be 256 x 256 face crops; add ``--crop`` to detect and crop faces from raw
photographs with RetinaFace.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def get_args_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        "Batch prediction with a fine-tuned MedicalFaceFound checkpoint", add_help=True)
    parser.add_argument("--checkpoint", required=True,
                        help="checkpoint .pth/.pt/.safetensors (from main_finetune)")
    parser.add_argument("--input", nargs="+", required=True, help="image files or directories")
    parser.add_argument("--out", default="predictions.csv", help="output CSV")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--device", default=None, help="cuda / cpu (default: cuda if available)")
    parser.add_argument("--half", action="store_true", help="fp16 inference on CUDA")
    parser.add_argument("--crop", action="store_true",
                        help="run RetinaFace detection/cropping on raw photographs "
                             "(default: images are already 256x256 face crops)")
    parser.add_argument("--size", type=int, default=256)
    parser.add_argument("--ratio", type=float, default=1.2)
    parser.add_argument("--with-normed", action="store_true",
                        help="add a value_normed column (regression)")
    parser.add_argument("--limit", type=int, default=None, help="predict only the first N images")
    # recovery options for bare state_dict checkpoints
    parser.add_argument("--model", default=None,
                        help="model name when the checkpoint has no training args")
    parser.add_argument("--type", dest="task_type", default=None,
                        choices=["regression", "classification"])
    parser.add_argument("--nb-classes", type=int, default=None)
    parser.add_argument("--task", default=None, help="task name written to the CSV header")
    parser.add_argument("--target-mean", type=float, default=None,
                        help="overrides the mean stored in the checkpoint")
    parser.add_argument("--target-std", type=float, default=None,
                        help="overrides the std stored in the checkpoint")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = get_args_parser().parse_args(argv)

    import torch

    from medicalfacefound.inference.predict import load_checkpoint, predict_folder

    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    model, cfg = load_checkpoint(
        args.checkpoint, model_name=args.model, task=args.task, task_type=args.task_type,
        nb_classes=args.nb_classes, target_mean=args.target_mean, target_std=args.target_std,
        device=device, half=args.half)

    print(f"checkpoint : {args.checkpoint}")
    print(f"task       : {cfg['task']} ({cfg['task_type']})"
          + (f", unit={cfg['unit']}" if cfg.get("unit") else ""))
    print(f"scaling    : value = output * {cfg['target_std']:.6g} + {cfg['target_mean']:.6g}")
    print(f"device     : {device}{' (fp16)' if args.half else ''}")

    summary = predict_folder(
        model, cfg, inputs=args.input, out=args.out, batch_size=args.batch_size, device=device,
        half=args.half, crop=args.crop, size=args.size, ratio=args.ratio,
        with_normed=args.with_normed, limit=args.limit)

    print(f"images     : {summary['images']} scanned, {summary['written']} predicted, "
          f"{summary['skipped']} skipped (no face)")
    print(f"wrote      : {Path(summary['out']).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
