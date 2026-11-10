# 三个外部人脸数据集的配对鲁棒性验证

使用本包 `load_task`、`predict_values` 和已发布的 `config.json`/`model.safetensors`，不训练、不调节模型权重。当前本地模型为 Age、HDLC、Hb；之后新增任务目录会自动加入。原始图片只读，缓存和报告写到 `output/robustness/`。

## 运行

当前机器的 Python 是 `/Users/tingfeng/miniforge3/envs/MedicalFaceFound_api/bin/python`。

```bash
cd /Users/tingfeng/Desktop/MedicalFaceFound_api

# 仅核对数据配对、完整模型目录，无推理
bash run_robustness.sh audit --output /Users/tingfeng/MedicalFaceFound/output/robustness/audit

# 三个数据集、全部当前模型；每个条件随机抽取5对，验证整个流程
bash run_robustness.sh run --limit-per-group 5 --output /Users/tingfeng/MedicalFaceFound/output/robustness/smoke-final

# 全量主分析：1465对、2730张唯一照片、每个本地模型10个条件
bash run_robustness.sh run --output /Users/tingfeng/MedicalFaceFound/output/robustness/primary

# 完整FEI压力测试：所有其余13种拍摄条件分别与11号正脸配对
bash run_robustness.sh run --protocol extended --output /Users/tingfeng/MedicalFaceFound/output/robustness/extended

# 只分析某个数据集/模型；可重复 --dataset 或 --task
bash run_robustness.sh run --dataset makeup --task Age --output /Users/tingfeng/MedicalFaceFound/output/robustness/makeup-age

# 比较我们包的方形人脸裁剪方式；其余检测设置保持一致
bash run_robustness.sh run --preprocess package --output /Users/tingfeng/MedicalFaceFound/output/robustness/package-crop

# 单独重画报告，不重复预测
bash run_robustness.sh report --output /Users/tingfeng/MedicalFaceFound/output/robustness/primary
```

另一台机器可在仓库根目录运行 `python -m medicalfacefound.robustness`，或安装 `medicalfacefound[robustness]` 后使用 `mff-robustness`。用 `--data-root`、`--weights-dir`、`--detector-home` 改目录。依赖见 `requirements-robustness.txt`。本机已补齐 SciPy、Matplotlib、RetinaFace 0.0.19；使用其 PyTorch 后端，无需 TensorFlow。旧 `cadFace_deploy` 依赖不是这套流程的运行要求。

RetinaFace 权重必须预先放在 `--detector-home/.deepface/weights/retinaface.pth`，避免长任务中隐式联网下载。本机路径是 `weights/retinaface-cache/.deepface/weights/retinaface.pth`，来源是 [RetinaFace 官方权重](https://github.com/serengil/deepface_models/releases/download/v1.0/retinaface.pth)。

默认 CPU、4线程、batch=4，一次只加载一个约780MB的模型。CUDA 可加 `--device cuda --half --batch-size 16`；Mac 的 MPS 是否可用取决于 PyTorch 环境，不自动切换设备。

## 和论文的对应关系

已阅读用户提供的正式发表版本 `PIIS2589750026000798 (1).pdf`（17页），[DOI](https://doi.org/10.1016/j.landig.2026.101056)。第12页明确报告同一人的整形前后、化妆前后、拍摄条件变化；第17页链接这三个数据集和作者代码。正式版把细节指向独立 appendix 第5页，该附录未包含在收到的PDF里。

配对差值、绝对差值、双侧 Wilcoxon signed-rank 方法依据 [作者预印本补充方法，第26页](https://arxiv.org/pdf/2506.14909)。RetinaFace 对齐、仅接收单人脸参考 [作者公开代码](https://github.com/AIM-Harvard/FAHR-Face/blob/main/other/face_crop_align.py)。本流程是将同类验证用于 MedicalFaceFound，不能称为逐项精确复现正式版附录。

| 数据集 | 配对方向 | 本地完整配对数 |
|---|---|---:|
| HDA Eyebrow | `_a` 术后 − `_b` 术前 |128|
| HDA Eyelid | 同上 |131|
| HDA Facelift | 同上 |98|
| HDA FacialBones | 同上 |108|
| HDA Nose | 同上 |174|
| Makeup | `make_up.csv` 指定的化妆 − 素颜 |26|
| FEI pose_03_vs_05 | 03 − 05 |200|
| FEI pose_07_vs_05 | 07 − 05 |200|
| FEI smile_vs_neutral | 12 − 11 |200|
| FEI dark_vs_light | 14 − 13 |200|

HDA 共639对，而预印本描述638对，其有效检测样本数还会更小。本流程按本地文件逐一建清单，不人为删样本凑论文数量。解析数字/字母编号和 `.jpg.png` 双扩展名；subject由目录与原始编号组成，不跨手术合并同名编号。HDA配对ID不等于经过核实的全库人物ID；置信区间假设同一条件内不同配对ID为不同受试者，如果后续发现重复人物，应先校订身份映射再分析。

全量审计已确认：`Facelift/64_a.jpg` 与 `77_a.jpg`、`64_b.jpg` 与 `77_b.jpg` 分别字节完全相同。统计现在按每个条件内的有序原图SHA256配对去重，保留64号，77号记为 `duplicate_pair`；HDA因此是639个原始配对记录、638个唯一配对。`n_expected` 保留原始分母，`n_duplicate_pairs` 单列重复数量，重复记录不进入检验、CI或一致性指标。相同基准图与不同变体的比较，以及不同条件的同图比较，不会被错误合并。

已有预测可运行 `bash run_robustness.sh reanalyse --output <原输出目录>`，直接从 `pairs.csv`、`predictions.csv`、`image_qc.csv` 重新去重、计算统计并画图，不重新推理。原始预测文件不变；`run.json` 保留原推理来源，另记录统计修订代码及输入文件哈希。

FEI姿态编号基于本地联系图的工作映射，**论文未公开原始文件编号，不能保证这些编号精确对应±22.5°**。配置 `configs/robustness-fei-primary.json` 可通过 `--fei-mapping` 更换。`extended` 不依赖姿态角度命名，覆盖全部2800张FEI照片，包含3265对、4130张唯一图片。FEI同一人不同条件分别分析，不池化成相互独立的样本。

## 预处理与失败处理

默认 `retina-align`：EXIF旋转→RGB解码→RetinaFace单人脸检测→眼部关键点对齐→256×256输入→包内ImageNet归一化。`package` 使用包内 `square_box`/`crop_square`、扩展比例1.2，不做关键点旋转。

**默认检测尺度明确固定为长边最多640像素，禁止RetinaFace再次上采样**。检测坐标及关键点映射回原图后再裁剪，保留原始图像细节。原因：本机PyTorch检测后端试跑发现，默认上采样会将部分占图较大的人脸放到难以检测的尺度；例如Nose/41_b的最高置信度从默认上采样的0.283，变为原尺度的0.995。这个统一尺度策略与论文未明确公开的尺度参数有差异，记录在报告中，不为个别照片切换方法。若需直接检查当前RetinaFace默认尺度，使用 `--detector-max-side 0 --allow-upscaling`，单独输出作为敏感性分析。

固定置信度0.9。未检出、多人脸、解码错误均记录，默认不以整张图或其他检测器替代。`--multi-face highest-confidence` 需显式指定，建议单独做敏感性分析。只有一对中两张图都成功才进入该模型/条件的配对统计，但始终保留原始分母、两端失败率和原因。程序性错误或某个条件无有效配对会输出 `partial` 并返回退出码2；正常完成为0，允许存在已明示的部分检测排除。

## 指标与解释

- 论文对应：平均差值、差值SD、平均绝对差值、双侧配对Wilcoxon。
- 补充：配对受试者 bootstrap 95% CI（默认2000次）、差值RMSE、绝对差值P95、Pearson/Spearman、Lin concordance、ICC(A,1)、Bland–Altman图和描述性一致性界限。
- 多重比较：当前报告内所有模型×条件作为一个BH校正家族；原始P与校正Q均输出。不要通过拆分命令规避整体多重比较。
- 回归任务另给 `MAD / training target SD`，便于检查量纲；这个标准化量不是临床可接受阈值。不同任务单位不同，不能按原始MAD直接排名。
- 二分类任务使用包内正类概率。`--thresholds` 可提供 `{"TaskName":{"decision_threshold":0.5,"absolute_tolerance":0.05}}`，输出阈值翻转率和容许变化范围内比例。示例阈值不能当作经验证的临床阈值，不提供配置时不自动判定“通过”。
- 不把高相关性或P>0.05当作鲁棒性/等效性证明；常数输出的相关性和ICC留空。没有疾病标签，不能计算疾病AUC、敏感度、特异度或证明临床有效性。检测失败也属于整体系统的鲁棒性结果。

## 输出、续跑与新增模型

`audit.json` / `pairs.csv`：完整配对审计。`image_qc.csv`：逐图检测状态、置信度、坐标、源文件哈希。`predictions.csv`：逐模型逐图预测。`paired_results.csv`：配对差值及排除原因。`summary.csv/json`：每模型每条件统计。`run.json`：模型SHA256、配置、实际导入的库版本、代码指纹、随机种子、方法来源与局限。`report.html`：可直接打开的本地报告；`figures/`：PNG和PDF图。

缓存按源图片内容、检测权重、预处理配置、代码指纹、依赖版本、模型权重和模型配置隔离。中断后重跑相同命令复用已完成记录；只有实际需要的模型才加载。检测失败也缓存，`--retry-failures` 重试失败图片和预测。改阈值、图片、代码或权重会产生新缓存，不沿用不匹配的预测。bootstrap、报告路径或配对选择变化不改变同配置的图像预测。**源代码指纹目前覆盖整个robustness/inference/utils，因此改报告代码也会保守地使缓存失效。**

新增 `weights/tasks/<Task>/config.json` 和 `model.safetensors` 后重跑即可。不完整目录、校验和不符、非标量回归或非二分类任务不会被悄悄忽略，会列入问题清单。重复运行同一output目录会更新该报告，建议完整分析、抽样、不同预处理各用独立output目录；不要同时写同一output目录。

测试：`python -m unittest discover -s tests -p test_robustness.py -v`。真实模型抽样报告必须保留“冒烟测试”标记，不用于宣称最终鲁棒性结论。
