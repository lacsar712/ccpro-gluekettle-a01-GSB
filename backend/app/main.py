from datetime import datetime

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from sqlmodel import SQLModel, select

from app.db import engine, get_session
from app.domain import (
    RuleError,
    assert_can_set_status,
    is_qualified,
    latest_peak,
    qualified_readings,
)
from app.models import CookLog, DensityReading, Kettle, User, Workshop, utcnow
from app.security import make_token, parse_token, verify_password
from app.seed import seed_demo


async def current_user(request: Request) -> User | None:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    username = parse_token(header.split(" ", 1)[1])
    if not username:
        return None
    with get_session() as session:
        return session.exec(select(User).where(User.username == username)).first()


def load_kettle(session, kettle_id: int) -> Kettle | None:
    return session.exec(
        select(Kettle)
        .where(Kettle.id == kettle_id)
        .options(selectinload(Kettle.cooks), selectinload(Kettle.readings))
    ).first()


def kettle_json(kettle: Kettle) -> dict:
    active = [r for r in (kettle.readings or []) if r.voided_at is None]
    return {
        "id": kettle.id,
        "code": kettle.code,
        "status": kettle.status,
        "bench": kettle.bench,
        "latestPeakC": latest_peak(kettle),
        "cookCount": len(kettle.cooks or []),
        "readingCount": len(active),
        "hasQualifiedReading": bool(qualified_readings(kettle)),
    }


def reading_json(reading: DensityReading, kettle_code: str = "") -> dict:
    code = kettle_code or (reading.kettle.code if reading.kettle else "")
    return {
        "id": reading.id,
        "kettleId": reading.kettle_id,
        "kettleCode": code,
        "slotNo": reading.slot_no,
        "gravity": reading.gravity,
        "sampledAt": reading.sampled_at.isoformat() if reading.sampled_at else None,
        "sampledBy": reading.sampled_by,
        "voidedAt": reading.voided_at.isoformat() if reading.voided_at else None,
        "qualified": is_qualified(reading),
    }


def parse_sampled_at(raw) -> datetime | None:
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        raise RuleError("取样时刻格式无效，应为 ISO 时间")


async def health(request: Request):
    return JSONResponse({"status": "ok", "service": "GlueKettle"})


async def login(request: Request):
    body = await request.json()
    with get_session() as session:
        user = session.exec(select(User).where(User.username == body.get("username", ""))).first()
        if user is None or not verify_password(body.get("password", ""), user.password_hash):
            return JSONResponse({"detail": "用户名或密码错误"}, status_code=401)
        return JSONResponse(
            {"access_token": make_token(user.username), "user": {"username": user.username, "role": user.role}}
        )


async def me(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    return JSONResponse({"username": user.username, "role": user.role})


async def board(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    with get_session() as session:
        shop = session.exec(select(Workshop)).first()
        if shop is None:
            return JSONResponse({"detail": "尚无熬胶坊"}, status_code=404)
        kettles = session.exec(
            select(Kettle)
            .where(Kettle.workshop_id == shop.id)
            .options(selectinload(Kettle.cooks), selectinload(Kettle.readings))
        ).all()
        loaded = sorted(kettles, key=lambda k: k.bench)
        return JSONResponse(
            {"workshop": shop.name, "alley": shop.alley, "kettles": [kettle_json(k) for k in loaded]}
        )


async def add_cook(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    kettle_id = int(request.path_params["kettle_id"])
    body = await request.json()
    try:
        peak = float(body.get("peakTempC"))
    except (TypeError, ValueError):
        return JSONResponse({"detail": "峰值温度必须是数字"}, status_code=400)
    with get_session() as session:
        kettle = load_kettle(session, kettle_id)
        if kettle is None:
            return JSONResponse({"detail": "锅不存在"}, status_code=404)
        session.add(CookLog(kettle_id=kettle.id, peak_temp_c=peak, operator=user.username))
        session.commit()
        kettle = load_kettle(session, kettle_id)
        return JSONResponse(kettle_json(kettle))


async def set_status(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    kettle_id = int(request.path_params["kettle_id"])
    body = await request.json()
    with get_session() as session:
        kettle = load_kettle(session, kettle_id)
        if kettle is None:
            return JSONResponse({"detail": "锅不存在"}, status_code=404)
        try:
            assert_can_set_status(kettle, body.get("status", ""))
        except RuleError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        kettle.status = body.get("status")
        session.add(kettle)
        session.commit()
        kettle = load_kettle(session, kettle_id)
        return JSONResponse(kettle_json(kettle))


async def list_readings(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    kettle_id = request.query_params.get("kettleId")
    with get_session() as session:
        stmt = select(DensityReading).options(selectinload(DensityReading.kettle))
        if kettle_id:
            try:
                stmt = stmt.where(DensityReading.kettle_id == int(kettle_id))
            except ValueError:
                return JSONResponse({"detail": "kettleId 必须是数字"}, status_code=400)
        stmt = stmt.order_by(DensityReading.kettle_id, DensityReading.slot_no, DensityReading.id)
        rows = session.exec(stmt).all()
        return JSONResponse({"readings": [reading_json(r) for r in rows]})


async def add_reading(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    body = await request.json()
    try:
        kettle_id = int(body.get("kettleId"))
    except (TypeError, ValueError):
        return JSONResponse({"detail": "锅码无效"}, status_code=400)
    try:
        slot_no = int(body.get("slotNo"))
    except (TypeError, ValueError):
        return JSONResponse({"detail": "槽位号必须是整数"}, status_code=400)
    if slot_no < 1:
        return JSONResponse({"detail": "槽位号从 1 起"}, status_code=400)
    try:
        gravity = float(body.get("gravity"))
    except (TypeError, ValueError):
        return JSONResponse({"detail": "比重必须是数字"}, status_code=400)
    if not (0 < gravity < 3):
        return JSONResponse({"detail": "比重数值超出合理范围"}, status_code=400)
    try:
        sampled_at = parse_sampled_at(body.get("sampledAt"))
    except RuleError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    with get_session() as session:
        kettle = session.get(Kettle, kettle_id)
        if kettle is None:
            return JSONResponse({"detail": "锅不存在"}, status_code=404)
        clash = session.exec(
            select(DensityReading).where(
                DensityReading.kettle_id == kettle_id,
                DensityReading.slot_no == slot_no,
                DensityReading.voided_at.is_(None),
            )
        ).first()
        if clash is not None:
            return JSONResponse(
                {"detail": f"锅 {kettle.code} 的槽位 {slot_no} 已有未作废读数，请换槽位号"},
                status_code=409,
            )
        reading = DensityReading(
            kettle_id=kettle_id,
            slot_no=slot_no,
            gravity=gravity,
            sampled_by=user.username,
        )
        if sampled_at is not None:
            reading.sampled_at = sampled_at
        session.add(reading)
        try:
            session.commit()
        except IntegrityError:
            # 并发撞车：同锅同槽位号的未作废读数只留一条
            session.rollback()
            return JSONResponse(
                {"detail": f"锅 {kettle.code} 的槽位 {slot_no} 已有未作废读数，请换槽位号"},
                status_code=409,
            )
        session.refresh(reading)
        return JSONResponse(reading_json(reading, kettle.code), status_code=201)


async def void_reading(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    if user.role != "admin":
        return JSONResponse({"detail": "仅管理员可作废读数"}, status_code=403)
    reading_id = int(request.path_params["reading_id"])
    with get_session() as session:
        reading = session.exec(
            select(DensityReading)
            .where(DensityReading.id == reading_id)
            .options(selectinload(DensityReading.kettle))
        ).first()
        if reading is None:
            return JSONResponse({"detail": "读数不存在"}, status_code=404)
        if reading.voided_at is not None:
            return JSONResponse({"detail": "该读数已作废"}, status_code=400)
        reading.voided_at = utcnow()
        session.add(reading)
        session.commit()
        session.refresh(reading)
        return JSONResponse(reading_json(reading))


def init() -> None:
    SQLModel.metadata.create_all(engine)
    seed_demo()


init()

app = Starlette(
    routes=[
        Route("/api/health", health),
        Route("/api/auth/login", login, methods=["POST"]),
        Route("/api/auth/me", me),
        Route("/api/board", board),
        Route("/api/kettles/{kettle_id:int}/cooks", add_cook, methods=["POST"]),
        Route("/api/kettles/{kettle_id:int}/status", set_status, methods=["POST"]),
        Route("/api/readings", list_readings),
        Route("/api/readings", add_reading, methods=["POST"]),
        Route("/api/readings/{reading_id:int}/void", void_reading, methods=["POST"]),
    ],
    middleware=[Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])],
)
