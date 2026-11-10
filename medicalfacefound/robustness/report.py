"""Local, self-contained HTML plus exportable scientific figures; no face uploads."""
from __future__ import annotations

import base64
import html
from pathlib import Path

import numpy as np


def write_report(output, metadata, summaries, paired):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    output = Path(output)
    figures = output / "figures"
    figures.mkdir(exist_ok=True)
    embedded = []
    for task in sorted({r["task"] for r in summaries}):
        rows = [r for r in summaries if r["task"] == task and r["n"]]
        if not rows:
            continue
        labels = [f"{r['dataset']}/{r['contrast']} (n={r['n']}/{r['n_expected']})" for r in rows]
        fig, axes = plt.subplots(1, 2, figsize=(14, max(4.8, len(rows)*.45)), layout="constrained")
        y = np.arange(len(rows))
        for ax, metric, low, high, title in [
            (axes[0], "mean_difference", "mean_difference_ci_low", "mean_difference_ci_high", "Signed shift: variant - baseline"),
            (axes[1], "mean_absolute_difference", "mad_ci_low", "mad_ci_high", "Mean absolute paired difference")]:
            values = np.array([r[metric] for r in rows])
            ax.scatter(values, y, color="#126e82", zorder=3)
            for i, r in enumerate(rows):
                if low in r:
                    ax.plot([r[low], r[high]], [i, i], color="#126e82", linewidth=2)
            ax.axvline(0, color="0.6", linewidth=.7)
            ax.set_yticks(y, labels if ax is axes[0] else [""]*len(rows)); ax.invert_yaxis()
            ax.set_title(title); ax.set_xlabel(rows[0].get("unit") or "model output units")
            ax.grid(axis="x", alpha=.2)
        fig.suptitle(f"{task} — paired stability with 95% bootstrap intervals")
        path = figures / f"{task}_effects.png"
        fig.savefig(path, dpi=160); fig.savefig(figures / f"{task}_effects.pdf"); plt.close(fig)
        embedded.append((task, base64.b64encode(path.read_bytes()).decode()))

        # Each contrast gets a distinct Bland–Altman panel; never pool FEI repeats.
        fig, axes = plt.subplots((len(rows)+2)//3, 3, figsize=(13, 3.4*((len(rows)+2)//3)), squeeze=False, layout="constrained")
        for ax, row in zip(axes.flat, rows):
            data = [p for p in paired if p["task"] == task and p["dataset"] == row["dataset"] and p["contrast"] == row["contrast"] and p["status"] == "ok"]
            a = np.array([r["baseline_value"] for r in data]); b = np.array([r["variant_value"] for r in data])
            ax.scatter((a+b)/2, b-a, s=12, alpha=.5)
            ax.axhline(row["mean_difference"], color="#126e82")
            for key in ("loa_lower", "loa_upper"):
                if key in row:
                    ax.axhline(row[key], color="#c45c36", linestyle="--", linewidth=.8)
            ax.set_title(f"{row['dataset']}/{row['contrast']}", fontsize=9)
            ax.set_xlabel("Pair mean"); ax.set_ylabel("Variant - baseline")
        for ax in list(axes.flat)[len(rows):]:
            ax.set_visible(False)
        fig.suptitle(f"{task} — Bland–Altman: bias and descriptive 95% limits")
        fig.savefig(figures/f"{task}_bland_altman.png", dpi=150)
        fig.savefig(figures/f"{task}_bland_altman.pdf"); plt.close(fig)
    keys = ["task", "unit", "dataset", "contrast", "n_expected", "n", "n_duplicate_pairs", "retention_rate", "mean_difference",
            "sd_difference", "mean_absolute_difference", "mad_ci_low", "mad_ci_high", "wilcoxon_p",
            "wilcoxon_q_bh", "icc_a1", "concordance"]
    def cell(value):
        if value is None:
            return "—"
        return html.escape(f"{value:.4g}" if isinstance(value, float) else str(value))
    table = "<tr>" + "".join(f"<th>{k}</th>" for k in keys) + "</tr>"
    for r in summaries:
        table += "<tr>" + "".join(f"<td>{cell(r.get(k))}</td>" for k in keys) + "</tr>"
    notice = "抽样冒烟测试：仅验证流程，不用于形成鲁棒性结论。" if metadata["smoke_test"] else "完整配对清单；统计仅使用双方预测均成功的配对。"
    pictures = "".join(f'<h2>{html.escape(t)}</h2><img alt="{html.escape(t)} paired effects" src="data:image/png;base64,{data}">' for t, data in embedded)
    failures = "".join(f"<li>{html.escape(m['task'])}: {html.escape(str(m.get('error')))}</li>" for m in metadata["models"] if m.get("error"))
    text = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>MedicalFaceFound 鲁棒性验证</title>
<style>body{{font:15px/1.6 system-ui;margin:36px;color:#17313c}}h1{{font-size:28px}}.note{{background:#eef5f6;padding:16px;border-left:4px solid #126e82}}img{{width:100%;max-width:1500px}}.scroll{{overflow:auto}}table{{border-collapse:collapse;font-size:12px}}th,td{{padding:8px;border-bottom:1px solid #d4e1e5;white-space:nowrap}}th{{text-align:left;background:#edf4f6}}code{{background:#eef2f4;padding:2px}}</style>
<h1>MedicalFaceFound · 外部配对鲁棒性验证</h1><div class="note"><b>{notice}</b><br>
状态：{metadata['status']} · 协议：{metadata['protocol']} · 预处理：{metadata['preprocess']['mode']}<br>
检测输入长边上限：{metadata['preprocess'].get('detector_max_side', 0)} px；允许检测器放大：{metadata['preprocess'].get('allow_upscaling', True)}；
裁剪回到原图坐标。所有图像使用同一设置，不按检测结果回退。<br>
检验的是预测稳定性，不是诊断准确性。P&gt;0.05 不证明等效；同时查看绝对变化、区间和配对保留率。</div>
<p>排除的字节完全重复配对：{len(metadata.get('duplicate_pairs', {}))} 对。
相同条件中按两张原图SHA256识别的重复配对仅计算一次，保留原始分母和 duplicate_pair 排除记录。
差值统一为 variant − baseline。HDA：术后 − 术前；Makeup：化妆 − 素颜。
各 FEI 条件单独分析，不把同一人的多张照片当作独立受试者混合检验。
BH 校正在本报告全部有效模型×条件检验中进行。置信区间按配对受试者重采样。</p>
<p>已核对用户提供的正式版正文（第12、17页），正文将详细鲁棒性方法指向另附 appendix 第5页；该附录未包含在17页正文PDF中。
统计细节参考<a href="https://arxiv.org/pdf/2506.14909">作者预印本补充方法（第26页）</a>，
对齐与单人脸筛选参考<a href="https://github.com/AIM-Harvard/FAHR-Face/blob/main/other/face_crop_align.py">作者公开预处理代码</a>。
FEI 姿态编号是已披露的工作映射，并未验证为精确 ±22.5°。本次模型、后端及裁剪设置不等同于论文的全部实现细节。</p>
<ul>{failures}</ul><div class="scroll"><table>{table}</table></div>{pictures}
<p>数据文件：<a href="summary.csv">summary.csv</a> · <a href="paired_results.csv">paired_results.csv</a> ·
<a href="predictions.csv">predictions.csv</a> · <a href="image_qc.csv">image_qc.csv</a> · <a href="run.json">run.json</a>。
figures/ 内另存 PNG、PDF 效应图和 Bland–Altman 图。</p></html>'''
    (output/"report.html").write_text(text, encoding="utf-8")
