"""Conservative acquisition heuristics, not a clinical quality certification."""
from __future__ import annotations

import base64
import importlib.util
from io import BytesIO
from threading import Lock

import numpy as np
from PIL import Image

from medicalfacefound.inference import face as face_pipeline

QUALITY_VERSION = "mff-retinaface0.0.19-pytorch-r1.2-s256-quality-v1"


def png_bytes(array):
    output = BytesIO()
    Image.fromarray(array).save(output, "PNG")
    return output.getvalue()


class QualityChecker:
    def __init__(self):
        self.lock = Lock()

    @property
    def available(self):
        return all(importlib.util.find_spec(name) is not None for name in ("retinaface", "torch", "cv2"))

    def detect(self, image):
        if not self.available:
            raise RuntimeError("照片检查尚未就绪，请联系管理员")
        with self.lock:
            return face_pipeline.detect_faces(image)

    def check(self, decoded, *, foreground_alpha=None):
        import cv2
        faces = self.detect(decoded.array)
        checks = []

        def check(key, label, passed, message):
            checks.append({"key": key, "label": label, "passed": bool(passed), "message": message})

        check("face", "单人脸", len(faces) == 1, "仅保留一张清晰正面人脸" if len(faces) != 1 else "检测到一张人脸")
        report = {"version": QUALITY_VERSION, "face_count": len(faces), "checks": checks,
                  "passed": False, "crop_box": None, "note": "自动检查仅用于采集质量提示，不能保证预测准确性。"}
        if len(faces) != 1:
            return report, None
        face = faces[0]
        x1, y1, x2, y2 = face["box"]
        w, h = x2 - x1, y2 - y1
        box = face_pipeline.square_box(tuple(face["box"]), decoded.array.shape[:2])
        complete = box[0] >= 0 and box[1] >= 0 and box[2] <= decoded.width and box[3] <= decoded.height
        check("framing", "面部取景", complete and min(w, h) >= 100,
              "请让额头、下巴完整入镜，并适当靠近镜头" if not complete or min(w, h) < 100 else "面部尺寸及周围留白合适")
        if w <= 0 or h <= 0:
            return report, None
        crop = face_pipeline.crop_square(decoded.array, box, size=face_pipeline.DEFAULT_SIZE)
        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
        exposure_pixels = gray
        if foreground_alpha is not None:
            alpha_crop = face_pipeline.crop_square(foreground_alpha, box, size=face_pipeline.DEFAULT_SIZE,
                                                   resample=Image.Resampling.BILINEAR)
            # Exclude areas where the applied white fill covers at least half the pixel.
            exposure_pixels = gray[alpha_crop >= 128]
        enough_pixels = exposure_pixels.size >= gray.size / 4
        brightness = float(exposure_pixels.mean()) if enough_pixels else None
        clipped = float(((exposure_pixels < 12) | (exposure_pixels > 245)).mean()) if enough_pixels else None
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        exposure_ok = enough_pixels and 45 <= brightness <= 215 and clipped < 0.35
        if not enough_pixels:
            exposure_message = "填白后保留的区域太少，无法检查光线，请调整取景或使用原图"
        else:
            exposure_message = "光线适中" if exposure_ok else "请调整到均匀光线处，避免过暗、过曝或强烈阴影"
        check("exposure", "光线", exposure_ok, exposure_message)
        check("sharpness", "清晰度", sharpness >= 30, "清晰度检查通过" if sharpness >= 30 else "照片较模糊，请保持稳定并重新拍摄")
        # The repository pipeline returns bounding boxes, not landmark-based pose.
        # Do not claim that occlusion or pose was measured when it was not.
        metrics = {"brightness": round(brightness, 2) if enough_pixels else None, "sharpness": round(sharpness, 2)}
        if foreground_alpha is not None:
            metrics["exposure_excluded_fraction"] = round(1 - exposure_pixels.size / gray.size, 4)
        report.update(passed=all(c["passed"] for c in checks), crop_box=list(box), face_box=face["box"],
                      metrics=metrics,
                      preview="data:image/png;base64," + base64.b64encode(png_bytes(crop)).decode())
        return report, crop
