import asyncio
import sys
import uuid
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from temporalio.client import Client

from workflows.models import OrderInput
from workflows.order_workflow import OrderFulfillmentWorkflow

TASK_QUEUE = "order-fulfillment-task-queue"
DEMO_DELAY_SECONDS = 20


async def main():
    client = await Client.connect("localhost:7233")

    order_id = f"order-crash-demo-{uuid.uuid4().hex[:8]}"
    order = OrderInput(
        order_id=order_id,
        customer_name="Demo Customer",
        item="Mechanical Keyboard",
        quantity=1,
        amount_cents=8999,
        demo_delay_seconds=DEMO_DELAY_SECONDS,
    )

    print(f"Starting workflow for {order_id}...")
    print(
        f"This order pauses for {DEMO_DELAY_SECONDS}s right after payment "
        f"validation — that's your window to go kill the worker (Ctrl+C in "
        f"its window) and restart it. This script will keep waiting and "
        f"print the final result once the workflow completes, proving it "
        f"resumed rather than restarted."
    )

    handle = await client.start_workflow(
        OrderFulfillmentWorkflow.run,
        order,
        id=order_id,
        task_queue=TASK_QUEUE,
    )

    result = await handle.result()
    print(f"Final result: {result}")
    print(
        "If you killed and restarted the worker during the pause and this "
        "still completed successfully, the workflow resumed correctly "
        "instead of restarting from Step 1."
    )


if __name__ == "__main__":
    asyncio.run(main())
