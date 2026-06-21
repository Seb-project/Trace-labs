from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .models import (
    AccountOverview,
    AccountProfile,
    BillingIntegrationStatus,
    PricingPreview,
    UsageEvent,
    UsageEventRequest,
)
from .storage import JsonStore


EVENT_METER_ENV = {
    "circuit_block.generated": "SOLVIMON_CIRCUIT_BLOCK_METER_REFERENCE",
    "kicad_export.created": "SOLVIMON_KICAD_EXPORT_METER_REFERENCE",
    "datasheet_page.processed": "SOLVIMON_DATASHEET_PAGE_METER_REFERENCE",
    "ai_token.used": "SOLVIMON_AI_TOKEN_METER_REFERENCE",
    "footprint_lookup.performed": "SOLVIMON_FOOTPRINT_LOOKUP_METER_REFERENCE",
}


class AccountBillingService:
    def __init__(self, data_dir: Path):
        self.events_store = JsonStore(data_dir / "usage_events.json")
        self.account_store = JsonStore(data_dir / "account.json")
        self._events_lock = threading.Lock()
        self._events_cache: list[UsageEvent] | None = None
        self._events_cache_signature: tuple[int, int] | None = None

    def account(self) -> AccountProfile:
        stored = self.account_store.read_dict()
        if stored:
            account = AccountProfile(**stored)
        else:
            account = AccountProfile(
                account_id=os.getenv("TRACELABS_ACCOUNT_ID", "local-dev"),
                display_name=os.getenv("TRACELABS_ACCOUNT_NAME", "Local developer"),
                email=os.getenv("TRACELABS_ACCOUNT_EMAIL", ""),
            )

        customer_reference = os.getenv("SOLVIMON_CUSTOMER_REFERENCE", account.solvimon_customer_reference)
        subscription_reference = os.getenv(
            "SOLVIMON_SUBSCRIPTION_REFERENCE",
            account.solvimon_subscription_reference,
        )
        next_account = account.model_copy(
            update={
                "solvimon_customer_reference": customer_reference,
                "solvimon_subscription_reference": subscription_reference,
                "status": "active" if customer_reference else account.status,
            }
        )
        if next_account != account or not stored:
            self.account_store.write_dict(next_account.model_dump())
        return next_account

    def record(self, request: UsageEventRequest) -> UsageEvent:
        account = self.account()
        event = UsageEvent(
            reference=request.reference or f"evt_{uuid4().hex}",
            event_type=request.event_type,
            quantity=request.quantity,
            metadata=request.metadata,
            timestamp=request.timestamp or datetime.now(timezone.utc).isoformat(),
            account_id=account.account_id,
            solvimon_sync_status="pending" if self._can_sync_event(request.event_type, account) else "not_configured",
        )
        event = self._sync_to_solvimon(event, account)
        with self._events_lock:
            cached_events = self._cached_events_if_fresh()
            if cached_events is None:
                events_data = self.events_store.read_list()
                cached_events = [UsageEvent(**item) for item in events_data]
            else:
                events_data = [item.model_dump() for item in cached_events]
            events_data.append(event.model_dump())
            self.events_store.write_list(events_data)
            self._events_cache = [*cached_events, event]
            self._events_cache_signature = self._events_signature()
        return event

    def preview(self) -> PricingPreview:
        events = self.events()
        used_blocks = int(sum(e.quantity for e in events if e.event_type == "circuit_block.generated"))
        remaining = max(0, 50 - used_blocks)
        overage = max(0, used_blocks - 50) * 0.20
        return PricingPreview(
            used_blocks=used_blocks,
            remaining_blocks=remaining,
            estimated_overage=round(overage, 2),
            estimated_monthly_bill=round(12 + overage, 2),
            recent_events=events[-8:],
            message=self._pricing_message(used_blocks, remaining, overage),
        )

    def overview(self) -> AccountOverview:
        return AccountOverview(
            account=self.account(),
            pricing_preview=self.preview(),
            billing=self.integration_status(),
        )

    def integration_status(self) -> BillingIntegrationStatus:
        account = self.account()
        api_key = os.getenv("SOLVIMON_API_KEY", "")
        mode = self._mode()
        meter_references = self._meter_references()
        setup_required: list[str] = []
        if not api_key:
            setup_required.append("Set SOLVIMON_API_KEY on the backend.")
        if not account.solvimon_customer_reference:
            setup_required.append("Create or configure a Solvimon customer reference.")
        if "circuit_block.generated" not in meter_references:
            setup_required.append("Set SOLVIMON_CIRCUIT_BLOCK_METER_REFERENCE.")

        events = self.events()
        synced_events = [event for event in events if event.solvimon_sync_status == "synced"]
        failed_events = [event for event in events if event.solvimon_sync_status == "failed"]
        last_event = (failed_events or synced_events or [None])[-1]
        last_status = "not_configured"
        if last_event is not None:
            last_status = "failed" if last_event.solvimon_sync_status == "failed" else "synced"

        return BillingIntegrationStatus(
            mode=mode if api_key else "disabled",
            configured=not setup_required,
            customer_reference=account.solvimon_customer_reference,
            subscription_reference=account.solvimon_subscription_reference,
            meter_references=meter_references,
            last_sync_status=last_status,
            last_synced_at=last_event.solvimon_synced_at if last_event else None,
            last_error=last_event.solvimon_error if last_event else None,
            setup_required=setup_required,
        )

    def events(self) -> list[UsageEvent]:
        with self._events_lock:
            cached_events = self._cached_events_if_fresh()
            if cached_events is None:
                cached_events = [UsageEvent(**item) for item in self.events_store.read_list()]
                self._events_cache = cached_events
                self._events_cache_signature = self._events_signature()
            return [event.model_copy() for event in cached_events]

    def _cached_events_if_fresh(self) -> list[UsageEvent] | None:
        if self._events_cache is None:
            return None
        if self._events_cache_signature != self._events_signature():
            return None
        return self._events_cache

    def _events_signature(self) -> tuple[int, int] | None:
        try:
            stat = self.events_store.path.stat()
        except FileNotFoundError:
            return None
        return stat.st_mtime_ns, stat.st_size

    def _sync_to_solvimon(self, event: UsageEvent, account: AccountProfile) -> UsageEvent:
        if not self._can_sync_event(event.event_type, account):
            return event.model_copy(update={"solvimon_sync_status": "not_configured"})

        meter_reference = self._meter_references().get(event.event_type)
        if not meter_reference:
            return event.model_copy(update={"solvimon_sync_status": "not_configured"})

        payload = {
            "meter_reference": meter_reference,
            "customer_reference": account.solvimon_customer_reference,
            "reference": event.reference,
            "timestamp": event.timestamp,
            "meter_values": [
                {
                    "reference": os.getenv("SOLVIMON_METER_VALUE_REFERENCE", "quantity"),
                    "number": str(event.quantity),
                }
            ],
        }
        property_reference = os.getenv("SOLVIMON_EVENT_TYPE_PROPERTY_REFERENCE", "")
        if property_reference:
            payload["meter_properties"] = [
                {
                    "reference": property_reference,
                    "value": event.event_type,
                }
            ]

        try:
            self._post_solvimon("/v1/ingest/meter-data", payload)
        except Exception as exc:  # pragma: no cover - network failures vary by host
            return event.model_copy(
                update={
                    "solvimon_sync_status": "failed",
                    "solvimon_error": str(exc),
                }
            )

        return event.model_copy(
            update={
                "solvimon_sync_status": "synced",
                "solvimon_synced_at": datetime.now(timezone.utc).isoformat(),
                "solvimon_error": None,
            }
        )

    def _post_solvimon(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self._api_base()}{path}",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-API-KEY": os.getenv("SOLVIMON_API_KEY", ""),
                "Idempotency-Key": event_idempotency_key(payload),
            },
        )
        timeout = float(os.getenv("SOLVIMON_TIMEOUT_SECONDS", "8"))
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Solvimon returned {exc.code}: {detail}") from exc
        if not raw:
            return {}
        return json.loads(raw)

    def _can_sync_event(self, event_type: str, account: AccountProfile) -> bool:
        return bool(
            os.getenv("SOLVIMON_API_KEY")
            and account.solvimon_customer_reference
            and self._meter_references().get(event_type)
        )

    def _meter_references(self) -> dict[str, str]:
        return {
            event_type: value
            for event_type, env_name in EVENT_METER_ENV.items()
            if (value := os.getenv(env_name, ""))
        }

    def _mode(self) -> str:
        mode = os.getenv("SOLVIMON_ENVIRONMENT", "test").lower()
        return "live" if mode == "live" else "test"

    def _api_base(self) -> str:
        configured = os.getenv("SOLVIMON_API_BASE", "").rstrip("/")
        if configured:
            return configured
        if self._mode() == "live":
            return "https://api.solvimon.com"
        return "https://test.api.solvimon.com"

    def _pricing_message(self, used_blocks: int, remaining: int, overage: float) -> str:
        if used_blocks == 0:
            return "No bill impact yet."
        return (
            f"{used_blocks} generated block event{'s' if used_blocks != 1 else ''} recorded. "
            f"On the Maker plan, {remaining} included blocks remain. "
            f"Estimated overage: GBP {overage:.2f}."
        )


def event_idempotency_key(payload: dict[str, Any]) -> str:
    reference = str(payload.get("reference", ""))
    meter_reference = str(payload.get("meter_reference", ""))
    customer_reference = str(payload.get("customer_reference", ""))
    return f"tracelabs:{customer_reference}:{meter_reference}:{reference}"


# Backwards-compatible name used by the existing app module.
MockSolvimonService = AccountBillingService
