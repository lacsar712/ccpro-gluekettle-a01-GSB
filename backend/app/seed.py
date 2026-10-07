from sqlmodel import select

from app.db import get_session
from app.models import CookLog, GravityReading, Kettle, User, Workshop, utcnow
from app.security import hash_password


def seed_demo() -> None:
    with get_session() as session:
        admin = session.exec(select(User).where(User.username == "admin")).first()
        if admin is None:
            session.add(User(username="admin", password_hash=hash_password("123456"), role="admin"))
        else:
            admin.password_hash = hash_password("123456")
            admin.role = "admin"
        worker = session.exec(select(User).where(User.username == "worker")).first()
        if worker is None:
            session.add(User(username="worker", password_hash=hash_password("123456"), role="worker"))
        else:
            worker.password_hash = hash_password("123456")
            worker.role = "worker"
        if session.exec(select(Workshop)).first():
            session.commit()
            return
        shop = Workshop(name="骨巷熬胶坊", alley="西市骨巷")
        session.add(shop)
        session.flush()
        # (锅码, 状态, 台位, 峰值, 比重读数[(槽位, 比重, 取样人, 作废)])
        layout = [
            # 峰值够但无比重读数：演示双门槛之一缺失
            ("锅-1", Kettle.STATUS_BOILING, 0, 96.0, []),
            ("锅-2", Kettle.STATUS_COLD, 1, None, []),
            # 已出胶：峰值、比重两套都达标
            ("锅-3", Kettle.STATUS_DRAWN, 2, 102.0, [(1, 1.05, "worker", False), (2, 1.099, "worker", True)]),
            # 比重合格但峰值不足：演示峰值门槛
            ("锅-4", Kettle.STATUS_BOILING, 3, 82.0, [(1, 1.06, "worker", False)]),
            # 有读数但出带（低于 1.02）：不能放行
            ("锅-5", Kettle.STATUS_COLD, 4, None, [(1, 1.01, "worker", False)]),
            ("锅-6", Kettle.STATUS_DRAWN, 5, 94.0, [(1, 1.045, "worker", False)]),
        ]
        for code, status, bench, peak, gravities in layout:
            kettle = Kettle(workshop_id=shop.id, code=code, status=status, bench=bench)
            session.add(kettle)
            session.flush()
            if peak is not None:
                session.add(CookLog(kettle_id=kettle.id, peak_temp_c=peak, operator="worker"))
            for slot_no, gravity, sampler, voided in gravities:
                reading = GravityReading(
                    kettle_id=kettle.id,
                    slot_no=slot_no,
                    gravity=gravity,
                    sampled_at=utcnow(),
                    sampler=sampler,
                    voided_at=utcnow() if voided else None,
                )
                session.add(reading)
        session.commit()
