# Order Fulfillment Service — Temporal Workflow Orchestration

A durable order-fulfillment backend built with **Temporal, FastAPI, and Docker**, demonstrating workflow orchestration, failure recovery, compensating transactions, structured observability, automated testing, and CI.

## What this demonstrates

This project focuses on backend and infrastructure engineering concepts used in reliable distributed systems:

* **Durable workflow execution** — orders move through payment validation → inventory reservation → shipping → customer notification using Temporal
* **Automatic retries** — transient downstream failures are retried by Temporal rather than immediately failing the workflow
* **Non-retryable business failures** — invalid cards, out-of-stock inventory, and invalid shipping addresses are handled separately from infrastructure failures
* **Saga / compensating transactions** — completed steps can be reversed through payment refunds and inventory release when later steps fail
* **Crash recovery** — worker processes can stop and restart while Temporal preserves workflow state
* **Authenticated API boundary** — FastAPI exposes order operations behind an `X-API-Key` requirement
* **Structured logging** — workflow activities emit JSON-style events correlated by order and activity
* **Containerized development stack** — PostgreSQL, Temporal, Temporal UI, FastAPI, and the Temporal worker run together with Docker Compose
* **Automated CI** — GitHub Actions runs the test suite on a clean Ubuntu environment for pushes and pull requests to `main`
* **Performance measurement** — a reproducible local benchmark measures authenticated order-submission latency

## Architecture

```text
Client
  │
  │ X-API-Key
  ▼
FastAPI API
  │
  │ Temporal client
  ▼
Temporal Server
  │
  ├── PostgreSQL
  │
  ▼
Temporal Worker
  │
  ▼
OrderFulfillmentWorkflow
  │
  ├── validate_payment
  ├── reserve_inventory
  ├── ship_order
  └── notify_customer

Compensation path:
  ├── refund_payment
  └── release_inventory
```

The complete local stack runs through Docker Compose:

```text
Docker Compose
├── PostgreSQL
├── Temporal Server
├── Temporal Web UI
├── FastAPI API
└── Temporal Worker
```

## Reliability and failure handling

The workflow distinguishes between failures that should be retried and failures that should not.

### Retryable transient failures

Activities simulate temporary downstream failures such as network interruptions or service timeouts.

Temporal automatically retries these activities.

Example structured event:

```json
{
  "activity": "ship_order",
  "event": "transient_failure",
  "order_id": "order-example",
  "retryable": true
}
```

A verified workflow demonstrated:

```text
validate_payment
  attempt 1 → transient failure
  attempt 2 → success

reserve_inventory
  attempt 1 → success

ship_order
  attempt 1 → transient failure
  attempt 2 → success

notify_customer
  attempt 1 → success

workflow → COMPLETED
```

### Non-retryable business failures

Examples include:

* `InvalidCardError`
* `OutOfStockError`
* `InvalidAddressError`

These are logged with:

```json
{
  "event": "business_failure",
  "retryable": false
}
```

because retrying cannot correct the underlying business condition.

### Saga compensation

If a later step fails after earlier work has already succeeded, compensating activities undo completed operations.

Examples:

```text
Payment succeeds
      ↓
Inventory fails
      ↓
refund_payment
      ↓
Workflow ends safely
```

and:

```text
Inventory reserved
      ↓
Later step fails
      ↓
release_inventory
```

Compensation events are emitted with `compensation=true`.

## Structured logging

Activity logs include fields such as:

* `event`
* `order_id`
* `activity`
* `retryable`
* `error_type`
* `compensation`

Temporal also attaches execution context including activity attempt, workflow ID, workflow run ID, task queue, and workflow type.

Sensitive payment authorization values are intentionally excluded from logs.

Example:

```json
{
  "activity": "validate_payment",
  "event": "payment_validated",
  "order_id": "order-example"
}
```

## Tech stack

* **Python 3.13**
* **FastAPI**
* **Pydantic**
* **Temporal Python SDK**
* **PostgreSQL**
* **Docker / Docker Compose**
* **pytest**
* **pytest-asyncio**
* **httpx**
* **python-dotenv**
* **GitHub Actions**

## Getting started

### Prerequisites

* Python 3.13
* Docker Desktop
* Git

### Clone and enter the project

```bash
git clone <repository-url>
cd order-fulfillment-temporal
```

### Create a virtual environment

Windows PowerShell:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

### Configure the API key

Create a `.env` file in the project root:

```text
ORDER_API_KEY=your-local-api-key
```

The `.env` file is excluded from Docker build context and should not be committed.

## Running the application

Build and start the complete stack:

```powershell
docker compose up --build -d
```

Verify the services:

```powershell
docker compose ps
```

You should see:

```text
api
postgresql
temporal
temporal-ui
worker
```

The API is available at:

```text
http://localhost:8000
```

Temporal Web UI is available at:

```text
http://localhost:8080
```

To stop the stack:

```powershell
docker compose down
```

## API endpoints

All endpoints require an `X-API-Key` header.

| Method | Path                        | Description                                              |
| ------ | --------------------------- | -------------------------------------------------------- |
| `POST` | `/orders`                   | Start a new order fulfillment workflow                   |
| `GET`  | `/orders/{order_id}`        | Query the current order status                           |
| `POST` | `/orders/{order_id}/cancel` | Request cancellation and trigger applicable compensation |
| `GET`  | `/health`                   | Health check                                             |

Example order submission:

```json
{
  "customer_name": "Demo Customer",
  "item": "Mechanical Keyboard",
  "quantity": 1,
  "amount_cents": 12999
}
```

Example response:

```json
{
  "order_id": "order-example",
  "status": "PLACED"
}
```

The workflow continues durably after the API returns.

## Running the tests

Start the Temporal infrastructure if it is not already running:

```powershell
docker compose up -d postgresql temporal
```

Run the test suite:

```powershell
python -m pytest -q
```

Current result:

```text
8 passed
```

The suite covers:

* workflow happy path
* inventory failure and payment compensation
* workflow status queries
* API authentication
* missing API keys
* invalid API keys
* valid authenticated requests
* protected endpoints

## Continuous integration

GitHub Actions automatically runs CI for:

* pull requests targeting `main`
* pushes to `main`

The workflow:

1. checks out the repository
2. creates a clean Ubuntu environment
3. installs Python 3.13
4. installs project dependencies
5. starts PostgreSQL and Temporal
6. waits until the Temporal Python client can establish a connection
7. runs the full pytest suite
8. prints infrastructure logs automatically if CI fails

This verifies the project outside the local Windows development environment.

## Performance benchmark

A local benchmark of **25 authenticated `POST /orders` requests** against the Dockerized stack measured order-submission latency.

The measurement includes:

```text
API authentication
      ↓
FastAPI request handling
      ↓
Temporal workflow start
      ↓
PLACED response
```

It does **not** measure the time required for the complete fulfillment workflow to finish.

| Metric     |    Result |
| ---------- | --------: |
| Requests   |        25 |
| Successful | 25 (100%) |
| Average    |  30.28 ms |
| p50        |  24.44 ms |
| p95        |  49.15 ms |
| Minimum    |  13.53 ms |
| Maximum    | 117.66 ms |

Run the benchmark locally with:

```powershell
python .\benchmarks\order_submission.py
```

These results represent a local development environment and are not intended as production-scale performance claims.

## Project status

Core implementation is complete:

* Durable Temporal workflow ✅
* Retry handling ✅
* Saga compensation ✅
* Worker crash recovery ✅
* Authenticated FastAPI service ✅
* Automated tests ✅
* Dockerized API and worker ✅
* Five-service Docker Compose stack ✅
* Structured activity logging ✅
* GitHub Actions CI ✅
* Local performance benchmark ✅
