from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.outbox import Outbox
from app.models.payment import Currency, Payment, PaymentStatus


class IdempotencyConflict(Exception):
    """Raised when idempotency_key already exists but with different payload."""


async def get_payment_by_id(session: AsyncSession, payment_id: UUID) -> Payment | None:
    stmt = select(Payment).where(Payment.id == payment_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_payment_by_idempotency_key(
    session: AsyncSession, idempotency_key: str
) -> Payment | None:
    stmt = select(Payment).where(Payment.idempotency_key == idempotency_key)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def create_payment(
    session: AsyncSession,
    *,
    idempotency_key: str,
    amount: Decimal,
    currency: Currency,
    description: str | None,
    meta: dict | None,
    webhook_url: str,
) -> Payment:
    existing = await get_payment_by_idempotency_key(session, idempotency_key)
    if existing is not None:
        return existing

    payment = Payment(
        amount=amount,
        currency=currency,
        description=description,
        meta=meta,
        status=PaymentStatus.PENDING,
        idempotency_key=idempotency_key,
        webhook_url=webhook_url,
    )
    session.add(payment)
    await session.flush()

    outbox_event = Outbox(
        event_type="payment.created",
        payload={
            "payment_id": str(payment.id),
            "amount": str(payment.amount),
            "currency": payment.currency.value,
            "webhook_url": payment.webhook_url,
        },
        status="pending",
    )
    session.add(outbox_event)

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await get_payment_by_idempotency_key(session, idempotency_key)
        if existing is not None:
            return existing
        raise

    await session.refresh(payment)
    return payment
