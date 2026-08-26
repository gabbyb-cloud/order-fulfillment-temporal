from dataclasses import dataclass
from enum import Enum


class OrderStatus(str, Enum):
    PLACED = "PLACED"
    PAYMENT_VALIDATED = "PAYMENT_VALIDATED"
    INVENTORY_RESERVED = "INVENTORY_RESERVED"
    SHIPPED = "SHIPPED"
    COMPLETED = "COMPLETED"
    FAILED_PAYMENT = "FAILED_PAYMENT"
    FAILED_INVENTORY = "FAILED_INVENTORY"
    FAILED_SHIPPING = "FAILED_SHIPPING"
    CANCELLED = "CANCELLED"


@dataclass
class OrderInput:
    order_id: str
    customer_name: str
    item: str
    quantity: int
    amount_cents: int
    # Demo-only durable pause used to create a window for the worker
    # crash/restart exercise. Normal application requests leave this at 0.
    demo_delay_seconds: int = 0


class InvalidCardError(Exception):
    """Represents a non-retryable invalid-card business failure."""


class OutOfStockError(Exception):
    """Represents a non-retryable out-of-stock business failure."""


class InvalidAddressError(Exception):
    """Represents a non-retryable invalid-address business failure."""
