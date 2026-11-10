"""Grad-CAM visualisations for the deployed Swin regressors.

The overlay is generated from the same 256x256 crop that is used for
inference, so the heatmap is spatially aligned with the model input.
"""

from __future__ import annotations

import io
import logging
import math
from typing import Literal

import numpy as np

logger = logging.getLogger(__name__)
GradCAMVariant = Literal["block", "norm1"]
ExplanationVariant = Literal["block", "norm1", "hirescam", "layercam"]


def gradcam_png(model, config, image, *, variant: GradCAMVariant = "block"):
    """Return a PNG overlay (bytes) for one RGB uint8 model input crop."""
    import cv2
    import torch
    from medicalfacefound.inference.face import to_model_input

    image = np.asarray(image, dtype=np.uint8)
    height, width = image.shape[:2]
    device = next(model.parameters()).device
    tensor = torch.from_numpy(to_model_input(image)[None]).to(device)

    captured = {}

    def hook(_module, _inputs, output):
        feature = output[0] if isinstance(output, tuple) else output
        feature.retain_grad()
        captured["feature"] = feature

    block = model.blocks[-1]
    layer = block.norm1 if variant == "norm1" else block
    handle = layer.register_forward_hook(hook)
    try:
        model.eval()
        model.zero_grad(set_to_none=True)
        with torch.enable_grad():
            output = model(tensor)
            if config.get("task_type") == "regression":
                target = output.reshape(-1)[0]
            else:
                target = output.max()
            target.backward()
        feature = captured.get("feature")
        if feature is None or feature.grad is None:
            raise RuntimeError("Grad-CAM feature or gradient was not captured")
        batch, tokens, channels = feature.shape
        side = math.isqrt(tokens)
        if side * side != tokens:
            raise RuntimeError(f"feature map is not square: {tokens} tokens")
        feature_map = feature.detach().reshape(batch, side, side, channels).permute(0, 3, 1, 2)
        gradient = feature.grad.detach().reshape(batch, side, side, channels).permute(0, 3, 1, 2)
        weights = gradient.mean(dim=(2, 3), keepdim=True)
        cam = torch.relu((weights * feature_map).sum(dim=1))[0].cpu().numpy()
        cam = cam - cam.min()
        cam = cam / (cam.max() + 1e-8)
        cam = cv2.resize(cam, (width, height), interpolation=cv2.INTER_CUBIC)
    finally:
        handle.remove()
        model.zero_grad(set_to_none=True)

    return cam_overlay_png(cam, image)


def cam_overlay_png(cam, image):
    import cv2
    from PIL import Image

    # Bicubic interpolation can overshoot at sharp edges. Clamp before
    # converting to uint8 so negative values do not wrap to high intensities.
    heatmap = cv2.applyColorMap(np.uint8(255 * np.clip(cam, 0, 1)), cv2.COLORMAP_JET)
    heatmap = cv2.cvtColor(heatmap, cv2.COLOR_BGR2RGB)
    overlay = 0.55 * image.astype(np.float32) + 0.45 * heatmap.astype(np.float32)
    overlay = np.clip(overlay, 0, 255).astype(np.uint8)

    buffer = io.BytesIO()
    Image.fromarray(overlay).save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
