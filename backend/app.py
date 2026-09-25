import json
import os
from datetime import datetime, timedelta, timezone

import psycopg
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

from rules import judge

SECRET = os.environ.get("JWT_SECRET", "herb-process-dev-secret")
DSN = os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:54393/herb")
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)
USERS = {
    "processor": {"role": "writer", "password_hash": pwd.hash("herb123456")},
    "checker": {"role": "reader", "password_hash": pwd.hash("check123456")},
}


def connect():
    return psycopg.connect(DSN, row_factory=dict_row)


class LoginIn(BaseModel):
    username: str
    password: str


class StepIn(BaseModel):
    name: str
    temp_c: float
    minutes: float


class BatchIn(BaseModel):
    herb: str = Field(min_length=1, max_length=80)
    steps: list[StepIn]


class CompareIn(BaseModel):
    experiment_id: int = Field(gt=0)
    control_id: int = Field(gt=0)


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(security)) -> dict:
    if credentials is None:
        raise HTTPException(status_code=401, detail="未登录")
    try:
        payload = jwt.decode(credentials.credentials, SECRET, algorithms=["HS256"])
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="无效令牌") from exc
    if payload.get("sub") not in USERS:
        raise HTTPException(status_code=401, detail="无效令牌")
    return {"username": payload["sub"], "role": payload.get("role")}


def require_writer(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "writer":
        raise HTTPException(status_code=403, detail="仅炮制员可写入记录")
    return user


app = FastAPI(title="饮片炮制记录台")


@app.on_event("startup")
def startup():
    with connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS batches (
                id serial PRIMARY KEY,
                herb text NOT NULL,
                doc jsonb NOT NULL,
                verdict text NOT NULL,
                reason text NOT NULL,
                created_by text NOT NULL,
                created_at timestamptz NOT NULL
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS comparisons (
                id serial PRIMARY KEY,
                experiment_id integer NOT NULL REFERENCES batches(id),
                control_id integer NOT NULL REFERENCES batches(id),
                created_by text NOT NULL,
                created_at timestamptz NOT NULL,
                released_by text,
                released_at timestamptz,
                CONSTRAINT different_pots CHECK (experiment_id <> control_id)
            )"""
        )
        count = conn.execute("SELECT COUNT(*) AS n FROM batches").fetchone()["n"]
        if count == 0:
            now = datetime.now(timezone.utc)
            samples = [
                ("甘草", {"steps": [{"name": "清炒", "temp_c": 120, "minutes": 12}]}),
                ("黄芩", {"steps": [{"name": "清炒", "temp_c": 40, "minutes": 12}]}),
            ]
            for herb, doc in samples:
                verdict, reason = judge(doc)
                conn.execute(
                    """INSERT INTO batches (herb, doc, verdict, reason, created_by, created_at)
                       VALUES (%s, %s::jsonb, %s, %s, %s, %s)""",
                    (herb, json.dumps(doc, ensure_ascii=False), verdict, reason, "processor", now),
                )
        conn.commit()


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "herb-process-record"}


@app.post("/api/auth/login")
def login(body: LoginIn):
    user = USERS.get(body.username.strip())
    if not user or not pwd.verify(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    exp = datetime.now(timezone.utc) + timedelta(hours=8)
    token = jwt.encode({"sub": body.username.strip(), "role": user["role"], "exp": exp}, SECRET, algorithm="HS256")
    return {"access_token": token, "username": body.username.strip(), "role": user["role"]}


@app.get("/api/batches")
def list_batches(_user: dict = Depends(current_user)):
    with connect() as conn:
        rows = conn.execute("SELECT id, herb, doc, verdict, reason, created_by FROM batches ORDER BY id DESC").fetchall()
    return rows


@app.post("/api/batches", status_code=201)
def create_batch(body: BatchIn, user: dict = Depends(require_writer)):
    doc = {"steps": [s.model_dump() for s in body.steps]}
    verdict, reason = judge(doc)
    with connect() as conn:
        row = conn.execute(
            """INSERT INTO batches (herb, doc, verdict, reason, created_by, created_at)
               VALUES (%s, %s::jsonb, %s, %s, %s, %s)
               RETURNING id, herb, doc, verdict, reason, created_by""",
            (body.herb.strip(), json.dumps(doc, ensure_ascii=False), verdict, reason, user["username"], datetime.now(timezone.utc)),
        ).fetchone()
        conn.commit()
    return row


# 联锅对照：实验锅、对照锅各取一锅，温度差与结论是否同向一律由服务端计算。
COMPARE_SELECT = """
    SELECT c.id,
           c.experiment_id, c.control_id,
           c.created_by, c.created_at,
           c.released_by, c.released_at,
           be.herb AS experiment_herb, be.doc AS experiment_doc,
           be.verdict AS experiment_verdict, be.reason AS experiment_reason,
           bc.herb AS control_herb, bc.doc AS control_doc,
           bc.verdict AS control_verdict, bc.reason AS control_reason
      FROM comparisons c
      JOIN batches be ON be.id = c.experiment_id
      JOIN batches bc ON bc.id = c.control_id
"""


def _fry_step(doc: dict) -> dict | None:
    return next((s for s in (doc.get("steps") or []) if s.get("name") == "清炒"), None)


def _fry_temp(doc: dict) -> float | None:
    fry = _fry_step(doc)
    if fry is None or fry.get("temp_c") is None:
        return None
    return float(fry["temp_c"])


def _fry_minutes(doc: dict) -> float | None:
    fry = _fry_step(doc)
    if fry is None or fry.get("minutes") is None:
        return None
    return float(fry["minutes"])


def _with_diff(row: dict) -> dict:
    exp_temp, ctl_temp = _fry_temp(row["experiment_doc"]), _fry_temp(row["control_doc"])
    exp_min, ctl_min = _fry_minutes(row["experiment_doc"]), _fry_minutes(row["control_doc"])
    row["experiment_temp"] = exp_temp
    row["control_temp"] = ctl_temp
    row["experiment_minutes"] = exp_min
    row["control_minutes"] = ctl_min
    row["temp_diff"] = None if exp_temp is None or ctl_temp is None else round(exp_temp - ctl_temp, 2)
    row["minutes_diff"] = None if exp_min is None or ctl_min is None else round(exp_min - ctl_min, 2)
    row["verdict_same"] = row["experiment_verdict"] == row["control_verdict"]
    return row


def _fetch_batches(conn, ids: list[int]) -> dict:
    rows = conn.execute(
        "SELECT id, herb, doc, verdict, reason FROM batches WHERE id = ANY(%s)",
        (ids,),
    ).fetchall()
    return {r["id"]: r for r in rows}


@app.post("/api/comparisons", status_code=201)
def create_comparison(body: CompareIn, user: dict = Depends(require_writer)):
    now = datetime.now(timezone.utc)
    with connect() as conn:
        found = _fetch_batches(conn, [body.experiment_id, body.control_id])
        missing = [i for i in (body.experiment_id, body.control_id) if i not in found]
        if missing:
            raise HTTPException(status_code=404, detail=f"锅次编号不存在：{missing}")
        active = conn.execute(
            """SELECT id FROM comparisons
               WHERE released_at IS NULL
                 AND (%s IN (experiment_id, control_id) OR %s IN (experiment_id, control_id))""",
            (body.experiment_id, body.control_id),
        ).fetchone()
        if active:
            raise HTTPException(status_code=409, detail="其中一锅已在生效对照中，先解除再指定")
        row = conn.execute(
            """INSERT INTO comparisons (experiment_id, control_id, created_by, created_at)
               VALUES (%s, %s, %s, %s)
               RETURNING id""",
            (body.experiment_id, body.control_id, user["username"], now),
        ).fetchone()
        conn.commit()
        item = conn.execute(COMPARE_SELECT + " WHERE c.id = %s", (row["id"],)).fetchone()
    return _with_diff(item)


@app.get("/api/comparisons")
def list_active_comparisons(_user: dict = Depends(current_user)):
    with connect() as conn:
        rows = conn.execute(
            COMPARE_SELECT + " WHERE c.released_at IS NULL ORDER BY c.id DESC"
        ).fetchall()
    return [_with_diff(r) for r in rows]


@app.get("/api/comparisons/history")
def comparison_history(_user: dict = Depends(current_user)):
    with connect() as conn:
        rows = conn.execute(
            COMPARE_SELECT
            + " WHERE c.released_at IS NOT NULL ORDER BY c.released_at DESC, c.id DESC"
        ).fetchall()
    return [_with_diff(r) for r in rows]


@app.post("/api/comparisons/{comparison_id}/release")
def release_comparison(comparison_id: int, user: dict = Depends(require_writer)):
    now = datetime.now(timezone.utc)
    with connect() as conn:
        row = conn.execute(
            """UPDATE comparisons SET released_by = %s, released_at = %s
                WHERE id = %s AND released_at IS NULL
            RETURNING id""",
            (user["username"], now, comparison_id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="生效对照不存在或已解除")
        conn.commit()
        item = conn.execute(COMPARE_SELECT + " WHERE c.id = %s", (comparison_id,)).fetchone()
    return _with_diff(item)
