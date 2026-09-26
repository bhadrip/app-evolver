from __future__ import annotations

from collections import defaultdict
from collections import Counter
from typing import Any

from .contracts import AppContract
from .store import StateStore


def group_signals(
    signals: list[dict[str, Any]], capabilities: dict[str, Any], max_samples: int
) -> list[dict[str, Any]]:
    """Pure signal grouping used by local and future remote analyst agents."""
    matches: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for signal in signals:
        if signal["event_type"] != "feedback_submitted":
            continue
        message = str(signal["payload"].get("message", ""))
        normalized = message.lower()
        for theme, capability in capabilities.items():
            if any(keyword.lower() in normalized for keyword in capability.get("signalKeywords", [])):
                matches[theme].append(signal)
                break

    themes: list[dict[str, Any]] = []
    for theme, signals in matches.items():
        capability = capabilities[theme]
        samples = [signal["payload"].get("message", "") for signal in signals[:max_samples]]
        evidence = {
            "signalCount": len(signals),
            "sourceEventIds": [signal["source_id"] for signal in signals],
            "samples": samples,
            "appVersions": [
                {"version": version, "revision": revision, "signalCount": count}
                for (version, revision), count in sorted(Counter(
                    (signal.get("app_version", "unknown"), signal.get("app_revision", "unknown"))
                    for signal in signals
                ).items())
            ],
        }
        summary = f"{len(signals)} customer signal(s) support: {capability['description']}"
        themes.append({
            "theme": theme,
            "summary": summary,
            "evidence": evidence,
            "score": float(len(signals)),
        })
    return themes


def triage(store: StateStore, contract: AppContract, max_samples: int) -> list[int]:
    observation_ids: list[int] = []
    for theme in group_signals(store.signals(contract.app_id), contract.capabilities, max_samples):
        observation_ids.append(store.upsert_observation(
            contract.app_id,
            theme["theme"],
            theme["summary"],
            theme["evidence"],
            theme["score"],
        ))
    return observation_ids
