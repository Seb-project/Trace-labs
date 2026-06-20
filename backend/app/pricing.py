from __future__ import annotations

from pathlib import Path

from .models import PricingPreview, UsageEvent, UsageEventRequest
from .storage import JsonStore


class MockSolvimonService:
    def __init__(self, data_dir: Path):
        self.store = JsonStore(data_dir / "usage_events.json")

    def record(self, request: UsageEventRequest) -> UsageEvent:
        event = UsageEvent(
            event_type=request.event_type,
            quantity=request.quantity,
            metadata=request.metadata,
        )
        events = self.store.read_list()
        events.append(event.model_dump())
        self.store.write_list(events)
        return event

    def preview(self) -> PricingPreview:
        events = [UsageEvent(**item) for item in self.store.read_list()]
        used_blocks = int(sum(e.quantity for e in events if e.event_type == "circuit_block.generated"))
        remaining = max(0, 50 - used_blocks)
        overage = max(0, used_blocks - 50) * 0.20
        return PricingPreview(
            used_blocks=used_blocks,
            remaining_blocks=remaining,
            estimated_overage=round(overage, 2),
            estimated_monthly_bill=round(12 + overage, 2),
            recent_events=events[-8:],
        )
