import asyncio
import json
import logging
from datetime import datetime, timezone

import aio_pika
from sqlalchemy import select

from app.core.config import settings
from app.db.session import async_session_maker
from app.models.outbox import Outbox

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("outbox-publisher")

POLL_INTERVAL = 2


async def publish_pending_events() -> None:
    connection = await aio_pika.connect_robust(settings.rabbitmq_url)
    async with connection:
        channel = await connection.channel()
        await channel.declare_queue(settings.payments_queue, durable=True)

        while True:
            try:
                async with async_session_maker() as session:
                    stmt = (
                        select(Outbox)
                        .where(Outbox.status == "pending")
                        .order_by(Outbox.created_at)
                        .limit(50)
                        .with_for_update(skip_locked=True)
                    )
                    result = await session.execute(stmt)
                    events = result.scalars().all()

                    for event in events:
                        message = aio_pika.Message(
                            body=json.dumps(event.payload).encode(),
                            content_type="application/json",
                            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                            message_id=str(event.id),
                        )
                        await channel.default_exchange.publish(
                            message, routing_key=settings.payments_queue
                        )
                        event.status = "published"
                        event.published_at = datetime.now(timezone.utc)
                        logger.info(f"Published event {event.id} ({event.event_type})")

                    await session.commit()
            except Exception as e:
                logger.error(f"Publisher error: {e}")

            await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    asyncio.run(publish_pending_events())
