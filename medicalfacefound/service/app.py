from __future__ import annotations

import base64
import hashlib
import json
import logging
import math
import os
import secrets
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from medicalfacefound.service import database as db
from medicalfacefound.service.catalog import CATALOG, CONSENT_VERSION
from medicalfacefound.service.explain import ExplanationVariant
from medicalfacefound.service.heatmap_settings import AGE_HEATMAP_LABELS, DEFAULT_HEATMAP_METHOD
from medicalfacefound.service.image import MAX_BYTES, ImageInputError, decode_image, decode_white_fill_mask
from medicalfacefound.service.models import ModelStore
from medicalfacefound.service.quality import QualityChecker, QUALITY_VERSION, png_bytes
from medicalfacefound.service.settings import Settings

logger = logging.getLogger(__name__)


async def read_image(file):
    content = await file.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise ImageInputError("图片大小不能超过 10 MB")
    return content


def create_app(settings: Settings | None = None):
    settings = settings or Settings.from_environment()
    os.environ.setdefault("DEEPFACE_HOME", str(settings.weights_dir / "retinaface-cache"))
    os.environ.setdefault("DEEPFACE_BACKEND_ENGINE", "pytorch")
    store = ModelStore(settings)
    checker = QualityChecker()

    @asynccontextmanager
    async def lifespan(app):
        await run_in_threadpool(db.initialize_database, settings.database_path)
        from medicalfacefound.service.admin import load_admin_token
        app.state.admin_token = load_admin_token(settings)
        yield

    app = FastAPI(title="MedicalFaceFound API", version="1.1.0", lifespan=lifespan)
    app.state.models = store
    app.state.settings = settings
    app.state.quality = checker

    @app.middleware("http")
    async def private_responses(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith(("/v1/", "/admin")):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    if settings.frontend_dir:
        app.mount("/ui-assets", StaticFiles(directory=settings.frontend_dir), name="ui-assets")

        @app.get("/", include_in_schema=False)
        def index():
            return FileResponse(settings.frontend_dir / "index.html")

        @app.get("/admin", include_in_schema=False)
        def admin_page():
            return FileResponse(settings.frontend_dir / "admin.html")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/ready")
    def ready():
        status = store.status()
        age_heatmap = db.age_heatmap_method(settings.database_path)
        return {"status": "ready", "capture_ready": checker.available, "backend": "medicalfacefound",
                "detector_backends": ["retinaface"] if checker.available else [], "quality_ready": checker.available,
                "consent_version": CONSENT_VERSION, "age_heatmap_method": age_heatmap,
                "age_heatmap_label": AGE_HEATMAP_LABELS[age_heatmap],
                "models": [{"id":name, **CATALOG.get(name, {"label":name})} for name in store.available], **status}

    def verified(content, require_pass=True, mask_content=None):
        try:
            decoded = decode_image(content)
            if mask_content is None:
                quality, crop = checker.check(decoded)
            else:
                foreground_alpha = decode_white_fill_mask(mask_content, decoded)
                quality, crop = checker.check(decoded, foreground_alpha=foreground_alpha)
            if require_pass and not quality["passed"]:
                raise HTTPException(422, detail={"message": "照片检查未通过，请调整后重试", "quality": quality})
            return decoded, quality, crop
        except ImageInputError as exc:
            raise HTTPException(422, str(exc)) from exc
        except (ImportError, RuntimeError) as exc:
            logger.exception("Photo quality check unavailable")
            raise HTTPException(503, "照片检查暂时不可用，请联系管理员") from exc

    async def uploaded(file):
        try:
            return await read_image(file)
        except ImageInputError as exc:
            raise HTTPException(422, str(exc)) from exc
        finally:
            await file.close()

    @app.post("/v1/photos/quality")
    async def quality_check(file: UploadFile = File(...), white_fill_mask: UploadFile | None = File(None)):
        content = await uploaded(file)
        mask_content = await uploaded(white_fill_mask) if white_fill_mask is not None else None
        decoded, quality, _ = await run_in_threadpool(verified, content, False, mask_content)
        return {**quality, "width": decoded.width, "height": decoded.height}

    @app.post("/v1/captures", status_code=201)
    async def create_capture(
        file: UploadFile = File(...), age: int = Form(..., ge=0, le=120),
        gender: Literal["male", "female", "other", "unspecified"] = Form(...),
        height_cm: float = Form(..., ge=30, le=250), weight_kg: float = Form(..., ge=1, le=500),
        capture_source: Literal["camera", "upload"] = Form(...),
        consent: bool = Form(...), consent_version: str = Form(...),
        request_id: str = Form(..., min_length=32, max_length=100),
        access_token: str = Form(..., min_length=32, max_length=128),
        white_fill_mask: UploadFile | None = File(None),
    ):
        if not consent or consent_version != CONSENT_VERSION:
            await file.close()
            if white_fill_mask is not None:
                await white_fill_mask.close()
            raise HTTPException(422, "请阅读并同意当前版本的资料用途说明")
        content = await uploaded(file)
        mask_content = await uploaded(white_fill_mask) if white_fill_mask is not None else None
        decoded, quality, crop = await run_in_threadpool(verified, content, True, mask_content)
        profile = dict(age=age,gender=gender,height_cm=height_cm,weight_kg=weight_kg,capture_source=capture_source,filename=file.filename)
        try:
            record = await run_in_threadpool(db.save_verified_capture, settings.database_path,
                content=content,decoded=decoded,profile=profile,request_id=request_id,access_token=access_token,
                consent_version=consent_version,quality=quality,processed=png_bytes(crop),mask_content=mask_content)
        except db.RecordConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"capture_id": record.id, "created_at": record.created_at,
                "image": {"width":decoded.width,"height":decoded.height,"format":decoded.format},
                "quality": {k:v for k,v in quality.items() if k != "preview"}}

    def authorize_capture(identity, authorization):
        row = db.capture_row(settings.database_path, identity)
        token = (authorization or "").removeprefix("Bearer ")
        if not row or not row["access_hash"] or not secrets.compare_digest(row["access_hash"],db.token_hash(token)):
            raise HTTPException(404, "记录不存在或访问凭证无效")
        return row

    @app.get("/v1/captures/{identity}/report")
    def capture_report(identity: str, authorization: str | None = Header(None)):
        authorize_capture(identity, authorization)
        return db.report(settings.database_path, identity)

    @app.post("/v1/captures/{identity}/deletion-request")
    def request_deletion(identity: str, authorization: str | None = Header(None)):
        authorize_capture(identity, authorization)
        with db.connect(settings.database_path) as conn:
            conn.execute("UPDATE captures SET deletion_requested_at=COALESCE(deletion_requested_at,?) WHERE id=?", (db.now(),identity))
        return {"status":"requested", "capture_id":identity}

    def attach_explanation(payload, identity, prediction_id, model, image):
        try:
            method = db.age_heatmap_method(settings.database_path) if model == "Age" else DEFAULT_HEATMAP_METHOD
            payload["explanation_method"] = method
            data = db.prediction_explanation(settings.database_path, identity, prediction_id, variant=method)
            if data is None:
                data = store.explain(model, image, variant=method)
                if not db.save_explanation(settings.database_path, prediction_id, data, variant=method):
                    payload["explanation_status"] = "failed"
                    return payload
            if model == "Age":
                db.set_explanation_method(settings.database_path, prediction_id, method)
        except Exception:
            logger.exception("Heatmap generation failed for %s", model)
            payload["explanation_status"] = "failed"
            return payload
        payload["explanation_status"] = "completed"
        payload["explanation"] = "data:image/png;base64," + base64.b64encode(data).decode("ascii")
        return payload

    def run_capture_prediction(identity, model, authorization, explain=False):
        row = authorize_capture(identity, authorization)
        if model not in store.available:
            raise HTTPException(404, "该模型尚未上线")
        if row["deletion_requested_at"]:
            raise HTTPException(409, "该记录已申请删除，已停止新的分析")
        if not row["processed_image"]:
            raise HTTPException(409, "旧记录缺少经过确认的推理图像，请重新采集")
        raw_config = (settings.weights_dir / "tasks" / model / "config.json").read_bytes()
        config = json.loads(raw_config)
        version = f'{config.get("sha256", "unverified")}:{hashlib.sha256(raw_config).hexdigest()}:{QUALITY_VERSION}'
        try:
            prediction_id, cached = db.reserve_prediction(settings.database_path,identity,model,version)
        except db.RecordConflict as exc:
            raise HTTPException(409,str(exc)) from exc
        if cached is not None:
            payload = {"model":model,"result":cached,"cached":True,"model_version":version}
            if explain:
                image = decode_image(row["processed_image"]).array
                payload = attach_explanation(payload, identity, prediction_id, model, image)
            return payload
        try:
            image = decode_image(row["processed_image"]).array
            result = store.predict(model,image)
            if not math.isfinite(float(result["value"])):
                raise RuntimeError("non-finite result")
            db.finish_prediction(settings.database_path,prediction_id,result=result)
            payload = {"model":model,"result":result,"cached":False,"model_version":version}
            if explain:
                payload = attach_explanation(payload, identity, prediction_id, model, image)
            return payload
        except Exception as exc:
            logger.exception("Capture prediction failed")
            db.finish_prediction(settings.database_path,prediction_id,error="模型分析失败，可重试；原始资料已保存")
            raise HTTPException(503,"模型分析失败，可仅重试分析，照片无需重复保存") from exc

    @app.post("/v1/captures/{identity}/predictions/{model}")
    def analyze_capture(identity: str, model: str, explain: bool = Query(False), authorization: str | None = Header(None)):
        return run_capture_prediction(identity,model,authorization,explain)

    @app.get("/v1/captures/{identity}/explanations/{prediction_id}")
    def capture_explanation(identity: str, prediction_id: str, authorization: str | None = Header(None),
                            variant: ExplanationVariant = "block"):
        authorize_capture(identity, authorization)
        data = db.prediction_explanation(settings.database_path, identity, prediction_id, variant=variant)
        if not data:
            raise HTTPException(404, "该分析没有热力图")
        return Response(data, media_type="image/png", headers={"Cache-Control": "private, max-age=300"})

    @app.post("/v1/models/{model_name}/predict")
    async def predict(model_name: str, file: UploadFile = File(...)):
        if model_name not in store.available:
            await file.close()
            raise HTTPException(404,"未找到可用的本地模型")
        content = await uploaded(file)
        decoded, quality, crop = await run_in_threadpool(verified,content)
        try:
            result = await run_in_threadpool(store.predict,model_name,crop)
            if not math.isfinite(float(result["value"])):
                raise RuntimeError("non-finite result")
            return {"model":model_name,"result":result,"image":{"width":decoded.width,"height":decoded.height,"face_bbox":quality["face_box"]}}
        except Exception as exc:
            raise HTTPException(503,"模型暂时不可用，请检查服务日志") from exc

    from medicalfacefound.service.admin import add_admin_routes
    add_admin_routes(app, settings, store)
    return app
