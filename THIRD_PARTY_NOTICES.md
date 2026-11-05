# Third-party notices

MedicalFaceFound builds on the following open-source projects. Their licenses apply
to the derived files listed below; the rest of the package is CC BY-NC 4.0
(see `LICENSE`).

## UM-MAE — CC BY-NC 4.0

- Upstream: <https://github.com/implus/UM-MAE>
- Derived files: the training code in `medicalfacefound/`
  (`main_pretrain.py`, `main_finetune.py`, `engine_pretrain.py`,
  `engine_finetune.py`, `mask_transform.py`, `utils/models_*.py`,
  `utils/datasets.py`, `utils/lr_*.py`, `utils/misc.py`, `utils/pos_embed.py`),
  which itself builds on MAE and DeiT.
- The package is therefore distributed under **CC BY-NC 4.0**, not a permissive
  license.

## Swin-Transformer — MIT

- Upstream: <https://github.com/microsoft/Swin-Transformer>
- The window-attention and patch-merging blocks follow the official Swin
  implementation. MIT permits use inside a CC BY-NC 4.0 work; the combined
  distribution remains non-commercial.

## timm — Apache 2.0

- Upstream: <https://github.com/huggingface/pytorch-image-models>
- Components: `timm.models.layers` (`DropPath`, `to_2tuple`, `trunc_normal_`),
  `timm.data.Mixup`, `timm.loss` (label smoothing, soft-target cross entropy),
  `timm.data.create_transform` for pretraining.
- Pin `timm==0.9.16`: `timm.models.layers` moved in timm 1.x.

## MAE / DeiT — research code

- <https://github.com/facebookresearch/mae>,
  <https://github.com/facebookresearch/deit>
- Training-loop and scheduler structure follow these implementations.

## RetinaFace / retina-face — MIT

- Upstream: <https://github.com/serengil/retinaface>
- Used by `medicalfacefound.inference.face` for face detection (installed as a
  regular dependency of the package). Detector weights are downloaded by the package
  on first use and are not redistributed here.

## Model weights

The weights are distributed separately from this code package; their license will be
published together with them.
