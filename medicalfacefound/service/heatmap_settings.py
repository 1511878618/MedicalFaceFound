"""Public age heatmap choices and the standard Grad-CAM default."""

from importlib.util import find_spec
from typing import Literal

AgeHeatmapMethod = Literal["block", "hirescam", "layercam"]
DEFAULT_HEATMAP_METHOD = "block"
AGE_HEATMAP_LABELS = {
    "block": "Grad-CAM · 最后一个 block 输出",
    "hirescam": "HiResCAM · 第四阶段 norm1",
    "layercam": "LayerCAM · 第三阶段 norm1",
}
PACKAGE_METHODS = {"hirescam", "layercam"}


def age_heatmap_options():
    package_available = find_spec("pytorch_grad_cam") is not None
    return [
        {"id": method, "label": label, "available": package_available or method not in PACKAGE_METHODS}
        for method, label in AGE_HEATMAP_LABELS.items()
    ]
