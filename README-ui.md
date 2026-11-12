# 首页与采集页面

本文介绍研究网站的页面和素材配置。部署与接口说明见 [README-service.md](README-service.md)，
研究方法见 [项目 README](README.md)。前端目录为 `medicalfacefound/service/static/`：

```bash
cd /path/to/MedicalFaceFound
bash start_service.sh
```

- 首页：`http://127.0.0.1:8000/`，研究介绍、宣传视频、论文与研究单位。
- 采集页面：`http://127.0.0.1:8000/ui-assets/capture.html`，照片采集和基本信息填写。
- 首页素材配置：`medicalfacefound/service/static/site-content.json`。

## 统一配色

主页和采集页采用临床蓝白方案，公共色值集中在 `medicalfacefound/service/static/theme.css`：冷白底色 `#F6F8FC`、深蓝文字 `#142C48`、蓝色强调 `#2563EB`、浅蓝色块 `#EAF1FF`。各页面样式引用同一组变量；成功、错误与连接状态保留独立的语义色。

`--concept-saturation` 控制面部与全身概念图的显示饱和度，当前为 `0.28`。该效果只用于概念图；单位 Logo、视频以及用户采集或上传的照片保持原色。更新样式时同步调整页面样式链接的版本参数，以避免浏览器继续使用旧缓存。

## 加入宣传视频

宣传视频位于 `static/assets/video/medicalfacefound-introduction.mp4`（1920×1080，约 2 分 16 秒），封面为 `medicalfacefound-poster.jpg`。页面支持播放、暂停、进度跳转及浏览器原生全屏控件，点击后播放。

将视频与封面放进 `static/assets/video/`，修改配置的 `video`：

```json
{
  "src": "/ui-assets/assets/video/introduction.mp4",
  "poster": "/ui-assets/assets/video/poster.jpg",
  "captions": "/ui-assets/assets/video/captions.zh.vtt",
  "title": "走近 MedicalFaceFound"
}
```

`poster` 和 `captions` 可留空。支持本地静态路径或 HTTP(S) 地址。
配置后自动展示带播放控件的视频，不自动播放。`src` 为空时展示“宣传视频 · 即将上线”；
加载失败时回到占位画面并提示无法播放。视频建议使用 MP4（H.264/AAC）。

## 替换单位 Logo

将透明底 SVG、PNG 或 WebP 放进 `static/assets/logos/`，修改 `institutions` 数组：

```json
{
  "name": "单位名称",
  "subtitle": "英文名称或补充名称",
  "logo": "/ui-assets/assets/logos/institution.svg",
  "url": "https://example.org"
}
```

数组顺序即页面顺序，可增删单位；`url` 可留空。没有图片或图片加载失败时显示 Logo 预留位。
已加入基因组所（国家生物信息中心）、计算所、中国科学院大学及北京安贞医院的 Logo，点击整张单位卡片可打开官网。
素材保存在本地，保留原图颜色和比例；下载来源与版本见本仓库 `medicalfacefound/service/static/assets/logos/SOURCES.md`。
单位名称依据论文作者单位设置，可按最终展示需求调整；静态备用卡片位于 `index.html`，调整单位时建议同步修改。
配置每次打开首页时重新读取，修改后刷新页面即可，无需重启后端。

## 研究内容来源

首页依据 MedicalFaceFound 仓库的 README 和论文页面整理：
[A Facial Foundation Model for Clinical Biomarker Prediction and Real-World Mobile Deployment](https://doi.org/10.1002/advs.77861)，Advanced Science，2026。

首页中的面部图为 AI 生成的三维概念视觉（`assets/face-sculpture.png`），不是真实预测结果。
采集页保持原有 API 与数据库流程。

## 概念图与交互

- 全身系统概念图：`assets/body-systems.png`，由 AI 生成；提示词保存在 `assets/body-systems.prompt.txt`。图中器官仅作示意，非精确解剖图或个体分析结果。
- 首页八类系统卡片可以切换研究说明；器官区域与全身性指标分别呈现。说明与高亮位置维护在 `home.js` 的 `systems` 中。
- 研究方法展示三阶段自监督预训练；论文卡片展示研究流程和 README 中报告的队列结果。
- 导航支持吸顶、章节高亮与手机菜单；减少动态效果的系统偏好会关闭过渡和入场动画。
- `capture-modern.css` 统一采集页字号、输入控件、步骤反馈和图片风格；采集业务脚本与提交 API 保持原实现。

## 外部鲁棒性验证

`bash run_robustness.sh audit` 核对三个外部数据集，`bash run_robustness.sh run` 调用 MedicalFaceFound 包评估全部已就绪的本地模型。默认输出到本仓库的 `output/robustness/primary/`，支持缓存续跑。完整方法、抽样验证和扩展 FEI 分析命令见 [ROBUSTNESS.md](ROBUSTNESS.md)。
