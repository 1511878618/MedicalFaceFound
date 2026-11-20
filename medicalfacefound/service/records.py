"""Per-record consent and user-entered measurements; no implicit training consent."""
import json
from datetime import date
from typing import Literal
from uuid import uuid4

from fastapi import HTTPException, Request, Header
from pydantic import BaseModel, Field

from medicalfacefound.service import database as db
from medicalfacefound.service.catalog import CATALOG, RESEARCH_CONSENT_VERSION


class ConsentUpdate(BaseModel):
    research: bool
    training: bool = False
    version: str


class Observation(BaseModel):
    model: str
    value: float = Field(ge=0, allow_inf_nan=False)
    unit: str = Field(min_length=1, max_length=32)
    measured_on: date
    source: Literal['self_report', 'lab_report']


class ClinicalInformation(BaseModel):
    medical_history: str = Field(default='', max_length=2000)
    medications: str = Field(default='', max_length=2000)
    family_history: str = Field(default='', max_length=2000)
    smoking: str = Field(default='', max_length=2000)
    alcohol: str = Field(default='', max_length=2000)
    notes: str = Field(default='', max_length=2000)


class SubjectUpdate(BaseModel):
    subject_id: str = Field(min_length=1,max_length=100)


class DeleteRecord(BaseModel):
    confirmation: str


def delete_capture(path, identity):
    with db.connect(path) as conn:
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute("SELECT 1 FROM predictions WHERE capture_id=? AND status='running'", (identity,)).fetchone():
            raise HTTPException(409, '该记录正在分析，请结束后再删除')
        if not conn.execute('DELETE FROM captures WHERE id=?', (identity,)).rowcount:
            raise HTTPException(404, '记录不存在')
        db.audit(conn, 'delete', identity)


def add_record_routes(app, settings, authorize):
    path = settings.database_path

    @app.delete('/v1/captures/{identity}')
    def delete(identity: str, body: DeleteRecord, request: Request, authorization: str | None = Header(None)):
        authorize(identity, authorization, request)
        if body.confirmation != identity:
            raise HTTPException(422, '请确认完整的采集编号')
        delete_capture(path, identity)
        return {'status': 'deleted', 'message': '记录及关联结果已删除；历史备份按保留规则另行处理。'}

    @app.put('/v1/captures/{identity}/research-consent')
    def consent(identity: str, body: ConsentUpdate, request: Request, authorization: str | None = Header(None)):
        authorized = authorize(identity, authorization, request)
        if body.research and authorized.get("subject_id", "unknown") == "unknown":
            raise HTTPException(422, "请先确认记录所属对象")
        if body.version != RESEARCH_CONSENT_VERSION or (body.training != body.research):
            raise HTTPException(422, '请确认当前科研授权，包含模型评估与训练')
        with db.connect(path) as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT deletion_requested_at,subject_id FROM captures WHERE id=?', (identity,)).fetchone()
            if not row or row[0]:
                raise HTTPException(409, '记录不存在或已申请删除')
            if body.research and row[1] == 'unknown':
                raise HTTPException(422, '请先确认记录所属对象')
            stamp = db.now()
            conn.execute('''UPDATE captures SET research_consent=?,training_consent=?,
                research_consent_version=?,research_consented_at=? WHERE id=?''',
                (int(body.research), int(body.training), body.version, stamp, identity))
            conn.execute('INSERT INTO consent_events VALUES (?,?,?,?,?,?)',
                (str(uuid4()), identity, int(body.research), int(body.training), body.version, stamp))
            if not body.research:
                conn.execute('DELETE FROM observations WHERE capture_id=?', (identity,))
                conn.execute('DELETE FROM clinical_information WHERE capture_id=?', (identity,))
            db.audit(conn, 'consent_update', identity, detail={'research': body.research, 'training': body.training})
        return db.report(path, identity)

    @app.put('/v1/captures/{identity}/observations')
    def observation(identity: str, body: Observation, request: Request, authorization: str | None = Header(None)):
        authorize(identity, authorization, request)
        if body.model not in CATALOG or body.model == 'CAD':
            raise HTTPException(422, '该指标暂不接受实测值')
        if body.measured_on > date.today() or body.measured_on.year < 1900 or not body.unit.strip():
            raise HTTPException(422, '请填写有效的检测日期和单位，检测日期不能晚于今天')
        with db.connect(path) as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT research_consent,deletion_requested_at,research_consent_version FROM captures WHERE id=?', (identity,)).fetchone()
            if not row or row[1]:
                raise HTTPException(409, '记录不存在或已申请删除')
            if not row[0] or row[2] != RESEARCH_CONSENT_VERSION:
                raise HTTPException(403, '补充实测值需先授权本条记录参与科研')
            conn.execute('''INSERT INTO observations VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(capture_id,model) DO UPDATE SET value=excluded.value,unit=excluded.unit,
                measured_on=excluded.measured_on,source=excluded.source,updated_at=excluded.updated_at''',
                (identity, body.model, body.value, body.unit.strip(), body.measured_on.isoformat(), body.source, db.now()))
        return db.report(path, identity)

    @app.delete('/v1/captures/{identity}/observations/{model}')
    def remove_observation(identity: str, model: str, request: Request, authorization: str | None = Header(None)):
        authorize(identity, authorization, request)
        with db.connect(path) as conn:
            conn.execute('DELETE FROM observations WHERE capture_id=? AND model=?', (identity, model))
        return db.report(path, identity)

    @app.put('/v1/captures/{identity}/clinical-information')
    def clinical(identity: str, body: ClinicalInformation, request: Request, authorization: str | None = Header(None)):
        authorize(identity, authorization, request)
        with db.connect(path) as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT research_consent,research_consent_version,deletion_requested_at FROM captures WHERE id=?', (identity,)).fetchone()
            if not row or row[2]:
                raise HTTPException(409, '记录不存在或已申请删除')
            if not row[0] or row[1] != RESEARCH_CONSENT_VERSION:
                raise HTTPException(403, '请先确认本条记录的科研授权')
            values = {key: value.strip() for key, value in body.model_dump().items()}
            conn.execute('INSERT INTO clinical_information VALUES (?,?,?) ON CONFLICT(capture_id) DO UPDATE SET information_json=excluded.information_json,updated_at=excluded.updated_at',
                         (identity, json.dumps(values, ensure_ascii=False), db.now()))
        return db.report(path, identity)

    @app.put('/v1/captures/{identity}/subject')
    def update_subject(identity: str, body: SubjectUpdate, request: Request, authorization: str | None = Header(None)):
        from medicalfacefound.service import accounts
        row=authorize(identity,authorization,request)
        user=accounts.current_user(path,request)
        if row['participant_id']:
            if not user or user['id']!=row['participant_id']: raise HTTPException(403,'请登录所属账号后更改记录归属')
            accounts.validate_subject(path,body.subject_id,user)
        elif body.subject_id not in {'self','unknown'}:
            raise HTTPException(403,'匿名记录不能关联账号成员')
        with db.connect(path) as conn:
            conn.execute('BEGIN IMMEDIATE')
            current=conn.execute('SELECT subject_id,deletion_requested_at FROM captures WHERE id=?',(identity,)).fetchone()
            if not current: raise HTTPException(404,'记录不存在')
            if current[1] or conn.execute("SELECT 1 FROM predictions WHERE capture_id=? AND status='running'",(identity,)).fetchone():
                raise HTTPException(409,'记录正在分析或已申请删除')
            if current[0]!=body.subject_id:
                stamp=db.now()
                conn.execute('UPDATE captures SET subject_id=?,research_consent=0,training_consent=0,research_consent_version=NULL,research_consented_at=NULL WHERE id=?',(body.subject_id,identity))
                conn.execute('INSERT INTO consent_events VALUES (?,?,?,?,?,?)',(str(uuid4()),identity,0,0,RESEARCH_CONSENT_VERSION,stamp))
                db.audit(conn,'subject_update',identity,detail={'from':current[0],'to':body.subject_id})
        return db.report(path,identity)
