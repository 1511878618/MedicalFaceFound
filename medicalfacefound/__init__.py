"""MedicalFaceFound — Swin-L facial foundation model for biomarker prediction.

The package contains the model definitions (``medicalfacefound.utils``), the
pretraining / fine-tuning entry points, and the inference utilities::

    from medicalfacefound import FaceCropper, load_task, predict_values

    crop = FaceCropper().crop_path("selfie.jpg")
    model, cfg = load_task("Age")
    print(predict_values(model, cfg, [crop]))

Weights are hosted on Hugging Face and downloaded on first use.
"""

from __future__ import annotations

__version__ = "1.0.1"

from medicalfacefound.inference import FaceCropper, load_task, load_tasks_index, predict_values  # noqa: E402
from medicalfacefound.inference.face import crop_square, detect_faces, load_image, square_box, to_model_input  # noqa: E402

__all__ = [
    "__version__",
    "FaceCropper",
    "load_task",
    "load_tasks_index",
    "predict_values",
    "crop_square",
    "detect_faces",
    "load_image",
    "square_box",
    "to_model_input",
]
