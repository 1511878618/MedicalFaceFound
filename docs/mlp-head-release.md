# Downstream two-layer MLP release

This local release contains only moca_mci, ocad and diabetes. It reuses the shared frozen UM-MAE Swin-L backbone. It does not modify or replace the original full-model tasks/ or tasks.json.

## Output contract

- moca_mci: probability of MoCA-defined impairment, trained class 0. The training label class 1 is normal. The head weights retain their original class order; only the reported scalar selects class 0. This is not a MoCA score or a clinical diagnosis.
- ocad: probability of the positive obstructive-CAD class (trained class 1).
- diabetes: probability of the positive diabetes class (trained class 1). This is NOT the separate type_2_diabetes head.
- Outputs are research model scores, not calibrated clinical risk or incident-disease predictions. Multiple images are image-level outputs; take the arithmetic mean of their probabilities for a subject-level score. Do not average logits.

## Files and architecture

Place tasks_binary/ next to backbone/ under a weights root. tasks_binary mixes head-only MLP heads (moca_mci, ocad) with self-contained full models (Diabetes, Hypertension, Smoking, Drinking); each task has model.safetensors and config.json, and tasks_binary/tasks.json is the group index. Shared backbone tensors are not duplicated per task. The loader dispatches on each config's format field.

Pooled 1536-d features BEFORE the original fc_norm -> LayerNorm(eps=1e-5) -> Linear(1536,512) -> GELU -> Dropout(0.2) -> Linear(512,2). Inference uses eval mode; the original Swin fc_norm is Identity, avoiding double normalization.

Preprocessing: prepared RGB face crop, EXIF transpose when loaded from file, Resize(short side=256, bicubic), CenterCrop(256), ToTensor, ImageNet normalization. Already prepared crops do not require a new face detector pass.

CUDA uses fp16 autocast with fp32 parameters, matching cached-feature training evaluation. --half does not convert MLP parameters to fp16; this branch already controls autocast. CPU fp32 works but need not reproduce historical CUDA fp16 scores bit-for-bit. Historical cache extraction used batch 64; CUDA batch-size effects can produce small numerical differences.

## CLI (updated source/package required)

```bash
mff predict --input /path/to/prepared_crops --no-crop \
  --local-dir /path/to/weights --task-group tasks_binary --all-tasks \
  --device cuda --out predictions.csv
```

For one task, replace --all-tasks with --task moca_mci (or ocad/diabetes). Existing calls without --task-group still use the original tasks group. mff defaults to face detection unless --no-crop is supplied.

Release parts are loaded with --task-group: tasks (original panel, default), tasks_binary (the six calibrated endpoints below) and tasks_part3 (EF, mmse_score, moca_score). The former tasks_only_mlp and tasks_part2 folders were superseded by tasks_binary and archived, together with the models that were not part of the calibrated release (tasks_only_mlp/diabetes, tasks_part2/CAD_v3, tasks_part2/Hyperlipidemia).

## Calibrated scores and research risk tiers

Six task configs carry two optional blocks; models without them behave exactly as before.

- calibration: Platt-on-logit, `p_cal = sigmoid(a * logit(clip(p, eps, 1-eps)) + b)`, fitted on a pooled multicentre development cohort.
- stratification: ordered cutoffs with one more label than cutoffs, comparator `>=`.

| task | group | levels | cutoffs (calibrated probability) |
| --- | --- | --- | --- |
| moca_mci | tasks_binary | Very low / Low / Moderate / High | 0.161189, 0.421372, 0.607382 |
| ocad | tasks_binary | Very low / Low / Moderate / High | 0.629486, 0.810863, 0.947465 |
| Diabetes | tasks_binary | Very low / Low / Moderate / High | 0.280747, 0.417792, 0.514698 |
| Hypertension | tasks_binary | Very low / Low / Moderate / High | 0.476313, 0.653654, 0.780490 |
| Smoking | tasks_binary | Negative / Positive | 0.211287 |
| Drinking | tasks_binary | Negative / Positive | 0.435524 |

CSV keeps `file,task,value,unit` plus `value_calibrated` and `risk_tier` when the loaded config has the blocks; `value` remains the model's own event probability. Rows stay per image, so calibration and tiers are applied to each photo's probability. The analysis behind these cutoffs was defined on the per-visit mean of photo probabilities, so a photo-level tier is not arithmetically identical to a published patient-level tier; average `value` per subject first if patient-level labels are required.

These cutoffs were selected and evaluated on the same pooled development set: they are apparent development estimates, not independent validation, not incident risk, and not a clinical decision rule. The lowest tier is a relative score category and does not imply absence of disease. Drinking discrimination is near chance.

## Python

```python
from medicalfacefound.inference.face import load_image
from medicalfacefound.inference.predict import load_task, predict_values
model, cfg = load_task('moca_mci', local_dir='/path/to/weights',
                       task_group='tasks_binary', device='cuda')
rows = predict_values(model, cfg, [load_image('/path/to/crop.jpg')], device='cuda')
# rows[0] -> {'task','value','unit','value_calibrated','risk_tier'} for configured tasks
```

Remote resolution uses the same explicit task group, but this release has NOT been uploaded. The existing remote default repository cannot serve these new files until they are actually uploaded.

## Performance and limitations

See performance_by_center.csv (current saved test estimates, not recalculated), including n, n_pos, auc, auc_lo, auc_hi. The moca_mci rows retain original label coding for n_pos (normal=1); AUC and its interval are invariant when BOTH label and score are complemented. n_cases_output_event explicitly reports impairment counts. ALL is pooled internal+external testing, not purely external validation.

MoCA has relatively consistent external-center discrimination. OCAD varies substantially by center; pooled AUC must not be read as uniform external performance. Diabetes has weak external discrimination. These three tasks were selected by the project owner for research release, not by a new independent validation exercise. Packaging parity establishes faithful inference, not clinical validity, licensing/consent review or absence of training leakage.

## License and release status

Project code license: CC BY-NC 4.0 (see bundled LICENSE and THIRD_PARTY_NOTICES.md). This engineering bundle does not independently establish redistribution permission for every pretrained component or training-data consent; those remain release-owner checks. Local candidate only: no remote upload, version tag or public package release was performed.
