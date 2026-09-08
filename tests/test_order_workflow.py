"""
Workflow tests using Temporal's WorkflowEnvironment test framework.

These use time-skipping (so a workflow with sleeps/timeouts runs
instantly in tests) and mocked activities (so results are deterministic
instead of depending on the random failure injection used for manual
demos). This is what "Temporal has a test framework for time-skipping
and mocking activities" from the design doc refers to.

Run with: pytest tests/ -v
"""

import sys
import uuid
from pathlib import Path

import pytest
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

sys.path.append(str(Path(__file__).resolve().parent.parent))

from workflows.models import OrderInput
from workflows.order_workflow import OrderFulfillmentWorkflow

TASK_QUEUE = "test-task-queue"


# --- Deterministic mock activities (replace the real, randomized ones) ---


@activity.defn(name="validate_payment")
async def mock_validate_payment_success(order: OrderInput) -> str:
    return f"payment-auth-{order.order_id}"


@activity.defn(name="reserve_inventory")
async def mock_reserve_inventory_success(order: OrderInput) -> str:
    return f"reservation-{order.order_id}"


@activity.defn(name="ship_order")
async def mock_ship_order_success(order: OrderInput) -> str:
    return f"tracking-{order.order_id}"


@activity.defn(name="notify_customer")
async def mock_notify_customer(order: OrderInput, message: str) -> None:
    pass


@activity.defn(name="refund_payment")
async def mock_refund_payment(order: OrderInput, payment_auth: str) -> None:
    pass


@activity.defn(name="release_inventory")
async def mock_release_inventory(order: OrderInput, reservation_id: str) -> None:
    pass


@activity.defn(name="reserve_inventory")
async def mock_reserve_inventory_out_of_stock(order: OrderInput) -> str:
    raise ApplicationError(
        f"{order.item} is out of stock", type="OutOfStockError", non_retryable=True
    )


def _sample_order(order_id: str | None = None) -> OrderInput:
    return OrderInput(
        order_id=order_id or f"order-{uuid.uuid4().hex[:8]}",
        customer_name="Test Customer",
        item="Widget",
        quantity=1,
        amount_cents=1000,
    )


@pytest.mark.asyncio
async def test_happy_path_completes_successfully():
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[OrderFulfillmentWorkflow],
            activities=[
                mock_validate_payment_success,
                mock_reserve_inventory_success,
                mock_ship_order_success,
                mock_notify_customer,
                mock_refund_payment,
                mock_release_inventory,
            ],
        ):
            order = _sample_order()
            result = await env.client.execute_workflow(
                OrderFulfillmentWorkflow.run,
                order,
                id=order.order_id,
                task_queue=TASK_QUEUE,
            )
            assert "completed successfully" in result


@pytest.mark.asyncio
async def test_inventory_failure_triggers_refund():
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[OrderFulfillmentWorkflow],
            activities=[
                mock_validate_payment_success,
                mock_reserve_inventory_out_of_stock,
                mock_ship_order_success,
                mock_notify_customer,
                mock_refund_payment,
                mock_release_inventory,
            ],
        ):
            order = _sample_order()
            result = await env.client.execute_workflow(
                OrderFulfillmentWorkflow.run,
                order,
                id=order.order_id,
                task_queue=TASK_QUEUE,
            )
            assert "failed at inventory reservation" in result
            assert "refunded" in result


@pytest.mark.asyncio
async def test_status_query_reflects_progress():
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[OrderFulfillmentWorkflow],
            activities=[
                mock_validate_payment_success,
                mock_reserve_inventory_success,
                mock_ship_order_success,
                mock_notify_customer,
                mock_refund_payment,
                mock_release_inventory,
            ],
        ):
            order = _sample_order()
            handle = await env.client.start_workflow(
                OrderFulfillmentWorkflow.run,
                order,
                id=order.order_id,
                task_queue=TASK_QUEUE,
            )
            result = await handle.result()
            final_status = await handle.query(OrderFulfillmentWorkflow.get_status)
            assert final_status == "COMPLETED"
            assert "completed successfully" in result


@pytest.mark.asyncio
async def test_shipping_failure_compensates_in_reverse_order():
    compensation_calls = []

    @activity.defn(name="ship_order")
    async def fail_shipping(order: OrderInput) -> str:
        raise ApplicationError(
            "Invalid shipping address",
            type="InvalidAddressError",
            non_retryable=True,
        )

    @activity.defn(name="release_inventory")
    async def record_release(
        order: OrderInput, reservation_id: str
    ) -> None:
        compensation_calls.append(
            ("release_inventory", order.order_id, reservation_id)
        )

    @activity.defn(name="refund_payment")
    async def record_refund(
        order: OrderInput, payment_auth: str
    ) -> None:
        compensation_calls.append(
            ("refund_payment", order.order_id, payment_auth)
        )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[OrderFulfillmentWorkflow],
            activities=[
                mock_validate_payment_success,
                mock_reserve_inventory_success,
                fail_shipping,
                mock_notify_customer,
                record_refund,
                record_release,
            ],
        ):
            order = _sample_order()
            handle = await env.client.start_workflow(
                OrderFulfillmentWorkflow.run,
                order,
                id=order.order_id,
                task_queue=TASK_QUEUE,
            )
            await handle.result()
            status = await handle.query(
                OrderFulfillmentWorkflow.get_status
            )

            assert status == "FAILED_SHIPPING"
            assert compensation_calls == [
                (
                    "release_inventory",
                    order.order_id,
                    f"reservation-{order.order_id}",
                ),
                (
                    "refund_payment",
                    order.order_id,
                    f"payment-auth-{order.order_id}",
                ),
            ]



@pytest.mark.asyncio
async def test_cancellation_after_payment_refunds_without_reserving():
    activity_calls = []

    @activity.defn(name="validate_payment")
    async def record_payment(order: OrderInput) -> str:
        activity_calls.append("validate_payment")
        return f"payment-auth-{order.order_id}"

    @activity.defn(name="reserve_inventory")
    async def record_inventory(order: OrderInput) -> str:
        activity_calls.append("reserve_inventory")
        return f"reservation-{order.order_id}"

    @activity.defn(name="refund_payment")
    async def record_refund(
        order: OrderInput, payment_auth: str
    ) -> None:
        activity_calls.append(
            ("refund_payment", order.order_id, payment_auth)
        )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[OrderFulfillmentWorkflow],
            activities=[
                record_payment,
                record_inventory,
                mock_ship_order_success,
                mock_notify_customer,
                record_refund,
                mock_release_inventory,
            ],
        ):
            order = _sample_order()
            order.demo_delay_seconds = 3600

            handle = await env.client.start_workflow(
                OrderFulfillmentWorkflow.run,
                order,
                id=order.order_id,
                task_queue=TASK_QUEUE,
            )

            await handle.signal(OrderFulfillmentWorkflow.cancel_order)
            await handle.result()
            status = await handle.query(
                OrderFulfillmentWorkflow.get_status
            )

            assert status == "CANCELLED"
            assert activity_calls == [
                "validate_payment",
                (
                    "refund_payment",
                    order.order_id,
                    f"payment-auth-{order.order_id}",
                ),
            ]
