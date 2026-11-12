# MedicalFaceFound

**A Facial Foundation Model for Clinical Biomarker Prediction and Real-World Mobile Deployment**

Official implementation accompanying the article in *Advanced Science* (2026).

[![Paper](https://img.shields.io/badge/DOI-10.1002%2Fadvs.77861-blue)](https://doi.org/10.1002/advs.77861)
[![Code license: CC BY-NC 4.0](https://img.shields.io/badge/code-CC%20BY--NC%204.0-lightgrey.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-brightgreen.svg)](pyproject.toml)

[Paper](https://doi.org/10.1002/advs.77861) · [Installation](#installation) ·
[Inference](#inference) · [Fine-tuning](#fine-tuning) · [Citation](#citation)

## Overview

**MedicalFaceFound** is a facial foundation model that estimates clinical biomarkers
from a single frontal photograph, without blood sampling. It targets **62 biomarkers
across eight physiological systems** — anthropometric, cardiovascular, digestive,
electrolyte, endocrine, hematologic, immune and renal — and supports downstream risk
screening for cardiovascular, metabolic, lipid and haematologic conditions.

The backbone is a **Swin-Large Transformer** trained with self-supervised masked
autoencoding (UM-MAE) through a **three-stage general-to-clinical curriculum**:

| Stage | Data | Images | What it learns |
| :-- | :-- | --: | :-- |
| 1 | ImageNet-22K | 14,197,122 | general visual representations |
| 2 | VGGFace2-HQ | 1,160,250 | facial structure and local facial patterns |
| 3 | Anzhen clinical facial photographs | 88,489 | clinical acquisition characteristics and health-related facial phenotypes |

For each biomarker the encoder is fine-tuned independently with a task-specific head
(62 models), and predictions are returned in clinical units.

## Results

| Finding | Number |
| :-- | :-- |
| Biomarkers predicted | 62 across 8 systems |
| Internal cohort | AZ-TR, N = 4,698 (median age 60.0) |
| External cohorts | AZ-EV1 (1,498), AZ-EV2 (2,247), AZTZ-EV (206), DX-EV (900), genetics AZ-GEV (111) |
| Smartphone cohort | APP-EV, N = 110 |
| Median Pearson's r, internal | **0.197** (IQR 0.104–0.291) |
| Median Pearson's r, external | **0.172** (IQR 0.081–0.266) |
| Baselines (internal) | Swin-Large 0.168, ResNet18 0.108 |
| Biomarkers where MedicalFaceFound ranks first | **45 / 62 (73%)** |
| Strongest external signals | RBC 0.478, eGFR 0.442, HDL-C 0.430 |
| vs. polygenic risk scores | better for 14 / 26 biomarkers |
| Coronary stenosis from face-estimated cardiovascular biomarkers | AUC 0.66 |
| Label efficiency | retains performance with **400 labelled samples** |
| Agreement with laboratory values (relative importance, ICC) | 0.86 (95% CI 0.68–0.94) |

Per-system median Pearson's r (internal / external):

| System | Internal | External |
| :-- | --: | --: |
| Anthropometrics | 0.698 | 0.702 |
| Renal | 0.277 | 0.315 |
| Electrolytes | 0.141 | 0.030 |

These results are reported at the cohort level in the paper. See the article and
supplementary materials for the evaluation protocols and per-biomarker results.

## Installation

Clone the repository and install the package in a Python 3.9+ environment:

```bash
git clone https://github.com/1511878618/MedicalFaceFound.git
cd MedicalFaceFound
python -m pip install -e .
```

This installs the `mff` inference CLI, Python API and training dependencies.
Dependencies are declared in [pyproject.toml](pyproject.toml); `timm` is pinned to
`0.9.16` for compatibility with the model implementation. Install a compatible
PyTorch / torchvision build for your CPU or CUDA environment.

For the optional research web application, install the service dependencies:

```bash
python -m pip install -e '.[service]'
```

A conda configuration is also provided in
[environment-service.yml](environment-service.yml). See the
[service guide](README-service.md) for detector setup and deployment.

```bash
mff --help
python -m medicalfacefound.main_finetune --help
python -m medicalfacefound.main_pretrain --help
```

## Model checkpoints

Model checkpoints are distributed separately from the source code. The planned
release includes the pretrained backbone and 62 biomarker-specific checkpoints.
Hugging Face download instructions will be available with the checkpoint release.
The inference examples below use checkpoints stored in a local `weights/` directory.

| Path | Contents | Size |
| :-- | :-- | --: |
| `backbone/model.safetensors` | UM-MAE Swin-L encoder (400 tensors, 194.9 M parameters) | 0.73 GiB |
| `tasks/<name>/model.safetensors` | 62 fine-tuned biomarker models (404 tensors each) | 45.8 GiB |
| `tasks.json` | index: task type, `target_mean`/`target_std`, SHA-256 | — |

Each `tasks/<name>/config.json` stores the unit and the `target_mean` / `target_std`
used for de-normalisation. The checkpoints do not carry per-task metrics; performance
is reported in the paper.

```text
weights/
├── backbone/
│   ├── config.json
│   └── model.safetensors
├── tasks/
│   └── Age/
│       ├── config.json
│       └── model.safetensors
└── tasks.json
```

Each task can be used independently. `--all-tasks` reads the task list from
`tasks.json` and requires the corresponding checkpoint directories.

## Inference

### Command line

```bash
# Predict one biomarker from a photograph; face detection runs automatically.
mff predict --input selfie.jpg --task Age --local-dir weights --out predictions.csv

# Predict all tasks listed in weights/tasks.json for a directory of photographs.
mff predict --input photos/ --all-tasks --local-dir weights --out predictions.csv

# Crop separately, then skip detection for the prepared crop.
mff crop selfie.jpg --out face.jpg
mff predict --input face.jpg --no-crop --task HDLC --local-dir weights
```

Use `--device cpu` or `--device cuda` to select the inference device. Predictions
are written to CSV with the image path, task name, predicted value and unit.

### Python

```python
from medicalfacefound import FaceCropper, load_task, predict_values

crop = FaceCropper().crop_path("selfie.jpg")  # RGB uint8, shape (256, 256, 3)
if crop is None:
    raise ValueError("No face detected in the input image")

model, config = load_task("Age", local_dir="weights", device="cpu")
predictions = predict_values(model, config, [crop], device="cpu")
print(predictions)  # Each result contains task, value and unit.
```

Regression models return values in clinical units: the package applies
`value = output * target_std + target_mean` using `tasks/<name>/config.json`.
The 62 biomarkers evaluated in the paper are regression tasks; the classification wrapper is used
for the additional models (sex, smoking, etc.) that are not part of this release.

### Input requirements

A 256 × 256 RGB frontal face crop, ImageNet-normalised. `FaceCropper` performs the
RetinaFace detection, expands the box to a square (margin ratio 1.2), pads out-of-frame
faces with edge pixels and resizes with bicubic interpolation. If multiple faces
are detected, the inference cropper selects the detection with the highest confidence;
if none is detected, it returns `None`. The web application applies additional
single-face and image-quality checks, described in the [service guide](README-service.md).

### Resource requirements

Measured with the released weights (fp32) on a single RTX 4060:

| Setting | Throughput | Memory |
| :-- | --: | --: |
| GPU, `--batch-size 8` | ≈17 ms / image | ≈1.15 GB |
| CPU, `--batch-size 8` | ≈316 ms / image | — |
| One model on disk | — | 780 MB (194.9 M parameters) |

`--all-tasks` loads models sequentially; each biomarker has its own fine-tuned
backbone. Runtime therefore depends on both the number of tasks and the number
of image batches processed.

## Fine-tuning

To adapt MedicalFaceFound to a new cohort or target, initialise the encoder from
the pretrained backbone and fine-tune it with a task-specific prediction head.
The repository supports full-network fine-tuning and training the prediction head
with a frozen encoder.

> **Dataset adaptation required.** The cohort-specific annotation reader (`SingleTaskDataset._load_annotations` in
> `medicalfacefound/utils/datasets.py`) ships as a stub: fill it in for your CSV
> (filter by `type`, drop rows with a missing target, compute the train-split
> mean/std) before `main_finetune` can build a dataset.

### Data format

`--data_path` points at a directory with **one folder per subject**, named by `eid`;
every `.jpg` / `.jpeg` / `.png` inside is one sample (several photographs per subject
are allowed):

```
face_256/
├── az_1032/
│   ├── DSC05446.JPG
│   └── DSC05459.JPG
├── az_4777/
└── ...
```

`--annotation_path` is a CSV with `eid`, `type` (`train` / `validation` / `test`, split
**by subject**) and the target column named by `--label`:

```csv
eid,type,Height,Sex,HDLC
az_1032,train,172.0,1,1.32
az_4777,train,,0,1.10
az_9001,validation,168.5,1,1.45
az_9002,test,175.0,0,1.28
```

- rows with a missing target are dropped; rows whose `eid` has no folder are reported
  in `log_<split>set.txt`;
- regression (`--type regression --nb_classes 1`) z-scores the target with the
  training-split mean/std — the same numbers stored as `target_mean` / `target_std`
  in each released `config.json`;
- classification (`--type classification --nb_classes 2`) uses integer labels and no
  normalisation;
- `--predict` mode ignores the CSV targets and scores every image.

### Load the backbone

The released backbone is `safetensors`; `main_finetune.py` reads a `.pth`, so convert
it once:

```python
import torch
from safetensors.torch import load_file

state = load_file("backbone/model.safetensors")
torch.save({"model": state}, "backbone.pth")
```

Pass the converted checkpoint with `--finetune backbone.pth`. The task-specific
`fc_norm.*` and `head.*` parameters are initialised for the new target:

```python
model.load_state_dict(state, strict=False)   # missing: fc_norm, head
```

This is the same starting point used for the 62 released models.


### Command

Example configuration for a single biomarker on one GPU:

```bash
python -m medicalfacefound.main_finetune \
  --model swin_large_512to256 \
  --input_size 256 --batch_size 32 \
  --finetune backbone.pth \
  --dataset face256_single \
  --data_path /data/face_256/ \
  --annotation_path /data/face_256/class_map.csv \
  --label Height --type regression --nb_classes 1 \
  --epochs 100 --early_stop 12 \
  --blr 5e-3 --layer_decay 0.75 --weight_decay 0.05 --drop_path 0.1 \
  --output_dir runs/Height
```

What each flag does:

| Flag | Meaning |
| :-- | :-- |
| `--model swin_large_512to256` | Swin-L with 256 input, `window_size=8` (the released architecture) |
| `--finetune backbone.pth` | initialise from the released UM-MAE backbone |
| `--ft_mode full\|mlp` | full fine-tuning (default) or backbone-frozen, head-only training |
| `--dataset face256_single` | single-biomarker dataset (`'single'` selects `SingleTaskDataset`) |
| `--data_path` / `--annotation_path` | image root (one folder per `eid`) / CSV with `eid,type,<label>` |
| `--label Height --type regression --nb_classes 1` | target column, task type, output dim |
| `--blr 5e-3 --layer_decay 0.75` | base lr and layer-wise lr decay |
| `--early_stop 12` | stop if validation loss does not improve for 12 epochs |
| `--output_dir` | checkpoints, logs and `result.csv` |

For a classification biomarker (e.g. sex) use
`--label Sex --type classification --nb_classes 2`. For multiple GPUs, run the same
script through `python -m torch.distributed.run --nproc_per_node 8` (or `torchrun
--nproc_per_node 8`) and scale `--batch_size` per GPU; `medicalfacefound/scripts/finetune.sh`
is a template of that loop.

### Fine-tuning modes

`--ft_mode` selects which parameters are optimised:

| `--ft_mode` | Trainable parameters | Behaviour |
| :-- | :-- | :-- |
| `full` (default) | whole network (194.9 M) | AdamW with layer-wise lr decay (`--layer_decay`) across `patch_embed`, `blocks` and the head; the setting used for the 62 released models |
| `mlp` | head only, `fc_norm.*` + `head.*` (4,609 parameters for a regression task) | Swin backbone (`patch_embed`, `blocks`) frozen; the head is optimised with a flat learning rate and `--layer_decay` is ignored |

In `mlp` mode only the readout is adapted: the pretrained features are held fixed, which
is the appropriate setting for small cohorts and for measuring how linearly separable the
pretrained representation already is. Stochastic depth is disabled in this mode
(`--drop_path` is forced to 0) so the frozen features stay deterministic during training.
The parameter count is small, so a higher base learning rate is recommended, e.g.
`--blr 1e-2` at `--batch_size 32` (effective lr 1.25e-3).

The checkpoint layout is identical in both modes (`fc_norm.*` + `head.*` on top of the
backbone), so `mlp` checkpoints load through `load_task` exactly like `full` ones.

```bash
python -m medicalfacefound.main_finetune \
  --model swin_large_512to256 \
  --input_size 256 --batch_size 32 \
  --finetune backbone.pth \
  --ft_mode mlp \
  --dataset face256_single \
  --data_path /data/face_256/ \
  --annotation_path /data/face_256/class_map.csv \
  --label Height --type regression --nb_classes 1 \
  --epochs 100 --early_stop 12 \
  --blr 1e-2 --weight_decay 0.05 \
  --output_dir runs/Height-mlp
```

## Pretraining

The released backbone is a Swin-L (patch 4, stride-16 tokens, 75 % uniform masking,
base lr 1e-4) pre-trained with UM-MAE in three stages — ImageNet-22K → VGGFace2-HQ →
clinical facial photographs. The launcher below is the 8-GPU reference setup
(512 × 512 input, 32 × 32 mask grid); the exact settings of the released checkpoint
are recorded in `weights/backbone/config.json`. Reproducing this stage needs the full
pre-training corpora, so the launcher is kept as a reference; run it from a checkout of
this repository after editing the paths:

```bash
bash medicalfacefound/scripts/pretrain.sh
```

## Evaluation and analysis

`analysis/` holds the notebooks used for the paper's tables, figures and supplementary
tables. They are **not** part of the installed package and depend on the internal
`ppp_prediction` helper package (available from the authors) plus the shared paths in
`analysis/config.py`; their dependencies are listed in `requirements-analysis.txt`.

| Notebook | Content |
| :-- | :-- |
| `01-Table1.ipynb` | Table 1: cohort characteristics |
| `02-ModelPerformance.ipynb` | Biomarker prediction performance |
| `03-DiseaseRiskEvaluationModel.ipynb` | Clinical utility / disease risk models |
| `04-APP-Evaluation.ipynb` | Smartphone selfie predictions |
| `05-GeneticsEvaluation.ipynb` | Comparison with polygenic risk scores |
| `06.1`–`06.5` `Plot-Part*.ipynb` | Main and supplementary figures |
| `07-SupplementaryTable.ipynb` | Supplementary tables |

### External robustness evaluation

The `medicalfacefound/robustness/` module evaluates paired photographs under
changes in acquisition conditions. See [ROBUSTNESS.md](ROBUSTNESS.md) for dataset
preparation, protocols and commands. This workflow is documented separately from
the notebooks used for the paper's main analyses.

## Research web application

The repository includes an optional web interface and FastAPI service for photo
collection, biomarker inference and heatmap visualisation. The service reuses the
same face-cropping and prediction functions as the Python API.

After installing the service dependencies and preparing the RetinaFace and
biomarker checkpoints, run from the repository root:

```bash
bash start_service.sh --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) for the web application;
interactive API documentation is available at `/docs`. See the
[service guide](README-service.md) for configuration, data storage, access control
and backups, and the [frontend guide](README-ui.md) for page and asset customisation.

## Repository structure

```text
MedicalFaceFound/
├── medicalfacefound/
│   ├── inference/              # Face preprocessing, checkpoint loading and CLI
│   ├── utils/                  # Model architectures, datasets and training utilities
│   ├── main_pretrain.py         # Self-supervised pretraining
│   ├── main_finetune.py         # Task-specific fine-tuning
│   ├── scripts/                # Training launchers
│   ├── robustness/             # Paired external-data evaluation
│   └── service/                # Research web application and HTTP API
│       └── static/             # Frontend pages, scripts, styles and assets
├── analysis/                   # Paper analysis notebooks
├── configs/                    # Evaluation configurations
├── tests/                      # Service and evaluation tests
├── weights/                    # Local checkpoints (not tracked)
├── data/                       # Local research data and service state (not tracked)
├── start_service.sh             # Web application launcher
├── run_robustness.sh            # Robustness evaluation launcher
├── environment-service.yml     # Conda environment for the web application
├── pyproject.toml              # Package metadata and dependencies
├── README-service.md           # Service deployment and API documentation
├── README-ui.md                # Frontend maintenance
├── ROBUSTNESS.md               # External evaluation protocol
├── LICENSE
└── THIRD_PARTY_NOTICES.md
```

## Data access

The training data (facial photographs, clinical records, genotypes) are **not**
distributed. To replicate the paper, request access by email to
**[xutingfeng@big.ac.cn](mailto:xutingfeng@big.ac.cn)**, providing your name,
affiliation, intended use and the files you need. Data are shared only in compliance
with the applicable ethics approvals and data-use agreements.

## Citation

If you use MedicalFaceFound in your research, please cite:

```bibtex
@article{xu2026medicalfacefound,
  title   = {A Facial Foundation Model for Clinical Biomarker Prediction and Real-World Mobile Deployment},
  author  = {Xu, Tingfeng and Xu, Huixuan and Lin, Li and others},
  journal = {Advanced Science},
  year    = {2026},
  pages   = {e77861},
  doi     = {10.1002/advs.77861}
}
```

## License

- **Code** (this package, including the training loop adapted from UM-MAE):
  **CC BY-NC 4.0** — non-commercial use, share and modify with attribution. See
  [`LICENSE`](LICENSE) and [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
- **Model weights**: distributed separately from this code; their license will be
  published together with the weights.
- **Article**: see the [publisher page](https://doi.org/10.1002/advs.77861).

The weights are **not a medical device** and must not be used for diagnosis,
treatment, surveillance or re-identification.

## Contact

Questions and collaboration: **[xutingfeng@big.ac.cn](mailto:xutingfeng@big.ac.cn)**
