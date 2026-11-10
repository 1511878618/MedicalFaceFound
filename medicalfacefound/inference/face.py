"""Face detection, cropping and preprocessing (RetinaFace).

The released models expect a 256 x 256 RGB frontal face crop normalised with the
ImageNet statistics. RetinaFace weights are downloaded on first use by the
`retina-face` package (~118 MB, cached in ``~/.deepface/weights``).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

DEFAULT_SIZE = 256
DEFAULT_RATIO = 1.2


def load_image(path: str | Path) -> np.ndarray:
    """Read an image as an RGB uint8 array (EXIF orientation applied)."""
    from PIL import Image, ImageOps

    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        return np.asarray(img)


def detect_faces(image: np.ndarray, threshold: float = 0.9) -> list[dict]:
    """Return detected faces sorted by confidence: [{"box": (x1, y1, x2, y2), "score": s}]."""
    try:
        from retinaface import RetinaFace
    except ImportError as exc:  # pragma: no cover - dependency hint
        raise ImportError(
            "face detection needs retina-face; reinstall the package: pip install medicalfacefound"
        ) from exc

    bgr = np.ascontiguousarray(image[..., ::-1])
    faces = RetinaFace.detect_faces(bgr, threshold=threshold)
    if not isinstance(faces, dict):
        return []

    out = []
    for face in faces.values():
        x1, y1, x2, y2 = face["facial_area"]
        out.append({"box": (int(x1), int(y1), int(x2), int(y2)), "score": float(face.get("score", 0.0))})
    out.sort(key=lambda d: d["score"], reverse=True)
    return out


def square_box(box: tuple[int, int, int, int], shape: tuple[int, int], ratio: float = DEFAULT_RATIO):
    """Expand a face box to a square of side ``max(w, h) * ratio``."""
    x1, y1, x2, y2 = box
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    half = max(x2 - x1, y2 - y1) * ratio / 2.0
    return (int(round(cx - half)), int(round(cy - half)),
            int(round(cx + half)), int(round(cy + half)))


def crop_square(image: np.ndarray, box: tuple[int, int, int, int], size: int = DEFAULT_SIZE,
                *, resample=None) -> np.ndarray:
    """Crop ``box`` (padding with edge pixels when out of bounds) and resize."""
    from PIL import Image

    h, w = image.shape[:2]
    x1, y1, x2, y2 = box
    pad_l, pad_t = max(0, -x1), max(0, -y1)
    pad_r, pad_b = max(0, x2 - w), max(0, y2 - h)
    if any((pad_l, pad_t, pad_r, pad_b)):
        padding = ((pad_t, pad_b), (pad_l, pad_r)) + ((0, 0),) * (image.ndim - 2)
        image = np.pad(image, padding, mode="edge")
        x1, y1, x2, y2 = x1 + pad_l, y1 + pad_t, x2 + pad_l, y2 + pad_b

    patch = image[y1:y2, x1:x2]
    return np.asarray(Image.fromarray(patch).resize(
        (size, size), Image.Resampling.BICUBIC if resample is None else resample
    ))


def to_model_input(crop: np.ndarray) -> np.ndarray:
    """RGB uint8 (H, W, 3) -> float32 CHW with ImageNet normalisation."""
    x = crop.astype(np.float32) / 255.0
    x = (x - IMAGENET_MEAN) / IMAGENET_STD
    return np.ascontiguousarray(x.transpose(2, 0, 1))


class FaceCropper:
    """Detect the most confident face and return a square crop for the model."""

    def __init__(self, size: int = DEFAULT_SIZE, ratio: float = DEFAULT_RATIO, threshold: float = 0.9):
        self.size = size
        self.ratio = ratio
        self.threshold = threshold

    def crop(self, image: np.ndarray) -> np.ndarray | None:
        faces = detect_faces(image, threshold=self.threshold)
        if not faces:
            return None
        box = square_box(faces[0]["box"], image.shape[:2], ratio=self.ratio)
        return crop_square(image, box, size=self.size)

    def crop_path(self, path: str | Path) -> np.ndarray | None:
        return self.crop(load_image(path))
