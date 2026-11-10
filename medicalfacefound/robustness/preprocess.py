"""Fixed preprocessing without detector fallbacks or silent full-image inference."""
from __future__ import annotations

import numpy as np
from PIL import Image

from medicalfacefound.inference.face import load_image, crop_square, square_box


def prepare(path, *, mode, threshold, ratio, multi_face, detector_max_side=640, allow_upscaling=False):
    from retinaface import RetinaFace

    rgb = load_image(path)
    bgr = np.ascontiguousarray(rgb[:, :, ::-1])
    # Fix detector scale across the dataset, not a per-image success fallback.
    detection_bgr = bgr
    if detector_max_side and max(rgb.shape[:2]) > detector_max_side:
        scale = detector_max_side / max(rgb.shape[:2])
        small = Image.fromarray(rgb).resize((round(rgb.shape[1]*scale), round(rgb.shape[0]*scale)), Image.Resampling.BILINEAR)
        detection_bgr = np.ascontiguousarray(np.asarray(small)[:, :, ::-1])
    sx, sy = rgb.shape[1]/detection_bgr.shape[1], rgb.shape[0]/detection_bgr.shape[0]
    faces = RetinaFace.detect_faces(detection_bgr, threshold=threshold, allow_upscaling=allow_upscaling)
    faces = sorted(faces.values(), key=lambda f: float(f["score"]), reverse=True) if isinstance(faces, dict) else []
    meta = {"width": rgb.shape[1], "height": rgb.shape[0], "face_count": len(faces)}
    if not faces:
        return None, {**meta, "status": "no_face"}
    if len(faces) > 1 and multi_face == "reject":
        return None, {**meta, "status": "multiple_faces"}
    face = faces[0]
    box = [int(round(v*(sx if i % 2 == 0 else sy))) for i, v in enumerate(face["facial_area"])]
    meta.update(confidence=float(face["score"]), bbox=box, detector_width=detection_bgr.shape[1], detector_height=detection_bgr.shape[0])
    if mode == "package":
        crop = crop_square(rgb, square_box(tuple(box), rgb.shape[:2], ratio=ratio), size=256)
    else:
        # Same landmark alignment functions as RetinaFace.extract_faces, with
        # one detector call and explicit most-confident/reject multi-face policy.
        from retinaface.commons import postprocess
        landmarks = {key: (float(value[0])*sx, float(value[1])*sy) for key, value in face["landmarks"].items()}
        aligned, angle = postprocess.align_img_wrt_eyes(
            img=bgr, left_eye=landmarks["left_eye"], right_eye=landmarks["right_eye"])
        x1, y1, x2, y2 = postprocess.project_facial_area(
            facial_area=tuple(box), angle=angle, size=rgb.shape[:2])
        x1, y1 = max(0, int(x1)), max(0, int(y1))
        x2, y2 = min(aligned.shape[1], int(x2)), min(aligned.shape[0], int(y2))
        if x2 <= x1 or y2 <= y1:
            raise ValueError("empty aligned face box")
        patch = aligned[y1:y2, x1:x2]
        crop = postprocess.resize_image(img=patch, target_size=(256, 256), min_max_norm=False)[:, :, ::-1]
        meta["alignment_degrees"] = float(angle)
    crop = np.ascontiguousarray(crop, dtype=np.uint8)
    if crop.shape != (256, 256, 3):
        raise ValueError(f"Invalid crop: {crop.shape}")
    return crop, {**meta, "status": "ok"}


def save_crop(path, array):
    Image.fromarray(array).save(path, format="PNG")
