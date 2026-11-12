"""Payments (app/billing/): the provider's webhook, the payment page, and the university
admin's Billing page.

POST /billing/webhook/{provider}           the provider's events (signature checked by the provider)
GET  /billing/checkouts/{id}               what the payment page shows (plan, price, university)
POST /billing/simulated/checkouts/{id}     {outcome: "paid" | "failed"}: the test-mode page's buttons
GET  /admin/billing                        the university's subscription, payments and the plans  (tenant_admin)
POST /admin/billing/checkout               {plan} -> {url}: choose a paid plan, or pay after a failed renewal
POST /admin/billing/cancel                 cancel (a paid month runs to its end)
POST /admin/billing/resume                 undo the cancellation

The payment and webhook routes work on any host (they are about a checkout, not about the
host's university), like the sign-up.
"""
import logging
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app import tenants
from app.auth import tenant_admin
from app.billing import providers, service
from app.db import get_admin_connection

router = APIRouter()
log = logging.getLogger("uvicorn.error")


class SimulatedOutcome(BaseModel):
    outcome: Literal["paid", "failed"]


class PlanChoice(BaseModel):
    plan: str = Field(min_length=1, max_length=30)


@router.post("/billing/webhook/{provider_name}")
async def webhook(provider_name: str, request: Request):
    if provider_name not in providers.PROVIDERS:
        raise HTTPException(404, "Unknown payment provider.")
    try:
        event = await run_in_threadpool(service.receive_webhook, provider_name, await request.body(), request.headers)
    except providers.InvalidWebhook as error:
        log.warning("Billing: refused a %s webhook call: %s", provider_name, error)
        raise HTTPException(400, "Invalid webhook call.")
    return {"received": event.id}


def checkout_id(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise HTTPException(404, "This payment page does not exist.")


@router.get("/billing/checkouts/{checkout}")
def get_checkout(checkout: str):
    return service.checkout_out(checkout_id(checkout))


@router.post("/billing/simulated/checkouts/{checkout}")
def simulated_payment(checkout: str, body: SimulatedOutcome):
    return service.simulate_checkout(checkout_id(checkout), body.outcome == "paid")


@router.get("/admin/billing", dependencies=[Depends(tenant_admin)])
def billing():
    with get_admin_connection() as conn:
        subscription = service.subscription(conn, tenants.current_id())
        plans = [p for p in service.plans(conn, public_only=True) if not p["trial_days"]]
    return {"subscription": subscription, "plans": plans}


@router.post("/admin/billing/checkout", dependencies=[Depends(tenant_admin)])
def billing_checkout(body: PlanChoice):
    return {"url": service.checkout_for_university(tenants.current_id(), body.plan)}


@router.post("/admin/billing/cancel", dependencies=[Depends(tenant_admin)])
def billing_cancel():
    service.cancel(tenants.current_id())
    return {"ok": True}


@router.post("/admin/billing/resume", dependencies=[Depends(tenant_admin)])
def billing_resume():
    service.resume(tenants.current_id())
    return {"ok": True}
