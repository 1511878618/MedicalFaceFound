"""One-shot FAHR-FaceAge inference in the existing fahr-face conda environment."""

import base64
from io import BytesIO
import json
import math
from pathlib import Path
import sys

import cv2
import numpy as np
from PIL import Image
import torch
from transformers import ViTConfig


def overlay_data_url(image, normalized_map):
    heatmap = cv2.applyColorMap(np.uint8(255 * np.clip(normalized_map, 0, 1)), cv2.COLORMAP_JET)
    rgb = cv2.cvtColor(heatmap, cv2.COLOR_BGR2RGB)
    overlay = np.clip(0.55 * np.asarray(image) + 0.45 * rgb, 0, 255).astype(np.uint8)
    buffer = BytesIO()
    Image.fromarray(overlay).save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def predict(crop, source, checkpoint):
    sys.path.insert(0, str(source))
    from ViTForAgeEstimation import ViTForAgeRegression

    torch.set_num_threads(4)
    config = ViTConfig(image_size=112)
    model = ViTForAgeRegression(config)
    weights = torch.load(str(checkpoint), map_location="cpu", weights_only=True, mmap=True)
    model.load_state_dict(weights["model_state_dict"], strict=True)
    del weights
    model.eval().requires_grad_(False)

    resized = crop.resize((112, 112), Image.Resampling.BILINEAR)
    pixels = torch.from_numpy(np.array(resized)).permute(2, 0, 1).float() / 255
    mean = torch.tensor([0.485, 0.456, 0.406])[:, None, None]
    std = torch.tensor([0.229, 0.224, 0.225])[:, None, None]
    tensor = ((pixels - mean) / std).unsqueeze(0)
    feature = None

    def capture_feature(_module, _inputs, output):
        nonlocal feature
        # Track only the path from this layer to the age head.
        feature = output.requires_grad_(True)

    handle = model.vit.encoder.layer[-1].layernorm_before.register_forward_hook(capture_feature)
    try:
        with torch.enable_grad():
            output = model(tensor, output_attentions=True)
            age = output.age_output
            if feature is None:
                raise RuntimeError("FAHR-FaceAge target layer did not run")
            gradient, = torch.autograd.grad(age, feature)
    finally:
        handle.remove()

    value = float(age.detach())
    if not math.isfinite(value):
        raise RuntimeError("FAHR-FaceAge returned a non-finite age")
    # The leading CLS token has no spatial location.
    patches = feature.detach()[0, 1:]
    patch_gradients = gradient.detach()[0, 1:]
    side = config.image_size // config.patch_size
    cam = torch.relu(patches @ patch_gradients.mean(dim=0)).reshape(side, side).numpy()
    if not np.isfinite(cam).all():
        raise RuntimeError("FAHR-FaceAge returned non-finite Grad-CAM values")
    cam -= cam.min()
    cam /= cam.max() + 1e-8
    cam = cv2.resize(cam, crop.size, interpolation=cv2.INTER_CUBIC)

    # FAHR-Face paper, "2D and 3D Attention Maps": average the final
    # layer's CLS-to-patch attention over heads, excluding the CLS column.
    patch_attention = output.attentions[-1].detach()[0, :, 0, 1:]
    attention_grid = patch_attention.mean(dim=0).reshape(side, side).numpy()
    if not np.isfinite(attention_grid).all():
        raise RuntimeError("FAHR-FaceAge returned non-finite attention weights")
    attention_image = cv2.resize(attention_grid, (448, 448), interpolation=cv2.INTER_LINEAR)
    # Color normalization is for the preview; return the original weights too.
    attention_image -= attention_image.min()
    attention_image /= attention_image.max() + 1e-8
    attention_background = resized.resize((448, 448), Image.Resampling.BILINEAR)

    return {
        "model": "FAHR-FaceAge",
        "result": {"task": "Age", "value": value, "unit": "year"},
        "explanation": overlay_data_url(crop, cam),
        "explanation_status": "completed",
        "preprocessing": {"source": "stored_processed_crop", "input_size": [112, 112]},
        "attribution": {"method": "Grad-CAM", "layer": "vit.encoder.layer[-1].layernorm_before",
                        "grid": [side, side]},
        "attention": {
            "method": "final_layer_cls_to_patch_head_mean",
            "patch_weights": attention_grid.tolist(),
            "interpolation": "bilinear",
            "image_size": [448, 448],
            "overlay": overlay_data_url(attention_background, attention_image),
        },
    }


if __name__ == "__main__":
    source, checkpoint = map(Path, sys.argv[1:])
    with Image.open(BytesIO(sys.stdin.buffer.read())) as image:
        print(json.dumps(predict(image.convert("RGB"), source, checkpoint), allow_nan=False))
