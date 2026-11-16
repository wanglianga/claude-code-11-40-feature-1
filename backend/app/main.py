from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import API_PREFIX
from .db import init_db
from .routers import auth, catalog, probability, records, reid, surveys


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="自然保护区季节调查完整性、覆盖与个体重识别证据数据服务",
    description=(
        "交付季节调查覆盖与有效性证书数据，以及野生动物个体重识别证据链、"
        "专家裁定与样线统计账。服务不派发巡护任务、不预约人员器材，"
        "也不改变动物管理、捕捉、放归或保护行动。"
    ),
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (auth, catalog, surveys, records, probability, reid):
    app.include_router(module.router, prefix=API_PREFIX)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "survey-integrity-and-reid"}
