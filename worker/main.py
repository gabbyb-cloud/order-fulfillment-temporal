import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from temporalio.client import Client
from temporalio.worker import Worker

from activities.order_activities import (
    notify_customer,
    release_inventory,
    reserve_inventory,
    refund_payment,
    ship_order,
    validate_payment,
)
from workflows.order_workflow import OrderFulfillmentWorkflow

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)

TASK_QUEUE = "order-fulfillment-task-queue"
TEMPORAL_ADDRESS = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")


async def main() -> None:
    client = await Client.connect(TEMPORAL_ADDRESS)

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[OrderFulfillmentWorkflow],
        activities=[
            validate_payment,
            reserve_inventory,
            ship_order,
            notify_customer,
            refund_payment,
            release_inventory,
        ],
    )

    print(f"Worker started, listening on task queue '{TASK_QUEUE}'...")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
