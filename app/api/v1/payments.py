from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_api_key
from app.db.session import get_session
from app.schemas.payment import (
    PaymentCreateRequest,
    PaymentCreateResponse,
    PaymentDetailResponse,
)
from app.services.payment import create_payment, get_payment_by_id

router = APIRouter(prefix="/api/v1/payments", tags=["payments"])


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=PaymentCreateResponse,
    dependencies=[Depends(verify_api_key)],
)
async def create_payment_endpoint(
    payload: PaymentCreateRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_session),
) -> PaymentCreateResponse:
    payment = await create_payment(
        session,
        idempotency_key=idempotency_key,
        amount=payload.amount,
        currency=payload.currency,
        description=payload.description,
        meta=payload.meta,
        webhook_url=str(payload.webhook_url),
    )
    return PaymentCreateResponse(
        payment_id=payment.id,
        status=payment.status,
        created_at=payment.created_at,
    )


@router.get(
    "/{payment_id}",
    response_model=PaymentDetailResponse,
    dependencies=[Depends(verify_api_key)],
)
async def get_payment_endpoint(
    payment_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> PaymentDetailResponse:
    payment = await get_payment_by_id(session, payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    return PaymentDetailResponse.model_validate(payment)
