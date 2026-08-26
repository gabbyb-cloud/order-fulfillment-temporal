import json
import os
import random

from temporalio import activity
from temporalio.exceptions import ApplicationError

from workflows.models import OrderInput


def _failure_rate(name: str) -> float:
    """Read a demo failure-injection rate from the environment."""
    value = float(os.getenv(name, "0"))
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
    return value


# Failure injection is disabled by default so a fresh clone behaves
# deterministically. Set these variables explicitly when demonstrating retries
# and business-failure compensation paths.
TRANSIENT_FAILURE_RATE = _failure_rate("TRANSIENT_FAILURE_RATE")
BUSINESS_FAILURE_RATE = _failure_rate("BUSINESS_FAILURE_RATE")


def _log_event(
    event: str,
    order_id: str,
    activity_name: str,
    **details: object,
) -> None:
    payload = {
        "event": event,
        "order_id": order_id,
        "activity": activity_name,
        **details,
    }
    activity.logger.info(json.dumps(payload, sort_keys=True))


def _maybe_raise_transient(activity_name: str, order_id: str) -> None:
    if random.random() < TRANSIENT_FAILURE_RATE:
        _log_event(
            "transient_failure",
            order_id,
            activity_name,
            retryable=True,
        )
        raise RuntimeError(
            f"Simulated transient failure calling {activity_name}; "
            "Temporal should retry this."
        )


@activity.defn
async def validate_payment(order: OrderInput) -> str:
    """Simulate payment validation with transient and business failures."""
    _maybe_raise_transient("validate_payment", order.order_id)

    if random.random() < BUSINESS_FAILURE_RATE:
        _log_event(
            "business_failure",
            order.order_id,
            "validate_payment",
            retryable=False,
            error_type="InvalidCardError",
        )
        raise ApplicationError(
            f"Card declined for order {order.order_id}",
            type="InvalidCardError",
            non_retryable=True,
        )

    _log_event("payment_validated", order.order_id, "validate_payment")
    return f"payment-auth-{order.order_id}"


@activity.defn
async def reserve_inventory(order: OrderInput) -> str:
    """Simulate inventory reservation with transient and business failures."""
    _maybe_raise_transient("reserve_inventory", order.order_id)

    if random.random() < BUSINESS_FAILURE_RATE:
        _log_event(
            "business_failure",
            order.order_id,
            "reserve_inventory",
            retryable=False,
            error_type="OutOfStockError",
        )
        raise ApplicationError(
            f"{order.item} is out of stock for order {order.order_id}",
            type="OutOfStockError",
            non_retryable=True,
        )

    _log_event("inventory_reserved", order.order_id, "reserve_inventory")
    return f"reservation-{order.order_id}"


@activity.defn
async def ship_order(order: OrderInput) -> str:
    """Simulate shipping with transient and non-retryable address failures."""
    _maybe_raise_transient("ship_order", order.order_id)

    if random.random() < BUSINESS_FAILURE_RATE:
        _log_event(
            "business_failure",
            order.order_id,
            "ship_order",
            retryable=False,
            error_type="InvalidAddressError",
        )
        raise ApplicationError(
            f"Invalid shipping address for order {order.order_id}",
            type="InvalidAddressError",
            non_retryable=True,
        )

    _log_event("order_shipped", order.order_id, "ship_order")
    return f"tracking-{order.order_id}"


@activity.defn
async def notify_customer(order: OrderInput, message: str) -> None:
    """Simulate a best-effort notification call with retryable failures."""
    _maybe_raise_transient("notify_customer", order.order_id)
    _log_event("customer_notified", order.order_id, "notify_customer")


@activity.defn
async def refund_payment(order: OrderInput, payment_auth: str) -> None:
    """Compensating action for a successful payment authorization."""
    _log_event(
        "payment_refunded",
        order.order_id,
        "refund_payment",
        compensation=True,
    )


@activity.defn
async def release_inventory(order: OrderInput, reservation_id: str) -> None:
    """Compensating action for a successful inventory reservation."""
    _log_event(
        "inventory_released",
        order.order_id,
        "release_inventory",
        compensation=True,
    )
