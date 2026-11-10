from __future__ import annotations

import argparse
import math
import os
from pathlib import Path


def positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return number


def main(argv=None):
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="External paired robustness evaluation with MedicalFaceFound")
    parser.add_argument("command", choices=["audit", "run", "report", "reanalyse"])
    parser.add_argument("--data-root", type=Path, default=Path.home()/"Desktop/人脸外部验证数据")
    parser.add_argument("--weights-dir", type=Path, default=root/"weights")
    parser.add_argument("--output", type=Path, default=root/"output/robustness/primary")
    parser.add_argument("--cache", type=Path, default=root/"output/robustness/cache")
    parser.add_argument("--detector-home", type=Path, default=root/"weights/retinaface-cache")
    parser.add_argument("--task", action="append", help="repeat to select tasks; otherwise discover all local tasks")
    parser.add_argument("--dataset", action="append", choices=["fei", "hda", "makeup"], help="repeat to select datasets; default all three")
    parser.add_argument("--protocol", choices=["primary", "extended"], default="primary")
    parser.add_argument("--fei-mapping", type=Path, help='JSON list of [contrast, baseline_index, variant_index]')
    parser.add_argument("--preprocess", choices=["retina-align", "package"], default="retina-align")
    parser.add_argument("--face-threshold", type=float, default=.9)
    parser.add_argument("--detector-max-side", type=int, default=640, help="fixed detector input cap; 0 disables resizing; crop uses original pixels")
    parser.add_argument("--allow-upscaling", action="store_true", help="RetinaFace library default; may miss oversized faces")
    parser.add_argument("--ratio", type=float, default=1.2, help="square expansion ratio, package mode only")
    parser.add_argument("--multi-face", choices=["reject", "highest-confidence"], default="reject")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--half", action="store_true", help="CUDA float16 only")
    parser.add_argument("--batch-size", type=positive, default=4)
    parser.add_argument("--threads", type=positive, default=4)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--bootstrap", type=positive, default=2000)
    parser.add_argument("--limit-per-group", type=positive, help="deterministic smoke test, explicitly marked in report")
    parser.add_argument("--thresholds", type=Path, help="task-specific decision_threshold / absolute_tolerance JSON")
    parser.add_argument("--retry-failures", action="store_true")
    args = parser.parse_args(argv)
    if not 0 < args.face_threshold <= 1 or not math.isfinite(args.ratio) or args.ratio <= 0:
        parser.error("face-threshold must be in (0,1]; ratio must be positive")
    if args.detector_max_side < 0:
        parser.error("detector-max-side must be nonnegative")
    if args.half and args.device != "cuda":
        parser.error("the package half-precision API requires --device cuda")
    if args.fei_mapping and args.protocol == "extended":
        parser.error("--fei-mapping is only used with --protocol primary")
    os.environ.setdefault("MPLCONFIGDIR", str(args.cache.resolve()/"matplotlib"))
    if args.command == "reanalyse":
        from .runner import reanalyse
        return reanalyse(args.output)
    if args.command == "report":
        import csv, json
        from .report import write_report
        metadata = json.loads((args.output/"run.json").read_text())
        summaries = json.loads((args.output/"summary.json").read_text())
        with (args.output/"paired_results.csv").open(encoding="utf-8-sig", newline="") as f:
            paired = list(csv.DictReader(f))
        for row in paired:
            for key in ("baseline_value", "variant_value", "difference"):
                row[key] = float(row[key]) if row[key] else None
        write_report(args.output, metadata, summaries, paired)
        return 0
    from .runner import audit, run
    if args.command == "audit":
        _, models, result = audit(args)
        return 2 if not models or result["data_issues"] or result["model_issues"] else 0
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
