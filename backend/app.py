import json
import os
from datetime import datetime, timedelta, timezone

import psycopg
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, Field
from psycopg.rows import dict_row

from rules import fry_step, judge

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


class PairIn(BaseModel):
    experiment_batch_id: int
    control_batch_id: int


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
            """CREATE TABLE IF NOT EXISTS pot_pairs (
                id serial PRIMARY KEY,
                experiment_batch_id integer NOT NULL REFERENCES batches(id),
                control_batch_id integer NOT NULL REFERENCES batches(id),
                created_by text NOT NULL,
                created_at timestamptz NOT NULL,
                unbound_by text,
                unbound_at timestamptz
            )"""
        )
        conn.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS pot_pairs_active_uniq
               ON pot_pairs (experiment_batch_id, control_batch_id)
               WHERE unbound_at IS NULL"""
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


def pair_payload(conn, pair: dict) -> dict:
    """把一条对照关系拼成专页要展示的对照包：两边工序 + 服务端算好的温度差与结论是否同向。"""
    rows = conn.execute(
        "SELECT id, herb, doc, verdict, reason FROM batches WHERE id = ANY(%s)",
        ([pair["experiment_batch_id"], pair["control_batch_id"]],),
    ).fetchall()
    by_id = {r["id"]: r for r in rows}

    def side(batch_id: int) -> dict:
        b = by_id[batch_id]
        step = fry_step(b["doc"]) or {}
        return {
            "batch_id": b["id"],
            "herb": b["herb"],
            "temp_c": step.get("temp_c"),
            "minutes": step.get("minutes"),
            "verdict": b["verdict"],
            "reason": b["reason"],
        }

    experiment = side(pair["experiment_batch_id"])
    control = side(pair["control_batch_id"])
    temp_diff = None
    if experiment["temp_c"] is not None and control["temp_c"] is not None:
        temp_diff = round(float(experiment["temp_c"]) - float(control["temp_c"]), 2)
    payload = {
        "id": pair["id"],
        "created_by": pair["created_by"],
        "created_at": pair["created_at"],
        "experiment": experiment,
        "control": control,
        "temp_diff": temp_diff,
        "same_direction": experiment["verdict"] == control["verdict"],
    }
    if pair["unbound_at"] is not None:
        payload["unbound_by"] = pair["unbound_by"]
        payload["unbound_at"] = pair["unbound_at"]
    return payload


@app.get("/api/pairs")
def list_pairs(_user: dict = Depends(current_user)):
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM pot_pairs WHERE unbound_at IS NULL ORDER BY id DESC"
        ).fetchall()
        return [pair_payload(conn, r) for r in rows]


@app.get("/api/pairs/history")
def pair_history(_user: dict = Depends(current_user)):
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM pot_pairs WHERE unbound_at IS NOT NULL ORDER BY unbound_at DESC"
        ).fetchall()
        return [pair_payload(conn, r) for r in rows]


@app.post("/api/pairs", status_code=201)
def create_pair(body: PairIn, user: dict = Depends(require_writer)):
    if body.experiment_batch_id == body.control_batch_id:
        raise HTTPException(status_code=400, detail="实验锅与对照锅不能是同一笔")
    with connect() as conn:
        for batch_id in (body.experiment_batch_id, body.control_batch_id):
            exists = conn.execute("SELECT 1 FROM batches WHERE id = %s", (batch_id,)).fetchone()
            if not exists:
                raise HTTPException(status_code=404, detail=f"记录 {batch_id} 不存在")
        dup = conn.execute(
            """SELECT 1 FROM pot_pairs
               WHERE unbound_at IS NULL AND experiment_batch_id = %s AND control_batch_id = %s""",
            (body.experiment_batch_id, body.control_batch_id),
        ).fetchone()
        if dup:
            raise HTTPException(status_code=409, detail="该对照已存在")
        pair = conn.execute(
            """INSERT INTO pot_pairs (experiment_batch_id, control_batch_id, created_by, created_at)
               VALUES (%s, %s, %s, %s) RETURNING *""",
            (body.experiment_batch_id, body.control_batch_id, user["username"], datetime.now(timezone.utc)),
        ).fetchone()
        conn.commit()
        return pair_payload(conn, pair)


@app.post("/api/pairs/{pair_id}/unbind")
def unbind_pair(pair_id: int, user: dict = Depends(require_writer)):
    with connect() as conn:
        pair = conn.execute("SELECT * FROM pot_pairs WHERE id = %s", (pair_id,)).fetchone()
        if pair is None:
            raise HTTPException(status_code=404, detail="对照不存在")
        if pair["unbound_at"] is not None:
            raise HTTPException(status_code=409, detail="对照已解除")
        pair = conn.execute(
            """UPDATE pot_pairs SET unbound_by = %s, unbound_at = %s
               WHERE id = %s RETURNING *""",
            (user["username"], datetime.now(timezone.utc), pair_id),
        ).fetchone()
        conn.commit()
        return pair_payload(conn, pair)
