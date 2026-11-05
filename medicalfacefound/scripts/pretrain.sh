#!/usr/bin/env bash
# Self-supervised UM-MAE pretraining (8 GPUs).
# Run from anywhere after `pip install .`:
#   bash medicalfacefound/scripts/pretrain.sh
# Edit the paths before running.
set -euo pipefail

python -m torch.distributed.run --nproc_per_node 8 --master_port 2024 \
    -m medicalfacefound.main_pretrain \
    --batch_size 64 --input_size 512 --token_size 32 \
    --model mae_swin_large_512 --mask_regular \
    --epochs 256 --warmup_epochs 10 --blr 1e-4 \
    --data_path /data/face_512/ \
    --log_dir runs/pretrain \
    --output_dir runs/pretrain \
    --load_from ""
