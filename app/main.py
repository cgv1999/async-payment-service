from fastapi import FastAPI

from app.api.v1 import api_router

app = FastAPI(
    title="Async Payment Service",
    version="1.0.0",
    description="Асинхронный сервис процессинга платежей",
)

app.include_router(api_router)


@app.get("/health", tags=["system"])
async def health() -> dict:
    return {"status": "ok"}
