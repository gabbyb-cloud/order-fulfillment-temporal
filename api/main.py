import os
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.security import APIKeyHeader
from temporalio.client import Client, WorkflowHandle
from temporalio.service import RPCError, RPCStatusCode

from api.schemas import CreateOrderRequest, CreateOrderResponse, OrderStatusResponse
from workflows.models import OrderInput
from workflows.order_workflow import OrderFulfillmentWorkflow

load_dotenv()

TASK_QUEUE = "order-fulfillment-task-queue"
TEMPORAL_ADDRESS = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
API_KEY = os.environ["ORDER_API_KEY"]
api_key_header = APIKeyHeader(name="X-API-Key")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.temporal_client = await Client.connect(TEMPORAL_ADDRESS)
    yield


def verify_api_key(key: str = Security(api_key_header)) -> None:
    if key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")


app = FastAPI(
    title="Order Fulfillment Service",
    description="Durable order fulfillment backed by Temporal workflows.",
    lifespan=lifespan,
    dependencies=[Depends(verify_api_key)],
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


def _get_handle(order_id: str) -> WorkflowHandle:
    client: Client = app.state.temporal_client
    return client.get_workflow_handle(order_id)


def _raise_workflow_http_error(exc: RPCError, order_id: str) -> None:
    if exc.status == RPCStatusCode.NOT_FOUND:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found") from exc

    raise HTTPException(
        status_code=503,
        detail="Workflow service unavailable",
    ) from exc


@app.post("/orders", response_model=CreateOrderResponse, status_code=201)
async def create_order(req: CreateOrderRequest) -> CreateOrderResponse:
    client: Client = app.state.temporal_client
    order_id = f"order-{uuid.uuid4().hex[:8]}"
    order = OrderInput(
        order_id=order_id,
        customer_name=req.customer_name,
        item=req.item,
        quantity=req.quantity,
        amount_cents=req.amount_cents,
    )

    try:
        await client.start_workflow(
            OrderFulfillmentWorkflow.run,
            order,
            id=order_id,
            task_queue=TASK_QUEUE,
        )
    except RPCError as exc:
        raise HTTPException(
            status_code=503,
            detail="Unable to start order - workflow service unavailable",
        ) from exc

    return CreateOrderResponse(order_id=order_id, status="PLACED")


@app.get("/orders/{order_id}", response_model=OrderStatusResponse)
async def get_order_status(order_id: str) -> OrderStatusResponse:
    handle = _get_handle(order_id)
    try:
        status = await handle.query(OrderFulfillmentWorkflow.get_status)
    except RPCError as exc:
        _raise_workflow_http_error(exc, order_id)

    return OrderStatusResponse(order_id=order_id, status=status)


@app.post("/orders/{order_id}/cancel", status_code=202)
async def cancel_order(order_id: str) -> dict:
    handle = _get_handle(order_id)
    try:
        await handle.signal(OrderFulfillmentWorkflow.cancel_order)
    except RPCError as exc:
        _raise_workflow_http_error(exc, order_id)

    return {"order_id": order_id, "message": "Cancellation requested"}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
