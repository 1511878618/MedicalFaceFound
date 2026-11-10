from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from medicalfacefound.inference.face import crop_square, detect_faces, square_box

MAX_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 20_000_000
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


class ImageInputError(ValueError):
    pass


@dataclass(frozen=True)
class DecodedImage:
    array: np.ndarray
    width: int
    height: int
    format: str


def decode_image(data: bytes) -> DecodedImage:
    if not data:
        raise ImageInputError("上传文件为空")
    if len(data) > MAX_BYTES:
        raise ImageInputError("图片大小不能超过 10 MB")
    try:
        with Image.open(BytesIO(data)) as image:
            image_format = image.format
            if image_format not in ALLOWED_FORMATS:
                raise ImageInputError("仅支持 JPEG、PNG 或 WEBP 图片")
            if image.width * image.height > MAX_PIXELS:
                raise ImageInputError(f"图片像素数不能超过 {MAX_PIXELS}")
            image = ImageOps.exif_transpose(image).convert("RGB")
            return DecodedImage(np.asarray(image).copy(), image.width, image.height, image_format)
    except ImageInputError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ImageInputError("无法解析上传的图片") from exc


def decode_white_fill_mask(data: bytes, decoded: DecodedImage) -> np.ndarray:
    """Map the browser's foreground alpha PNG to the submitted photo."""
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format != "PNG" or "A" not in image.getbands() or image.width * image.height > MAX_PIXELS:
                raise ImageInputError("填白掩码须为带透明通道的 PNG")
            alpha = image.getchannel("A").resize((decoded.width, decoded.height), Image.Resampling.BILINEAR)
            return np.asarray(alpha).copy()
    except ImageInputError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ImageInputError("无法解析填白掩码") from exc


def prepare_image(decoded: DecodedImage, mode: str, detector_backend: str) -> tuple[np.ndarray, dict]:
    image = decoded.array
    metadata = {"width": decoded.width, "height": decoded.height, "detected_face": False,
                "face_bbox": None, "face_confidence": None}
    if mode == "face":
        if detector_backend != "retinaface":
            raise ImageInputError("MedicalFaceFound 的人脸检测器为 RetinaFace")
        faces = detect_faces(image)
        if not faces:
            raise ImageInputError("未检测到有效人脸")
        face = faces[0]
        x1, y1, x2, y2 = face["box"]
        metadata.update(detected_face=True, face_bbox=(x1, y1, x2 - x1, y2 - y1), face_confidence=face["score"])
        image = crop_square(image, square_box(face["box"], image.shape[:2]), size=256)
    elif mode == "pad":
        height, width = image.shape[:2]
        # Resize before padding so a very narrow image cannot allocate a huge square.
        scale = 256 / max(height, width)
        size = (max(1, round(width * scale)), max(1, round(height * scale)))
        image = np.asarray(Image.fromarray(image).resize(size, Image.Resampling.BICUBIC))
        top, left = (256 - size[1]) // 2, (256 - size[0]) // 2
        image = np.pad(image, ((top, 256 - size[1] - top), (left, 256 - size[0] - left), (0, 0)), mode="edge")
    elif mode == "none":
        image = np.asarray(Image.fromarray(image).resize((256, 256), Image.Resampling.BICUBIC))
    else:
        raise ImageInputError("不支持的图片处理模式")
    return np.ascontiguousarray(image, dtype=np.uint8), metadata
