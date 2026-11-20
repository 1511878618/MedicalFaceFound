# 研究采集网站与模型 API

本文介绍研究网站的部署、配置和数据管理。模型方法、推理和训练说明见
[项目 README](README.md)。下文命令均从仓库根目录执行。

网站服务代码位于 `medicalfacefound/service/`，直接复用本仓库
`medicalfacefound/inference/face.py` 与 `predict.py`。人脸检测为 RetinaFace，
使用原有 `detect_faces → square_box`（1.2 倍）`→ crop_square`（256×256），
指标推理继续使用 `load_task → predict_values → to_model_input`，不另行实现模型。
质量检查仅包裹这些函数，检查单人脸、取景余量、亮度及模糊程度；不声称能判断遮挡、
照片真实性、所有姿态或临床适用性。这些启发式阈值仍需根据项目采集样本评估。

前端页面位于 `medicalfacefound/service/static/`，随本仓库一起分发；默认无需设置
`MFF_FRONTEND_DIR`。默认数据库为 `data/medicalface.sqlite3`，运行数据和模型权重
独立于版本控制，需在部署环境中准备。

## conda 环境

可使用提供的 conda 配置安装服务依赖：

```bash
cd /path/to/MedicalFaceFound
conda env create -f environment-service.yml
conda activate MedicalFaceFound
```

更新已创建的环境可运行 `conda env update -n MedicalFaceFound -f environment-service.yml`。
启动脚本优先使用 `MFF_PYTHON` 指定的解释器，其次是已激活的非 `base` conda 环境，
再查找默认 Miniforge 环境和 PATH 中的 Python。使用自定义环境时，建议显式激活或指定：

```bash
MFF_PYTHON=/path/to/environment/bin/python bash start_service.sh
```

RetinaFace 官方权重 `retinaface.pth` 放在
`weights/retinaface-cache/.deepface/weights/retinaface.pth`，来源：
[官方权重下载](https://github.com/serengil/deepface_models/releases/download/v1.0/retinaface.pth)。
服务默认设置 `DEEPFACE_HOME=weights/retinaface-cache` 和
`DEEPFACE_BACKEND_ENGINE=pytorch`。可以显式设置环境变量覆盖，前提是安装对应后端依赖。
首次部署应提前准备检测器权重，避免在用户请求中下载。指标权重仍为
`weights/tasks/<任务>/config.json` 与 `model.safetensors`。

## 启动与管理

```bash
cd /path/to/MedicalFaceFound
bash start_service.sh

# 也可在已配置好依赖的环境中直接启动
python -m medicalfacefound.service

# 自定义监听地址、端口或数据库（命令行参数优先于环境变量）
bash start_service.sh --host 127.0.0.1 --port 8000 --database /path/to/medicalface.sqlite3
```

默认地址 [http://127.0.0.1:8000](http://127.0.0.1:8000)。启动脚本以自身位置确定仓库，
可从其他目录使用绝对路径调用；直接使用 Python 模块时应在仓库根目录运行，或先安装本包。
模型仍串行调用，最多缓存一个指标模型。

- 首页：`/`
- 采集：`/ui-assets/capture.html`
- 个人账号与历史记录：`/ui-assets/records.html`
- 内部管理：`/admin`
- 用途说明：`/ui-assets/privacy.html`
- API：`/docs`

后台启动与检查（从仓库根目录运行，先确保端口没有其他服务占用）：

```bash
mkdir -p data
chmod 700 data
umask 077
nohup bash start_service.sh > data/server.log 2>&1 &
echo $! > data/server.pid
curl --noproxy '*' http://127.0.0.1:8000/health
curl --noproxy '*' http://127.0.0.1:8000/ready
tail -f data/server.log
```

停止前先用 `ps -p "$(cat data/server.pid)" -o command=` 确认是本服务，
再运行 `kill "$(cat data/server.pid)"`，等待退出后重启。
前台启动则使用 Ctrl+C；前台模式的日志默认输出到终端。
`/health` 返回 `ok` 只表示 HTTP 服务可用；`/ready` 的 `quality_ready`、
`inference_ready`、`available_models`、`missing_dependencies` 和 `load_errors`
用于进一步检查依赖与模型目录。实际加载权重发生在首次推理时。

| 环境变量 | 默认值 / 用途 |
| --- | --- |
| `MFF_PYTHON` | 覆盖启动脚本使用的 Python |
| `MFF_BACKEND_DIR` | 启动脚本所在仓库；仅启动脚本使用 |
| `MEDICALFACE_DB_PATH` | `<仓库>/data/medicalface.sqlite3` |
| `MFF_FRONTEND_DIR` | `<仓库>/medicalfacefound/service/static` |
| `MFF_WEIGHTS_DIR` | `<仓库>/weights` |
| `MFF_TASKS` | 默认发现完整模型目录；可用 `Age,HDLC,Hb` 限定 |
| `MFF_DEVICE` | `cpu`，可显式设为环境支持的设备 |
| `MFF_ADMIN_TOKEN` | 可选，至少 32 字符；否则读取或生成本地密钥 |
| `MFF_ENABLE_FAHR_FACEAGE` | 启动脚本中设为 `1` 后配置可选年龄对照 |
| `MFF_ENABLE_CAM_COMPARISON` | 设为 `1` 启用管理端热图方法对照 |

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

默认数据目录为仓库根目录下的 `data/`：

- `medicalface.sqlite3`：采集资料、原图、裁剪图、预测、已保存热图和管理设置。
- `admin-access.key`：首次启动时生成的管理员访问密钥。
- `backups/`：启动前与管理端手动生成的数据库备份。
- `server.log`：使用本文后台启动命令时写入的服务日志。

这些文件以及 `weights/`、`external/` 已加入 `.gitignore`。数据库、密钥和备份保存在部署环境中，
不要加入版本控制。若使用 `--database` 或 `MEDICALFACE_DB_PATH`，密钥和备份也会随数据库位置改变。

后续迁移应先停止写入服务，再使用 SQLite backup API 或管理端备份，
并核对 `PRAGMA integrity_check`、记录数及图片/预测内容；服务运行时不要只复制 `.sqlite3`
主文件，未 checkpoint 的事务可能还在 `-wal` 中。恢复时先停止服务，保留当前数据库，
使用备份替换数据库并一并保留管理员密钥，再重启验证。

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
本仓库 `external/FAHR-Face` 源码及 `weights/fahr-face/fahr_faceage.pth`。
三者均需提前准备，可用 `MFF_FAHR_FACEAGE_PYTHON`、`MFF_FAHR_FACEAGE_SOURCE`、
`MFF_FAHR_FACEAGE_CHECKPOINT` 覆盖。新克隆仓库不包含这些本地资产。

```bash
# 启用可选的年龄与热图方法对照
MFF_ENABLE_FAHR_FACEAGE=1 MFF_ENABLE_CAM_COMPARISON=1 bash start_service.sh
```

## 前端维护与验证

首页配置为 `medicalfacefound/service/static/site-content.json`，公共配色为 `theme.css`。
视频、Logo、概念图与页面操作说明见 [README-ui.md](README-ui.md)。静态文件修改后刷新浏览器；
Python 代码或环境变量修改后重启服务。

```bash
# 使用配置好服务依赖的 Python；测试使用临时数据库，不写入本地采集库
python -m unittest discover -s tests -p 'test_service.py' -v
python -m unittest discover -s tests -p 'test_quality.py' -v
```

接口测试替换了部分检测/推理实现，验证采集、权限和数据保存流程，不证明真实模型预测性能。


## 个人记录与科研参与

个人页面支持账号密码注册、登录和退出；账号名为 3–40 位字母、数字、下划线或连字符，
密码为 10–128 字符。会话使用 HttpOnly、SameSite=Strict Cookie，HTTPS 下设置 Secure，
有效期为七天。公开部署应使用 HTTPS。当前没有邮件、短信或自助密码找回功能。
登录后新采集的记录关联当前账号；历史匿名记录不会自动归入账号。

基础服务同意保留，科研参与合并为一条自愿选择，明确涵盖本项目研究、评估及模型开发训练；
旧记录不自动扩大授权，需主动确认新版科研说明。每条记录可单独修改授权，撤回科研同时撤回训练并删除
该记录实测值和补充临床信息。撤回后不再进入相应用途的新导出，已导出的副本和历史备份需要研究团队另行处理。
实测值记录指标、单位、日期和来源，仅在科研同意后接受；页面差值需对应单位一致。
用户可确认完整采集编号直接删除自己的记录，关联预测、实测值及授权事件同步删除。

结果表列出论文 62 项指标及独立冠心病模型占位，共 63 项。可推理范围以 `/ready` 为准；
本机已补齐论文 62 项权重；独立冠心病模型仍待接入。待接入项目不产生预测。性能来自补充表 S5/S6，
不将 Pearson r 的平方替代论文 R²，也不将论文组合模型 AUC 用于独立冠心病模型。
WBC、PCT 单位仍待核对；FBG 指纤维蛋白原。网站结果仅供模型预测与科研参考。

新增接口：

- `POST /v1/account/register`、`POST /v1/account/login`：JSON 账号密码。
- `POST /v1/account/logout`、`GET /v1/account/me`：退出及当前用户。
- `GET /v1/me/captures?offset=0&limit=20`：当前账号历史记录。
- `PUT /v1/captures/{id}/research-consent`：`research`、`training`、`version`。
- `PUT /v1/captures/{id}/observations`：`model`、`value`、`unit`、`measured_on`、`source`。
- `PUT /v1/captures/{id}/clinical-information`：可选病史、用药、家族史、吸烟、饮酒和其他说明，仅在当前版本科研授权后接受。
- `DELETE /v1/captures/{id}/observations/{model}`：删除实测值。
- `DELETE /v1/captures/{id}`：JSON `confirmation` 必须等于完整采集编号。
- `GET /v1/admin/research-export?purpose=evaluation|training`：管理员按当前授权导出。

账号写请求携带 `X-MFF-Request: 1`；个人记录支持会话授权，匿名记录继续使用原记录 Bearer 凭证。
新增流程测试使用临时数据库：

```bash
python -m unittest discover -s tests -p 'test_product_workflow.py' -v
```

参考范围配置位于 `medicalfacefound/service/reference_ranges.json`，逐项保留来源、单位及适用条件。结果和下载报告共用展示逻辑，按成人性别显示；未成年人不套用成人区间。风险阈值与一般参考区间分别注明，模型输出不据此自动标记诊断。单位未确认或没有统一区间的项目仅显示说明。

## 对象档案与纵向记录

账号负责管理记录，测量对象单独保存。本人使用 `self`，未确认旧记录使用 `unknown`；
其他成员使用归属当前账号的独立 UUID。成员称呼仅用于本账号内管理，不建立跨账号共享或自动代理访问。
`GET/POST /v1/me/subjects` 列出/建立成员；`PUT /v1/captures/{id}/subject` 更正归属，
`GET /v1/me/captures?subject_id=...` 按对象分页。更正归属保留记录但重置科研授权。
历史数据迁移为待确认，不自动纳入本人趋势。记录删除同步更新列表、概览和趋势，历史备份仍独立保留。
趋势图预测点采用采集时间，实测点采用填写的检验日期；按单位分图，不连跨模型版本，
缺失值不补零。年龄、身高、体重及计算 BMI 来自每次采集资料。

### 后台按账号与成员浏览

后台保留单次测量详情，并提供账号目录、成员筛选和成员历史趋势。访客记录不自动归入账号；待确认归属的记录不进入成员趋势。管理员浏览不会修改记录归属或科研授权。

- `GET /v1/admin/participants?q=&limit=20&offset=0`：搜索并分页列出账号及记录数量，不返回密码或会话信息。
- `GET /v1/admin/participants/{id}/subjects`：该账号的本人、待确认及自定义成员与记录数量。
- 记录列表、普通导出与科研导出共同支持 `participant_id`、`ownership=all|account|guest`、`subject_id`，并保留日期、状态、标签筛选。
- 自定义成员须指定所属账号；`self` 在账号或访客范围内使用，避免将不同账号的本人数据混合。`unknown` 可用于全站待确认筛选。
- 科研和训练导出仍受当前有效授权限制，选择账号或成员不会扩大科研用途权限。

以上接口均要求独立管理员 Bearer 密钥；个人账号登录不会获得管理员访问权。
