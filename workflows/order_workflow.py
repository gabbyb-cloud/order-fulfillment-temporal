import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from activities.order_activities import (
        notify_customer,
        release_inventory,
        reserve_inventory,
        refund_payment,
        ship_order,
        validate_payment,
    )
    from workflows.models import OrderInput, OrderStatus


@workflow.defn
class OrderFulfillmentWorkflow:
    def __init__(self) -> None:
        self._status: OrderStatus = OrderStatus.PLACED
        self._cancel_requested = False

    @workflow.signal
    def cancel_order(self) -> None:
        """Request cancellation at the next workflow checkpoint."""
        self._cancel_requested = True

    @workflow.query
    def get_status(self) -> str:
        """Return the current order state."""
        return self._status.value

    @workflow.run
    async def run(self, order: OrderInput) -> str:
        payment_auth = await workflow.execute_activity(
            validate_payment,
            order,
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=RetryPolicy(
                maximum_attempts=3,
                backoff_coefficient=2.0,
                non_retryable_error_types=["InvalidCardError"],
            ),
        )
        self._status = OrderStatus.PAYMENT_VALIDATED

        if order.demo_delay_seconds > 0:
            workflow.logger.info(
                f"Demo pause: sleeping {order.demo_delay_seconds}s after payment "
                "validation, before reserving inventory."
            )
            await asyncio.sleep(order.demo_delay_seconds)

        if self._cancel_requested:
            await workflow.execute_activity(
                refund_payment,
                args=[order, payment_auth],
                start_to_close_timeout=timedelta(seconds=10),
            )
            self._status = OrderStatus.CANCELLED
            return f"Order {order.order_id} cancelled after payment; refunded."

        try:
            reservation_id = await workflow.execute_activity(
                reserve_inventory,
                order,
                start_to_close_timeout=timedelta(seconds=10),
                retry_policy=RetryPolicy(
                    maximum_attempts=5,
                    backoff_coefficient=2.0,
                    non_retryable_error_types=["OutOfStockError"],
                ),
            )
        except Exception:
            await workflow.execute_activity(
                refund_payment,
                args=[order, payment_auth],
                start_to_close_timeout=timedelta(seconds=10),
            )
            self._status = OrderStatus.FAILED_INVENTORY
            return (
                f"Order {order.order_id} failed at inventory reservation; "
                "payment refunded."
            )

        self._status = OrderStatus.INVENTORY_RESERVED

        if self._cancel_requested:
            await workflow.execute_activity(
                release_inventory,
                args=[order, reservation_id],
                start_to_close_timeout=timedelta(seconds=10),
            )
            await workflow.execute_activity(
                refund_payment,
                args=[order, payment_auth],
                start_to_close_timeout=timedelta(seconds=10),
            )
            self._status = OrderStatus.CANCELLED
            return (
                f"Order {order.order_id} cancelled after inventory reserved; "
                "rolled back."
            )

        try:
            await workflow.execute_activity(
                ship_order,
                order,
                start_to_close_timeout=timedelta(seconds=10),
                retry_policy=RetryPolicy(
                    maximum_attempts=5,
                    backoff_coefficient=2.0,
                    non_retryable_error_types=["InvalidAddressError"],
                ),
            )
        except Exception:
            await workflow.execute_activity(
                release_inventory,
                args=[order, reservation_id],
                start_to_close_timeout=timedelta(seconds=10),
            )
            await workflow.execute_activity(
                refund_payment,
                args=[order, payment_auth],
                start_to_close_timeout=timedelta(seconds=10),
            )
            self._status = OrderStatus.FAILED_SHIPPING
            return (
                f"Order {order.order_id} failed at shipping; inventory released "
                "and payment refunded."
            )

        self._status = OrderStatus.SHIPPED

        try:
            await workflow.execute_activity(
                notify_customer,
                args=[order, f"Your order {order.order_id} has shipped!"],
                start_to_close_timeout=timedelta(seconds=10),
                retry_policy=RetryPolicy(
                    maximum_attempts=3,
                    backoff_coefficient=1.5,
                ),
            )
        except Exception as exc:
            workflow.logger.warning(
                f"Notification failed for order {order.order_id} after retries: "
                f"{type(exc).__name__}"
            )

        self._status = OrderStatus.COMPLETED
        return f"Order {order.order_id} completed successfully."
