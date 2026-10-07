from datetime import datetime, timezone

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
    gravity_in_band,
    latest_peak,
    qualifying_gravity,
)
from app.models import CookLog, GravityReading, Kettle, User, Workshop
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
        .options(selectinload(Kettle.cooks), selectinload(Kettle.gravity_readings))
    ).first()


def reading_json(reading: GravityReading) -> dict:
    return {
        "id": reading.id,
        "kettleId": reading.kettle_id,
        "slotNo": reading.slot_no,
        "gravity": reading.gravity,
        "inBand": gravity_in_band(reading.gravity),
        "sampledAt": reading.sampled_at.isoformat(),
        "sampler": reading.sampler,
        "voidedAt": reading.voided_at.isoformat() if reading.voided_at else None,
    }


def kettle_json(kettle: Kettle) -> dict:
    qualified = qualifying_gravity(kettle)
    return {
        "id": kettle.id,
        "code": kettle.code,
        "status": kettle.status,
        "bench": kettle.bench,
        "latestPeakC": latest_peak(kettle),
        "cookCount": len(kettle.cooks or []),
        "gravityOk": qualified is not None,
        "gravityCount": len(
            [r for r in (kettle.gravity_readings or []) if r.voided_at is None]
        ),
        "qualifyingSlotNo": qualified.slot_no if qualified else None,
    }


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
            .options(selectinload(Kettle.cooks), selectinload(Kettle.gravity_readings))
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


async def list_gravity(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    kettle_id = int(request.path_params["kettle_id"])
    with get_session() as session:
        kettle = load_kettle(session, kettle_id)
        if kettle is None:
            return JSONResponse({"detail": "锅不存在"}, status_code=404)
        readings = sorted(
            kettle.gravity_readings or [], key=lambda r: (r.slot_no, r.sampled_at)
        )
        return JSONResponse(
            {
                "kettle": kettle_json(kettle),
                "readings": [reading_json(r) for r in readings],
            }
        )


async def add_gravity(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    kettle_id = int(request.path_params["kettle_id"])
    body = await request.json()
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
    raw_sampled = body.get("sampledAt")
    if raw_sampled:
        try:
            sampled_at = datetime.fromisoformat(str(raw_sampled).replace("Z", "+00:00"))
        except ValueError:
            return JSONResponse({"detail": "取样时刻格式无效"}, status_code=400)
        if sampled_at.tzinfo is None:
            sampled_at = sampled_at.replace(tzinfo=timezone.utc)
    else:
        sampled_at = datetime.now(timezone.utc)
    sampler = str(body.get("sampler") or user.username).strip()
    with get_session() as session:
        kettle = load_kettle(session, kettle_id)
        if kettle is None:
            return JSONResponse({"detail": "锅不存在"}, status_code=404)
        # 应用层先挡一道，给并发竞争留好可读错误；唯一索引兜底。
        clash = session.exec(
            select(GravityReading).where(
                GravityReading.kettle_id == kettle.id,
                GravityReading.slot_no == slot_no,
                GravityReading.voided_at.is_(None),
            )
        ).first()
        if clash is not None:
            return JSONResponse(
                {"detail": f"槽位 {slot_no} 已有未作废读数，禁止撞车"}, status_code=409
            )
        reading = GravityReading(
            kettle_id=kettle.id,
            slot_no=slot_no,
            gravity=gravity,
            sampled_at=sampled_at,
            sampler=sampler,
        )
        session.add(reading)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            return JSONResponse(
                {"detail": f"槽位 {slot_no} 已有未作废读数，禁止撞车"}, status_code=409
            )
        session.refresh(reading)
        return JSONResponse(reading_json(reading), status_code=201)


async def void_gravity(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    if user.role != "admin":
        return JSONResponse({"detail": "仅管理员可作废读数"}, status_code=403)
    kettle_id = int(request.path_params["kettle_id"])
    reading_id = int(request.path_params["reading_id"])
    with get_session() as session:
        reading = session.exec(
            select(GravityReading).where(
                GravityReading.id == reading_id,
                GravityReading.kettle_id == kettle_id,
            )
        ).first()
        if reading is None:
            return JSONResponse({"detail": "读数不存在"}, status_code=404)
        if reading.voided_at is None:
            reading.voided_at = datetime.now(timezone.utc)
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
        Route("/api/kettles/{kettle_id:int}/gravity", list_gravity),
        Route("/api/kettles/{kettle_id:int}/gravity", add_gravity, methods=["POST"]),
        Route(
            "/api/kettles/{kettle_id:int}/gravity/{reading_id:int}/void",
            void_gravity,
            methods=["POST"],
        ),
    ],
    middleware=[Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])],
)
