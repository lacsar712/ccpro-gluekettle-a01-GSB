# GlueKettle-01 · 骨巷熬胶坊

一排熬锅作业台。登录后是横向锅位，点锅登记煮胶峰值并改状态。前端是原生 JS，没有 React/Vue/Svelte。

## 技术栈

| 层 | 技术 |
| --- | --- |
| Web API | Starlette 路由表（不是 FastAPI Depends） |
| 结构 | SQLModel 实体 + `domain.py` 门槛 |
| 数据 | SQLModel / SQLAlchemy · psycopg2 · PostgreSQL 15 |
| 前端 | 原生 ES Module · Vite 仅打包 |
| 部署 | Docker Compose |

## 路径与端口

- 前端：http://localhost:4790
- API：http://localhost:8790
- PostgreSQL：localhost:6190

## 演示账号

`admin` / `123456`，`worker` / `123456`

## 业务规则

锅不可标「已出胶」，除非**两套门槛同时满足**（规则在 `backend/app/domain.py`）：

1. 最近一次煮胶峰值 **≥ 90℃**；
2. 至少一条**未作废**的比重计读数落在 **1.02–1.08（含）**；出带读数不能放行。

比重读数（`backend/app/models.py` 的 `GravityReading`）：

- 字段：锅码、槽位号（从 1 起）、比重、取样时刻、取样人、作废时刻（可空）。
- 操作工可新建；作废仅管理员。
- 同锅未作废槽位号唯一：应用层预检 + 数据库部分唯一索引
  `(kettle_id, slot_no) WHERE voided_at IS NULL` 双重兜底，并发抢交只留一条。
- 入口在顶栏「比重计」独立专页：按锅筛选、新建、作废，不是抽屉里塞一张表。

## 快速启动

```bash
cd GlueKettle/GlueKettle-01
docker compose up --build
```
