# Order Fulfillment Workflow — System Design

## Overview

This project demonstrates a durable order-fulfillment workflow built with
Temporal and FastAPI.

The main design goal is reliability: the system should handle temporary
failures, business failures, worker restarts, and partially completed orders
without losing workflow state or leaving completed work unaccounted for.

The workflow models a simplified order process:

1. Validate payment
2. Reserve inventory
3. Ship the order
4. Notify the customer

If a later step fails after earlier work has succeeded, compensating activities
reverse the completed work where appropriate.

---

## Architecture

```text
Client
  |
  | HTTP + X-API-Key
  v
FastAPI API
  |
  | Temporal client
  v
Temporal Server
  |
  +---- PostgreSQL
  |
  v
Temporal Worker
  |
  v
OrderFulfillmentWorkflow
  |
  +-- validate_payment
  +-- reserve_inventory
  +-- ship_order
  +-- notify_customer

Compensating activities:
  +-- refund_payment
  +-- release_inventory
```

The local development environment runs five services through Docker Compose:

- PostgreSQL
- Temporal Server
- Temporal Web UI
- FastAPI API
- Temporal Worker

---

## Why Temporal

A normal sequence of function calls depends on the application process
remaining alive.

For a multi-step process such as order fulfillment, a crash between steps can
make it difficult to determine:

- which work already completed
- which work should be retried
- which work should be reversed
- where processing should resume

Temporal provides durable workflow execution and preserves workflow history.

This allows the worker process to stop and restart without requiring the entire
order to start again from the beginning.

---

## Workflow Design

### Step 1 — Validate Payment

The workflow first runs `validate_payment`.

Successful completion represents a payment authorization.

Retry policy:

| Setting | Value |
| --- | --- |
| Maximum attempts | 3 |
| Backoff coefficient | 2.0 |
| Non-retryable error | `InvalidCardError` |

Temporary infrastructure-style failures are retried.

An invalid card is treated as a business failure and is not retried.

---

### Step 2 — Reserve Inventory

After payment succeeds, the workflow runs `reserve_inventory`.

Retry policy:

| Setting | Value |
| --- | --- |
| Maximum attempts | 5 |
| Backoff coefficient | 2.0 |
| Non-retryable error | `OutOfStockError` |

If inventory reservation fails after payment has already succeeded, the
workflow performs compensation:

```text
Payment validated
      |
      v
Inventory fails
      |
      v
Refund payment
      |
      v
FAILED_INVENTORY
```

---

### Step 3 — Ship Order

After inventory is reserved, the workflow runs `ship_order`.

Retry policy:

| Setting | Value |
| --- | --- |
| Maximum attempts | 5 |
| Backoff coefficient | 2.0 |
| Non-retryable error | `InvalidAddressError` |

If shipping ultimately fails, both completed business operations are reversed:

```text
Payment validated
      |
      v
Inventory reserved
      |
      v
Shipping fails
      |
      +--> Release inventory
      |
      +--> Refund payment
      |
      v
FAILED_SHIPPING
```

---

### Step 4 — Notify Customer

After shipping succeeds, the workflow runs `notify_customer`.

Retry policy:

| Setting | Value |
| --- | --- |
| Maximum attempts | 3 |
| Backoff coefficient | 1.5 |
| Non-retryable errors | None |

Customer notification is treated as best-effort.

A notification failure should not reverse payment, inventory, or shipping
because the order has already been shipped.

---

## Retry Strategy

The project separates failures into two categories.

### Retryable failures

These represent temporary problems such as:

- network interruptions
- temporary service outages
- short-lived downstream errors

The simulated activities can generate transient failures when demo failure
injection is explicitly enabled. Failure injection is disabled by default so
normal runs remain deterministic.

Temporal retries these operations according to the configured retry policy.

### Non-retryable business failures

These represent conditions where trying the same operation again is unlikely to
change the result.

Examples:

- `InvalidCardError`
- `OutOfStockError`
- `InvalidAddressError`

These errors are marked non-retryable so the workflow can immediately move to
the appropriate failure or compensation path.

---

## Saga Compensation

The workflow uses the Saga pattern to handle work that spans multiple logical
services.

Instead of relying on one large database transaction, previously completed
operations have compensating actions.

| Completed operation | Compensating action |
| --- | --- |
| Payment validation | `refund_payment` |
| Inventory reservation | `release_inventory` |

Compensation is executed in response to later failures or cancellation.

This prevents partially completed workflows from leaving earlier work
unaddressed.

---

## Cancellation Design

The workflow exposes a Temporal signal named:

```text
cancel_order
```

The API can send this signal to an active workflow.

Cancellation is checked between major workflow steps.

If cancellation occurs after payment validation:

```text
Refund payment
      |
      v
CANCELLED
```

If cancellation occurs after inventory reservation:

```text
Release inventory
      |
      v
Refund payment
      |
      v
CANCELLED
```

The signal does not interrupt an activity already in progress. The workflow
handles the cancellation request at the next defined checkpoint.

---

## Workflow Status Queries

The workflow exposes a Temporal query named:

```text
get_status
```

This allows the API to retrieve the current order state while the workflow is
running or after it has completed.

Example states include:

- `PLACED`
- `PAYMENT_VALIDATED`
- `INVENTORY_RESERVED`
- `SHIPPED`
- `COMPLETED`
- `CANCELLED`
- `FAILED_INVENTORY`
- `FAILED_SHIPPING`

Queries provide visibility without changing workflow state.

---

## Worker Crash Recovery

A core design goal was proving that workflow execution survives worker failure.

For the recovery demonstration, the workflow supports a controlled durable
pause after payment validation and before inventory reservation.

The test process was:

```text
Validate payment
      |
      v
Durable pause
      |
      v
Stop worker
      |
      v
Restart worker
      |
      v
Workflow continues
```

The workflow resumed from its durable history rather than restarting payment
validation from the beginning.

This demonstrates one of the primary reasons Temporal was selected for the
project.

---

## API Boundary

FastAPI provides the HTTP interface.

Available operations include:

| Method | Endpoint | Purpose |
| --- | --- | --- |
| POST | `/orders` | Start an order workflow |
| GET | `/orders/{order_id}` | Query order status |
| POST | `/orders/{order_id}/cancel` | Request cancellation |
| GET | `/health` | Health check |

The API starts the Temporal workflow and returns a `PLACED` response without
waiting for the complete fulfillment process.

This keeps the lifetime of the HTTP request separate from the lifetime of the
workflow.

---

## Authentication

API endpoints are protected using an `X-API-Key` header.

The API key is supplied through an environment variable rather than stored in
source control.

For a production system, stronger identity-based authentication and managed
secret storage would be appropriate.

---

## Observability

Activities emit structured event payloads containing fields such as:

- `event`
- `order_id`
- `activity`
- `retryable`
- `error_type`
- `compensation`

Examples include:

```text
payment_validated
inventory_reserved
order_shipped
customer_notified
transient_failure
business_failure
payment_refunded
inventory_released
```

Temporal also supplies execution context such as:

- workflow ID
- workflow run ID
- activity attempt
- task queue
- workflow type

Sensitive payment authorization values are intentionally excluded from logs.

---

## Testing Strategy

The automated test suite currently contains 11 passing tests.

Coverage includes:

- successful workflow execution
- inventory failure
- payment compensation
- workflow status queries
- API authentication
- missing API keys
- invalid API keys
- authenticated API requests
- shipping-failure compensation in reverse order
- cancellation after payment refunds without reserving inventory
- cancellation after inventory reservation releases inventory,
  refunds payment, and prevents shipping

Tests are run both locally and through GitHub Actions.

---

## Continuous Integration

GitHub Actions runs on:

- pushes to `main`
- pull requests targeting `main`

CI performs the following steps:

```text
Checkout repository
      |
      v
Install Python 3.13
      |
      v
Install dependencies
      |
      v
Start PostgreSQL + Temporal
      |
      v
Wait for Temporal client connection
      |
      v
Run pytest
```

Temporal readiness is verified using an actual Temporal client connection
rather than only checking whether port 7233 is open.

This avoids treating a partially started service as ready.

---

## Performance Measurement

The project includes a reproducible local benchmark for authenticated:

```text
POST /orders
```

The benchmark measures:

```text
API authentication
      |
      v
FastAPI request handling
      |
      v
Temporal workflow start
      |
      v
PLACED response
```

Example local run: 25 sequential authenticated requests, executed
inside the API container against the Docker Compose stack.

| Metric | Result |
| --- | ---: |
| Requests | 25 |
| Successful | 25 (100%) |
| Average | 38.74 ms |
| p50 | 32.93 ms |
| p95 | 75.51 ms |
| Minimum | 12.01 ms |
| Maximum | 107.65 ms |

These results measure local order-submission latency only.

They do not represent complete workflow execution time or production-scale
throughput.

Results vary with hardware, system load, and execution environment.

---

## Current Design Trade-offs

This project intentionally stays small enough to clearly demonstrate the
distributed-systems concepts.

Current limitations include:

- payment, inventory, shipping, and notification services are simulated
- API-key authentication is intentionally simple
- the system runs as a local Docker Compose environment
- the benchmark is local rather than production load testing
- downstream operations would require stronger idempotency guarantees in a
  production system
- Temporal container images are pinned to specific versions for reproducible
  local and CI environments

These are deliberate project boundaries rather than production claims.

---

## Production Extensions

If this system were developed further for production, important additions would
include:

- real payment, inventory, and shipping integrations
- idempotency keys and idempotent activity implementations
- managed authentication and authorization
- managed secrets
- metrics and distributed tracing
- alerting and dashboards
- stronger service health checks
- automated dependency and container-version update checks
- higher-volume load testing
- deployment orchestration
- production database and backup strategy

---

## Design Summary

The central design principle is:

> Reliability includes deciding what should happen when part of a workflow
> fails.

The project demonstrates that principle through durable workflow execution,
retry policies, business-error classification, Saga compensation, cancellation,
worker crash recovery, observability, automated testing, CI, and measured local
performance.
