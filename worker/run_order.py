import asyncio
import sys
import uuid
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from temporalio.client import Client

from workflows.models import OrderInput
from workflows.order_workflow import OrderFulfillmentWorkflow

TASK_QUEUE = "order-fulfillment-task-queue"


async def main():
    client = await Client.connect("localhost:7233")

    order_id = f"order-{uuid.uuid4().hex[:8]}"
    order = OrderInput(
        order_id=order_id,
        customer_name="Demo Customer",
        item="Mechanical Keyboard",
        quantity=1,
        amount_cents=8999,
    )

    print(f"Starting workflow for {order_id}...")

    handle = await client.start_workflow(
        OrderFulfillmentWorkflow.run,
        order,
        id=order_id,
        task_queue=TASK_QUEUE,
    )

    # Poll status via query a couple times while it runs, just to
    # demonstrate the query is live and working.
    await asyncio.sleep(1)
    try:
        status = await handle.query(OrderFulfillmentWorkflow.get_status)
        print(f"Current status (query): {status}")
    except Exception as e:
        print(f"(status query not available yet: {e})")

    result = await handle.result()
    print(f"Final result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
