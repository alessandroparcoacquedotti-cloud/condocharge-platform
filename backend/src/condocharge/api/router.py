from __future__ import annotations

from fastapi import APIRouter

from condocharge.api.v1.router import router as api_v1_router

api_router = APIRouter(prefix="/api")
api_router.include_router(api_v1_router)


@api_router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
