from fastapi import APIRouter

from app.api.v1.payments import router as payments_router

api_router = APIRouter()
api_router.include_router(payments_router)

__all__ = ["api_router"]
