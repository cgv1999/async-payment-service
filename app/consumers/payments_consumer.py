import asyncio
import logging
import random
from datetime import datetime, timezone
from uuid import UUID

import aiohttp
from faststream import FastStream
from faststream.rabbit import RabbitBroker, RabbitExchange, RabbitQueue
from sqlalchemy import select

from app.core.config import settings
from app.db.session import async_session_maker
from app.models.payment import Payment, PaymentStatus

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("payments-consumer")

broker = RabbitBroker(settings.rabbitmq_url)
app = FastStream(broker)

dlx_exchange = RabbitExchange("payments.dlx", durable=True)

payments_queue = RabbitQueue(
    settings.payments_queue,
    durable=True,
    routing_key="payments.new",
    arguments={
        "x-dead-letter-exchange": "payments.dlx",
        "x-dead-letter-routing-key": "payments.new.dlq",
    },
)

dlq_queue = RabbitQueue(
    settings.payments_dlq,
    durable=True,
    routing_key="payments.new.dlq",
)

DLQ_MAX_RETRIES = 3


async def send_webhook(url: str, payload: dict) -> bool:
    try:
        timeout = aiohttp.ClientTimeout(total=settings.webhook_timeout)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload) as resp:
                if 200 <= resp.status < 300:
                    return True
                logger.warning(f"Webhook returned {resp.status}")
                return False
    except Exception as e:
        logger.warning(f"Webhook error: {e}")
        return False


async def send_webhook_with_retry(url: str, payload: dict) -> bool:
    for attempt in range(1, DLQ_MAX_RETRIES + 1):
        if await send_webhook(url, payload):
            return True
        delay = 2 ** attempt
        logger.info(f"Retry webhook in {delay}s (attempt {attempt}/{DLQ_MAX_RETRIES})")
        await asyncio.sleep(delay)
    return False


async def emulate_gateway() -> bool:
    await asyncio.sleep(random.uniform(2, 5))
    return random.random() < 0.9


@broker.subscriber(payments_queue, exchange="")
async def handle_payment(body: dict) -> None:
    payment_id_raw = body.get("payment_id")
    if not payment_id_raw:
        logger.error(f"No payment_id in message: {body}")
        return

    payment_id = UUID(payment_id_raw)
    logger.info(f"Processing payment {payment_id}")

    async with async_session_maker() as session:
        stmt = select(Payment).where(Payment.id == payment_id)
        result = await session.execute(stmt)
        payment = result.scalar_one_or_none()

        if payment is None:
            logger.error(f"Payment {payment_id} not found")
            return

        if payment.status != PaymentStatus.PENDING:
            logger.info(f"Payment {payment_id} already processed: {payment.status}")
            return

        success = await emulate_gateway()
        payment.status = PaymentStatus.SUCCEEDED if success else PaymentStatus.FAILED
        payment.processed_at = datetime.now(timezone.utc)
        await session.commit()

        webhook_payload = {
            "payment_id": str(payment.id),
            "status": payment.status.value,
            "amount": str(payment.amount),
            "currency": payment.currency.value,
            "processed_at": payment.processed_at.isoformat(),
        }

        delivered = await send_webhook_with_retry(payment.webhook_url, webhook_payload)
        if not delivered:
            logger.error(f"Webhook failed after {DLQ_MAX_RETRIES} retries: {payment.id}")
            await broker.publish(
                body,
                queue=dlq_queue,
                exchange=dlx_exchange,
            )
            logger.info(f"Sent to DLQ: {payment.id}")
            return

        logger.info(f"Webhook delivered for {payment.id}")


@broker.subscriber(dlq_queue, exchange=dlx_exchange)
async def handle_dlq(body: dict) -> None:
    """DLQ subscriber: нужен для автоматического создания exchange/queue/binding."""
    logger.error(f"DLQ message: {body}")


if __name__ == "__main__":
    asyncio.run(app.run())
