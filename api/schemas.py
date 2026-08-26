from pydantic import BaseModel, Field


class CreateOrderRequest(BaseModel):
    customer_name: str = Field(..., examples=["Demo Customer"])
    item: str = Field(..., examples=["Mechanical Keyboard"])
    quantity: int = Field(..., gt=0, examples=[1])
    amount_cents: int = Field(..., gt=0, examples=[8999])


class CreateOrderResponse(BaseModel):
    order_id: str
    status: str


class OrderStatusResponse(BaseModel):
    order_id: str
    status: str
