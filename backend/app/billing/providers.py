"""Payment providers behind one small interface, so a real one (Stripe, Paymob) can be added
later without changing the rest of the billing code:

    create_checkout(checkout) -> URL    the payment page to send the browser to
    verify_webhook(body, headers) -> Event   a provider's webhook call, checked (InvalidWebhook if not)
    cancel(subscription_ref)            stop renewing a subscription at the provider

The billing code (app/billing/service.py) only sees Checkout and Event. Event kinds:
checkout.paid, checkout.failed (a payment page's outcome), invoice.paid,
invoice.payment_failed (a monthly renewal).

"simulated" is the only provider for now: no real payment and no keys. Its payment page is
our own (/checkout/<id> in the frontend, with a "Test mode" banner), and its "Pay" and "Fail
payment" buttons, and the console's "Simulate next month", make signed events that go
through the same webhook handling as a real provider's would.
"""
import hashlib
import hmac
import json
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Mapping, Protocol


class InvalidWebhook(Exception):
    """A webhook call that is not from the provider (bad signature) or cannot be read."""


@dataclass(frozen=True)
class Checkout:
    id: uuid.UUID
    plan_key: str
    plan_name: str
    amount_egp: int
    purpose: str          # signup | change_plan | pay_now
    university: str


@dataclass(frozen=True)
class Event:
    id: str               # unique per event: a repeated call is applied once
    kind: str
    data: dict = field(default_factory=dict)


class PaymentProvider(Protocol):
    name: str

    def create_checkout(self, checkout: Checkout) -> str: ...

    def verify_webhook(self, body: bytes, headers: Mapping[str, str]) -> Event: ...

    def cancel(self, subscription_ref: str) -> None: ...


class SimulatedProvider:
    """Test mode: our own checkout page; events signed with a key made at start-up."""
    name = "simulated"
    SIGNATURE_HEADER = "x-simulated-signature"

    def __init__(self):
        self._key = secrets.token_bytes(32)

    def create_checkout(self, checkout: Checkout) -> str:
        return f"/checkout/{checkout.id}"  # the frontend's test-mode payment page (same site)

    def subscription_ref(self, tenant_id: uuid.UUID) -> str:
        return f"sim_sub_{tenant_id.hex}"

    def signed_event(self, kind: str, **data) -> tuple[bytes, dict]:
        """An event as the provider would send it to our webhook: body and headers."""
        body = json.dumps({"id": f"evt_sim_{secrets.token_hex(12)}", "type": kind, "created": int(time.time()),
                           "data": data}).encode()
        return body, {self.SIGNATURE_HEADER: hmac.new(self._key, body, hashlib.sha256).hexdigest()}

    def verify_webhook(self, body: bytes, headers: Mapping[str, str]) -> Event:
        expected = hmac.new(self._key, body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, headers.get(self.SIGNATURE_HEADER, "")):
            raise InvalidWebhook("Bad signature.")
        try:
            event = json.loads(body)
            return Event(str(event["id"]), str(event["type"]), dict(event.get("data") or {}))
        except (ValueError, KeyError, TypeError) as error:
            raise InvalidWebhook("Unreadable event.") from error

    def cancel(self, subscription_ref: str) -> None:
        pass  # nothing is renewed at a simulated provider


PROVIDERS: dict[str, PaymentProvider] = {"simulated": SimulatedProvider()}


def get(name: str) -> PaymentProvider:
    return PROVIDERS[name]
