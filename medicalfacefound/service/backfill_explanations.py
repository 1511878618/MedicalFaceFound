"""Backfill Grad-CAM overlays for completed predictions.

Run from the repository root:

    python -m medicalfacefound.service.backfill_explanations --dry-run
    python -m medicalfacefound.service.backfill_explanations
    python -m medicalfacefound.service.backfill_explanations --replace-existing
    python -m medicalfacefound.service.backfill_explanations --variant norm1

Only predictions whose recorded model_version matches the current weights are
processed; the stored 256x256 processed image is used as the model input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sqlite3
from collections import defaultdict
from contextlib import closing
from pathlib import Path

from medicalfacefound.service import database as db
from medicalfacefound.service.explain import gradcam_png
from medicalfacefound.service.quality import QUALITY_VERSION

logger = logging.getLogger("backfill-explanations")


def current_version(weights_dir: Path, model: str) -> str:
    raw = (weights_dir / "tasks" / model / "config.json").read_bytes()
    config = json.loads(raw)
    return f'{config.get("sha256", "unverified")}:{hashlib.sha256(raw).hexdigest()}:{QUALITY_VERSION}'


def parse_args():
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Backfill Grad-CAM images for completed predictions")
    parser.add_argument("--database", default=os.getenv("MEDICALFACE_DB_PATH", str(root / "data" / "medicalface.sqlite3")))
    parser.add_argument("--weights-dir", default=os.getenv("MFF_WEIGHTS_DIR", str(root / "weights")))
    parser.add_argument("--device", default=os.getenv("MFF_DEVICE", "cpu"))
    parser.add_argument("--limit", type=int, default=0, help="maximum number of predictions to process (0 = all)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--variant", choices=("block", "norm1"), default="block")
    parser.add_argument("--replace-existing", action="store_true",
                        help="regenerate completed predictions even when a heatmap already exists")
    parser.add_argument("--include-deletion-requested", action="store_true")
    return parser.parse_args()


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args()
    database = Path(args.database).expanduser().resolve()
    weights_dir = Path(args.weights_dir).expanduser().resolve()
    if not database.is_file():
        raise SystemExit(f"database not found: {database}")

    query = """SELECT p.id, p.capture_id, p.model, p.model_version, c.processed_image
        FROM predictions p JOIN captures c ON c.id = p.capture_id
        WHERE p.status = 'completed'
          AND c.processed_image IS NOT NULL"""
    if not args.replace_existing:
        image_column, _ = db.EXPLANATION_COLUMNS[args.variant]
        query += f" AND p.{image_column} IS NULL"
    if not args.include_deletion_requested:
        query += " AND c.deletion_requested_at IS NULL"
    query += " ORDER BY p.model, p.created_at"
    if args.limit:
        query += f" LIMIT {int(args.limit)}"

    with closing(sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(row) for row in conn.execute(query)]

    grouped = defaultdict(list)
    skipped = []
    versions = {}
    for row in rows:
        model = row["model"]
        if model not in versions:
            versions[model] = current_version(weights_dir, model)
        if row["model_version"] != versions[model]:
            skipped.append((row, "模型版本与当前权重不一致"))
            continue
        grouped[model].append(row)

    print(f"待处理 {sum(len(items) for items in grouped.values())} 条；跳过 {len(skipped)} 条", flush=True)
    for row, reason in skipped[:10]:
        print(f"  skip {row['id']} ({row['model']}): {reason}", flush=True)
    if args.dry_run or not grouped:
        for model, items in sorted(grouped.items()):
            print(f"  {model}: {len(items)} 条", flush=True)
        return

    backup = db.backup_database(database, "before-gradcam-backfill")
    print(f"数据库备份：{backup}", flush=True)

    done = failed = changed = 0
    for model, items in sorted(grouped.items()):
        from medicalfacefound.inference.predict import load_task
        from medicalfacefound.service.image import decode_image

        print(f"[{model}] 加载模型，共 {len(items)} 条", flush=True)
        network, config = load_task(model, local_dir=weights_dir, device=args.device)
        for index, row in enumerate(items, 1):
            try:
                image = decode_image(bytes(row["processed_image"])).array
                png = gradcam_png(network, config, image, variant=args.variant)
                if not db.save_explanation(database, row["id"], png, variant=args.variant,
                                           include_deletion_requested=args.include_deletion_requested):
                    changed += 1
                    continue
                done += 1
                if index % 10 == 0 or index == len(items):
                    print(f"  [{model}] 已检查 {index}/{len(items)} 条", flush=True)
            except Exception:
                failed += 1
                logger.exception("backfill failed: %s", row["id"])
    print(f"完成 {done} 条，失败 {failed} 条，跳过 {len(skipped) + changed} 条", flush=True)
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
