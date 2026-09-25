from __future__ import annotations

from collections import defaultdict
from typing import Any

from .contracts import AppContract
from .store import StateStore


def triage(store: StateStore, contract: AppContract, max_samples: int) -> list[int]:
    matches: dict[str, list[dict[str, Any]]] = defaultdict(list)
    capabilities = contract.capabilities
    for signal in store.signals(contract.app_id):
        if signal["event_type"] != "feedback_submitted":
            continue
        message = str(signal["payload"].get("message", ""))
        normalized = message.lower()
        for theme, capability in capabilities.items():
            if any(keyword.lower() in normalized for keyword in capability.get("signalKeywords", [])):
                matches[theme].append(signal)
                break

    observation_ids: list[int] = []
    for theme, signals in matches.items():
        capability = capabilities[theme]
        samples = [signal["payload"].get("message", "") for signal in signals[:max_samples]]
        evidence = {
            "signalCount": len(signals),
            "sourceEventIds": [signal["source_id"] for signal in signals],
            "samples": samples,
        }
        summary = f"{len(signals)} customer signal(s) support: {capability['description']}"
        observation_ids.append(
            store.upsert_observation(contract.app_id, theme, summary, evidence, score=float(len(signals)))
        )
    return observation_ids

