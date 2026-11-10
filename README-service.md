# 本地研究采集网站与模型 API

网站服务代码位于 `medicalfacefound/service/`，直接复用本仓库
`medicalfacefound/inference/face.py` 与 `predict.py`。人脸检测为 RetinaFace，
使用原有 `detect_faces → square_box`（1.2 倍）`→ crop_square`（256×256），
指标推理继续使用 `load_task → predict_values → to_model_input`，不另行实现模型。
质量检查仅包裹这些函数，检查单人脸、取景余量、亮度及模糊程度；不声称能判断遮挡、
照片真实性、所有姿态或临床适用性。这些启发式阈值仍需根据项目采集样本评估。

前端页面位于 `medicalfacefound/service/static/`，随本仓库一起分发；默认无需设置
`MFF_FRONTEND_DIR`。数据库仍可使用 `MedicalFaceFound_api/data/medicalface.sqlite3`，
`MedicalFaceFound_api/start_service.sh` 仍会把页面、后端和数据库连接到同一个服务。
本次没有改动图片压缩、视频字幕、部署拆分或并发策略。

## conda 环境

仅通过 conda 安装依赖：

```bash
conda env create -f environment-service.yml
# 已有环境可用 conda env update -n MedicalFaceFound_api -f environment-service.yml
conda install -n MedicalFaceFound_api ./tools/conda-packages/retina-face-0.0.19-local_pytorch_0.conda
conda activate MedicalFaceFound_api
```

当前镜像的 conda-forge 只提供 RetinaFace 0.0.18，而仓库要求 >=0.0.19。
仓库附带的本地 conda 包由官方 0.0.19 wheel 原样封装，未修改 Python 源代码，
运行依赖选择官方支持的 PyTorch 后端，不使用 pip 安装。构建脚本为
`tools/package_retina_conda.py`，使用 conda base 环境自带的 conda-package-handling。
原始 wheel SHA-256：`117c528129963ee6b3c9b3b36991ef11e9f76586868d46132ff7b47e0cbd761c`。
来源：https://pypi.org/project/retina-face/0.0.19/ ，包内保留上游 MIT 许可。

RetinaFace 官方权重 `retinaface.pth` 放在
`weights/retinaface-cache/.deepface/weights/retinaface.pth`，来源：
https://github.com/serengil/deepface_models/releases/download/v1.0/retinaface.pth 。
服务默认设置 `DEEPFACE_HOME=weights/retinaface-cache` 和
`DEEPFACE_BACKEND_ENGINE=pytorch`。可以显式设置环境变量覆盖，前提是安装对应后端依赖。
首次部署应提前准备检测器权重，避免在用户请求中下载。指标权重仍为
`weights/tasks/<任务>/config.json` 与 `model.safetensors`。

## 启动与管理

```bash
python -m medicalfacefound.service \
  --database "$HOME/Desktop/MedicalFaceFound_api/data/medicalface.sqlite3"
```

也可运行 `MedicalFaceFound_api/start_service.sh`。默认地址 http://127.0.0.1:8000 。
`MFF_FRONTEND_DIR` 可覆盖默认页面目录；`MFF_WEIGHTS_DIR`、`MFF_TASKS`、`MFF_DEVICE`
继续控制指标目录、开放任务、运行设备。
模型仍串行调用，最多缓存一个指标模型。

- 采集：`/ui-assets/capture.html`
- 内部管理：`/admin`
- 用途说明：`/ui-assets/privacy.html`
- API：`/docs`

管理员密钥默认在数据库旁的 `admin-access.key` 中自动生成（权限 0600），
**不会显示在服务日志、公开页面或 API 中**。由获授权人员从本机读取后登录。
也可用至少 32 字符的 `MFF_ADMIN_TOKEN` 配置。前端仅在当前页面内存保留密钥；
刷新或退出需重新登录。管理页面支持日期筛选、失败分析、删除申请、照片预览、
CSV 导出与手动备份。所有管理 API 均检查 Bearer 密钥。

## 采集与追溯

1. 选图、拍照和初始原图预览均在浏览器本地完成。
2. 主动点击“检查照片”会临时上传，服务执行原有 RetinaFace 裁剪及质量检查，不写数据库。
3. 确认完整原图和人脸图，填写资料并同意当前用途版本后才能保存；服务端重新检查图片。
4. 同时保存原始文件字节、实际模型输入 PNG、裁剪范围、质量结果、同意版本及时间。
5. 使用采集编号调用分析，结果关联原记录；保存模型权重声明校验值、配置校验值、
   预处理版本、分析时间及状态。成功结果重复请求会复用，失败可仅重试分析。
6. 浏览器生成提交编号，服务校验内容摘要，重复发送同一提交不会生成新记录。
   同一提交编号修改资料会返回 409。
7. 每条新记录带有随机访问凭证，数据库仅保存其哈希；查报告、发起分析或删除申请均验证。
   凭证不写入下载报告、不放 URL。当前页面离开后可凭采集编号联系研究团队，经核实处理。

报告可下载为独立 HTML，用浏览器打印为 PDF。报告没有虚构参考区间或健康评分。
原始照片可能含 EXIF 信息；管理预览会重新编码，但数据库保留用户提交的原始文件。

## 数据库与备份

旧 `captures` 表通过增加可空字段迁移，旧照片和资料保留；不伪造旧记录的同意版本、
质量结果或分析输入。旧记录仍能在管理页面查看，不能直接用缺失的裁剪图发起新分析。
启动时会先用 SQLite backup API 保存一致性备份，再执行迁移。
手动备份也使用此 API，备份在数据库旁的 `backups/`，目录权限 0700，文件 0600。

用户可在结果页申请删除。申请后停止新分析；管理员输入完整采集编号再确认，
即可删除当前记录及其关联结果。正在分析的记录暂不允许删除。
查看详情、导出、备份、删除写入 `admin_events`；访问密钥不写入事件表。
**历史备份不会随单条记录自动删除**，当前没有自动保留期清理。研究团队须在正式招募前
明确数据保留期限、备份清理方式与正式知情同意材料，并更新用途说明。

## 接口

- `GET /ready`：可用指标、中文说明、照片检查状态和同意版本。
- `POST /v1/photos/quality`：multipart `file`，返回检查与临时人脸预览。
- `POST /v1/captures`：原图、基本资料，以及 `consent=true`、`consent_version`、
  `request_id`、`access_token`；与旧版相比增加这些必填字段，并强制质量检查。
- `POST /v1/captures/{id}/predictions/{task}`：记录凭证 Bearer，关联预测或复用成功结果。
- `GET /v1/captures/{id}/report`：记录凭证 Bearer，获取结果，不返回原图或凭证。
- `POST /v1/captures/{id}/deletion-request`：记录凭证 Bearer，提交删除申请。
- `POST /v1/models/{task}/predict`：保留直接预测入口，但同样强制原有 RetinaFace 检测及质量检查；
  不再允许 `pad/none` 绕过检查。该入口不保存记录；网站使用上述关联接口。
- `/v1/admin/*`：管理员 Bearer；列表、详情、图像、导出、备份、确认删除。

临时 FAHR-FaceAge 对照可通过 `MFF_ENABLE_FAHR_FACEAGE=1 bash start_service.sh` 启用。
在管理后台打开有裁剪图的采集详情，点击「运行年龄预测与热图」。
`POST /v1/admin/captures/{identity}/fahr-faceage` 使用管理员 Bearer 凭证，
返回年龄值、Grad-CAM（`explanation`）及论文方法的单图注意力（`attention`）。
后者提供最后一层 CLS 对图像块的跨头平均权重（`patch_weights`，7×7），
并双线性插值为 448×448 PNG 预览（`overlay`）。预览采用当前页面的配色与叠加方式，
论文的队列平均和标准人脸投影属于另一步分析。
结果随响应返回，数据库不保存这项临时对照。启动脚本默认复用 `fahr-face` conda 环境、
本地 `external/FAHR-Face` 源码和桌面的 `fahr_faceage.pth`。

## 验证

```bash
python -m unittest discover -s tests -v
```

测试使用临时数据库，验证质量拦截、与原有 FaceCropper 的一致性、同意校验、
提交幂等、分析失败重试、成功复用、记录级权限、管理员权限、删除与备份。
HTTP 测试模拟模型计算；实际模型及检测器验证另外使用概念图片，不能替代临床验证。
