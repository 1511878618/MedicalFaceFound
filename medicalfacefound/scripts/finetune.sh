#!/usr/bin/env bash
# Biomarker fine-tuning. Run from anywhere after `pip install .`:
#   bash medicalfacefound/scripts/finetune.sh
# Edit LABEL, BLR and the paths for your setup.
# Add `--ft_mode mlp` for backbone-frozen, head-only training (use BLR=1e-2).
set -euo pipefail

EPOCHS=100

for LABEL in Height; do
  for BLR in 5e-3; do
    python -m medicalfacefound.main_finetune \
        --model swin_large_512to256 \
        --input_size 256 \
        --batch_size 32 \
        --finetune backbone.pth \
        --dataset face256_single \
        --data_path /data/face_256/ \
        --annotation_path /data/face_256/class_map.csv \
        --label "${LABEL}" \
        --type regression \
        --nb_classes 1 \
        --epochs "${EPOCHS}" \
        --early_stop 12 \
        --blr "${BLR}" \
        --layer_decay 0.75 \
        --weight_decay 0.05 \
        --drop_path 0.1 \
        --output_dir "runs/${LABEL}"
  done
done
