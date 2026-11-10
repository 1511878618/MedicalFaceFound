"""Optional, read-only CAM comparison for the administrator."""

from __future__ import annotations

import base64
import logging
import math
from threading import Lock

import numpy as np
from fastapi import Depends, HTTPException

from medicalfacefound.service import database as db
from medicalfacefound.service.explain import cam_overlay_png
from medicalfacefound.service.image import decode_image

logger = logging.getLogger(__name__)


def add_cam_comparison_route(app, settings, store, admin):
    lock = Lock()

    @app.post("/v1/admin/captures/{identity}/cam-comparison", dependencies=[Depends(admin)])
    def cam_comparison(identity: str, evaluate: bool = False):
        row = db.capture_row(settings.database_path, identity)
        if row is None:
            raise HTTPException(404, "记录不存在")
        if row["deletion_requested_at"] or not row["processed_image"]:
            raise HTTPException(409, "该记录暂不可用于热图对照")
        if "Age" not in store.available:
            raise HTTPException(503, "年龄模型暂不可用")
        if not lock.acquire(blocking=False):
            raise HTTPException(429, "热图对照正在运行，请稍后重试")
        try:
            image = decode_image(row["processed_image"]).array
            result = store.compare_age_cams(image, evaluate=evaluate)
            current = db.capture_row(settings.database_path, identity)
            if current is None or current["deletion_requested_at"]:
                raise HTTPException(409, "该记录已删除或已申请删除")
            return result
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Experimental age CAM comparison failed")
            raise HTTPException(503, "热图对照运行失败，请检查服务日志") from exc
        finally:
            lock.release()


def reshape_swin_tokens(tokens):
    batch, count, channels = tokens.shape
    side = math.isqrt(count)
    return tokens.reshape(batch, side, side, channels).permute(0, 3, 1, 2)


def compare_age_cams(model, config, image, *, evaluate):
    methods = ("hirescam", "layercam", "gradcam_norm1") if evaluate else ("hirescam", "layercam")
    maps, road = age_cam_maps(model, config, image, methods, evaluate=evaluate)
    overlays = {
        name: "data:image/png;base64," + base64.b64encode(cam_overlay_png(maps[name], image)).decode("ascii")
        for name in ("hirescam", "layercam")
    }
    return {"overlays": overlays, "road": road}


def age_cam_maps(model, config, image, methods, *, evaluate=False):
    import torch
    from pytorch_grad_cam import GradCAM, HiResCAM, LayerCAM

    from medicalfacefound.inference.face import to_model_input

    tensor = torch.from_numpy(to_model_input(image)[None]).to(next(model.parameters()).device)

    def age_target(output):
        return output.reshape(-1)[0] * config["target_std"] + config["target_mean"]

    last_norm = model.blocks[-1].norm1
    stage3_norm = model.blocks[-1 - config["depths"][-1]].norm1
    layers = {
        "hirescam": (HiResCAM, last_norm),
        "layercam": (LayerCAM, stage3_norm),
        "gradcam_norm1": (GradCAM, last_norm),
    }

    maps = {}
    try:
        with torch.enable_grad():
            for name in methods:
                method, layer = layers[name]
                with method(model=model, target_layers=[layer], reshape_transform=reshape_swin_tokens) as cam:
                    saliency = cam(input_tensor=tensor, targets=[age_target])
                if saliency is None or not np.isfinite(saliency).all():
                    raise RuntimeError(f"Invalid age CAM: {name}")
                maps[name] = saliency[0]
    finally:
        model.zero_grad(set_to_none=True)

    return maps, road_age_changes(model, tensor, age_target, maps) if evaluate else None


def road_age_changes(model, tensor, age_target, maps):
    import torch
    from pytorch_grad_cam.metrics.road import NoisyLinearImputer

    # Use ROAD's interpolation without noise for a repeatable, equal-area comparison.
    fill = NoisyLinearImputer(noise=0)
    pixels = tensor[0].cpu()
    with torch.inference_mode():
        original = age_target(model(tensor)[0]).item()
        results = {}
        for name, saliency in maps.items():
            if np.ptp(saliency) == 0:
                results[name] = None
                continue
            order = np.argsort(saliency.ravel(), kind="stable")
            count = len(order) // 4
            perturbed = []
            for indices in (order[-count:], order[:count]):
                mask = torch.ones(saliency.size, dtype=torch.float32)
                mask[indices] = 0
                perturbed.append(fill(pixels, mask.reshape(saliency.shape)))
            scores = model(torch.stack(perturbed).to(tensor.device))
            changes = [age_target(score).item() - original for score in scores]
            if not all(math.isfinite(change) for change in changes):
                raise RuntimeError(f"Invalid ROAD age change: {name}")
            results[name] = {"high_delta_years": changes[0], "low_delta_years": changes[1]}
    return results
