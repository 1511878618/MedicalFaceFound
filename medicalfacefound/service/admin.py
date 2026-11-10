from __future__ import annotations

import csv
import io
import json
import logging
import os
import secrets
import subprocess
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from threading import Lock

from fastapi import Depends, Header, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from medicalfacefound.service import database as db
from medicalfacefound.service.explain import ExplanationVariant
from medicalfacefound.service.heatmap_settings import AgeHeatmapMethod, age_heatmap_options

logger = logging.getLogger(__name__)


def load_admin_token(settings):
    if settings.admin_token:
        if len(settings.admin_token) < 32:
            raise ValueError("MFF_ADMIN_TOKEN must contain at least 32 characters")
        return settings.admin_token
    path = settings.database_path.parent / "admin-access.key"
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd,"w") as file:
            file.write(secrets.token_urlsafe(36) + "\n")
    os.chmod(path,0o600)
    token = path.read_text().strip()
    if len(token) < 32:
        raise ValueError("Admin access key is invalid")
    return token


class DeleteConfirmation(BaseModel):
    confirmation: str


class ProfileUpdate(BaseModel):
    age: int | None = Field(None, ge=0, le=120)
    tags: list[str] | None = None


class HeatmapSettingsUpdate(BaseModel):
    age_method: AgeHeatmapMethod


def normalize_tags(tags):
    result = []
    for value in tags:
        tag = " ".join(str(value).split())
        if not tag:
            continue
        if len(tag) > 32:
            raise HTTPException(422, "单个标签不能超过 32 个字符")
        if not tag.isprintable():
            raise HTTPException(422, "标签包含非法字符")
        if tag not in result:
            result.append(tag)
    if len(result) > 20:
        raise HTTPException(422, "标签不能超过 20 个")
    return result


def add_admin_routes(app, settings, store):
    fahr_python = settings.fahr_faceage_python
    fahr_source = settings.fahr_faceage_source
    fahr_checkpoint = settings.fahr_faceage_checkpoint
    fahr_available = bool(
        fahr_python and os.access(fahr_python, os.X_OK)
        and fahr_source and (fahr_source / "ViTForAgeEstimation.py").is_file()
        and fahr_checkpoint and fahr_checkpoint.is_file()
    )
    fahr_lock = Lock()

    def admin(authorization: str | None = Header(None)):
        token = (authorization or "").removeprefix("Bearer ")
        if not token or not secrets.compare_digest(token,app.state.admin_token):
            raise HTTPException(401,"请使用管理员访问密钥登录",headers={"WWW-Authenticate":"Bearer"})

    if settings.cam_comparison_enabled:
        from medicalfacefound.service.cam_comparison import add_cam_comparison_route

        add_cam_comparison_route(app, settings, store, admin)

    @app.get("/v1/admin/settings/heatmaps", dependencies=[Depends(admin)])
    def heatmap_settings():
        return {"age_method": db.age_heatmap_method(settings.database_path), "options": age_heatmap_options()}

    @app.put("/v1/admin/settings/heatmaps", dependencies=[Depends(admin)])
    def update_heatmap_settings(body: HeatmapSettingsUpdate):
        if not any(option["id"] == body.age_method and option["available"] for option in age_heatmap_options()):
            raise HTTPException(409, "当前服务环境无法运行此热图方法")
        db.set_age_heatmap_method(settings.database_path, body.age_method)
        return heatmap_settings()

    def filters(start: date | None = None, end: date | None = None, status: str = "all", tag: str | None = None):
        if status not in {"all","failed","deletion"}:
            raise HTTPException(422,"筛选条件无效")
        if start and end and start > end:
            raise HTTPException(422,"开始日期不能晚于结束日期")
        tz = timezone(timedelta(hours=8))
        def utc(day):
            return datetime.combine(day,time.min,tzinfo=tz).astimezone(timezone.utc).isoformat()
        return {"start":utc(start) if start else None,"end":utc(end+timedelta(days=1)) if end else None,
                "status":status,"tag":tag or None}

    @app.get("/v1/admin/captures",dependencies=[Depends(admin)])
    def captures(start: date | None = None,end: date | None = None,status: str = "all",tag: str | None = None,
                 limit: int = Query(20,ge=1,le=100),offset: int = Query(0,ge=0)):
        return db.list_captures(settings.database_path,**filters(start,end,status,tag),limit=limit,offset=offset)

    @app.get("/v1/admin/tags",dependencies=[Depends(admin)])
    def tags():
        return {"items": db.list_tags(settings.database_path)}

    @app.patch("/v1/admin/captures/{identity}",dependencies=[Depends(admin)])
    def update(identity: str, body: ProfileUpdate):
        if body.age is None and body.tags is None:
            raise HTTPException(422,"没有需要更新的字段")
        if not db.capture_row(settings.database_path, identity):
            raise HTTPException(404,"记录不存在")
        try:
            if body.age is not None:
                db.set_age(settings.database_path, identity, body.age)
            if body.tags is not None:
                db.set_tags(settings.database_path, identity, normalize_tags(body.tags))
        except KeyError as exc:
            raise HTTPException(404,"记录不存在") from exc
        result = db.report(settings.database_path, identity)
        if result is None:
            raise HTTPException(404,"记录不存在")
        return result

    @app.get("/v1/admin/captures/{identity}",dependencies=[Depends(admin)])
    def detail(identity: str):
        result = db.report(settings.database_path,identity)
        if not result:
            raise HTTPException(404,"记录不存在")
        with db.connect(settings.database_path) as conn:
            db.audit(conn,"view",identity)
        result["fahr_faceage_available"] = bool(
            fahr_available and result["crop_box"] is not None and not result["deletion_requested_at"]
        )
        if settings.cam_comparison_enabled:
            result["cam_comparison_available"] = bool(
                "Age" in store.available and result["crop_box"] is not None and not result["deletion_requested_at"]
            )
        return result

    if fahr_available:
        @app.post("/v1/admin/captures/{identity}/fahr-faceage", dependencies=[Depends(admin)])
        def fahr_faceage(identity: str):
            row = db.capture_row(settings.database_path, identity)
            if row is None:
                raise HTTPException(404, "记录不存在")
            if row["deletion_requested_at"] or not row["processed_image"]:
                raise HTTPException(409, "该记录暂不可用于 FAHR-FaceAge 对照")
            if not fahr_lock.acquire(blocking=False):
                raise HTTPException(429, "FAHR-FaceAge 正在运行，请稍后重试")
            try:
                worker = Path(__file__).with_name("fahr_faceage_worker.py")
                completed = subprocess.run(
                    [str(fahr_python), "-B", str(worker), str(fahr_source), str(fahr_checkpoint)],
                    input=row["processed_image"], capture_output=True, check=True, timeout=90,
                    env={**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"},
                )
                return json.loads(completed.stdout)
            except subprocess.TimeoutExpired as exc:
                raise HTTPException(504, "FAHR-FaceAge 分析超时，请稍后重试") from exc
            except (OSError, subprocess.CalledProcessError, ValueError) as exc:
                logger.exception("FAHR-FaceAge worker failed")
                if isinstance(exc, subprocess.CalledProcessError):
                    logger.error("FAHR-FaceAge worker stderr: %s", exc.stderr.decode(errors="replace")[-3000:])
                raise HTTPException(503, "FAHR-FaceAge 分析失败，请检查服务日志") from exc
            finally:
                fahr_lock.release()

    @app.get("/v1/admin/captures/{identity}/image/{kind}",dependencies=[Depends(admin)])
    def image(identity: str,kind: str):
        if kind not in {"original","processed"}:
            raise HTTPException(404)
        row = db.capture_row(settings.database_path,identity)
        data = row.get("image_data" if kind == "original" else "processed_image") if row else None
        if not data:
            raise HTTPException(404,"该图像不存在")
        # Re-encode original for display: respect EXIF orientation without exposing metadata.
        from medicalfacefound.service.image import decode_image
        from medicalfacefound.service.quality import png_bytes
        return Response(png_bytes(decode_image(data).array),media_type="image/png")

    @app.get("/v1/admin/captures/{identity}/explanations/{prediction_id}",dependencies=[Depends(admin)])
    def explanation(identity: str,prediction_id: str,variant: ExplanationVariant = "block"):
        data = db.prediction_explanation(settings.database_path,identity,prediction_id,variant=variant)
        if not data:
            raise HTTPException(404,"该分析没有热力图")
        return Response(data,media_type="image/png",headers={"Cache-Control":"private, max-age=300"})

    @app.get("/v1/admin/export",dependencies=[Depends(admin)])
    def export(start: date | None = None,end: date | None = None,status: str = "all",tag: str | None = None):
        listing = db.list_captures(settings.database_path,**filters(start,end,status,tag),limit=10001)
        if listing["total"] > 10000:
            raise HTTPException(422,"单次最多导出一万条，请缩小日期范围")
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["采集编号","采集时间(UTC)","年龄","性别","身高(cm)","体重(kg)","来源","标签","同意版本","删除申请时间","指标","状态","预测值","单位","模型版本","尝试次数","分析时间(UTC)"])
        def safe(value):
            value = "" if value is None else str(value)
            return "'"+value if value.lstrip().startswith(("=","+","-","@")) or value.startswith(("\t","\r","\n")) else value
        for item in listing["items"]:
            record = db.report(settings.database_path,item["id"])
            if record is None:
                continue
            tags = "|".join(record.get("tags") or [])
            for prediction in record["predictions"] or [{}]:
                result = prediction.get("result") or {}
                writer.writerow([safe(x) for x in [record["id"],record["created_at"],record["age"],record["gender"],record["height_cm"],record["weight_kg"],record["capture_source"],tags,record["consent_version"],record["deletion_requested_at"],prediction.get("model"),prediction.get("status"),result.get("value"),result.get("unit"),prediction.get("model_version"),prediction.get("attempts"),prediction.get("updated_at")]])
        with db.connect(settings.database_path) as conn:
            db.audit(conn,"export")
        return Response("\ufeff"+output.getvalue(),media_type="text/csv; charset=utf-8",headers={"Content-Disposition":'attachment; filename="medicalfacefound-records.csv"'})

    @app.post("/v1/admin/backup",dependencies=[Depends(admin)])
    def backup():
        name = db.backup_database(settings.database_path)
        with db.connect(settings.database_path) as conn:
            db.audit(conn,"backup")
        return {"filename":name,"message":"备份已保存到数据库旁的 backups 目录"}

    @app.post("/v1/admin/captures/{identity}/delete",dependencies=[Depends(admin)])
    def delete(identity: str,body: DeleteConfirmation):
        if body.confirmation != identity:
            raise HTTPException(422,"请确认要删除的采集编号")
        with db.connect(settings.database_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM predictions WHERE capture_id=? AND status='running'",(identity,)).fetchone():
                raise HTTPException(409,"该记录正在分析，请结束后再删除")
            cursor = conn.execute("DELETE FROM captures WHERE id=?",(identity,))
            if not cursor.rowcount:
                raise HTTPException(404,"记录不存在")
            db.audit(conn,"delete",identity)
        return {"status":"deleted","message":"当前数据库记录及关联结果已删除；历史备份须按保留规则另行清理"}
