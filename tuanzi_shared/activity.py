"""Irregular sequencing over clips that already exist.

LUNA ZHOU, 2026-11-10. The model, when one is available, only chooses from
this list. Nothing here invents frames or motion.
"""

from __future__ import annotations

import random

# Same family as the desktop weights. Sleep stays common; locomotion stays
# available; the last two picks are skipped so the sequence cannot lock.
WEIGHTS = (
    ("walk", 8),
    ("run", 2),
    ("nuzzle", 3),
    ("wave", 1),
    ("purr", 2),
    ("ball", 2),
    ("groom", 3),
    ("groom_fur", 3),
    ("eat", 1),
    ("bed", 10),
    ("butterfly", 2),
    ("tail", 1),
    ("tilt", 1),
)

LIBRARY_IDS = frozenset(name for name, _weight in WEIGHTS)
PAUSE_MIN_MS = 400
PAUSE_MAX_MS = 24000


def clip_allowed(name: str, available: set[str] | None = None) -> bool:
    if name not in LIBRARY_IDS and name != "nest-breath":
        return False
    if available is None:
        return True
    return name in available


def irregular_pause_ms(rng: random.Random | None = None) -> int:
    """Three bands, so the pet does not tick on a fixed period."""
    rng = rng or random
    band = rng.random()
    if band < 0.45:
        return int(rng.uniform(400, 1600))
    if band < 0.8:
        return int(rng.uniform(2200, 7000))
    return int(rng.uniform(9000, PAUSE_MAX_MS))


def plan_steps(recent: list[str] | None = None, count: int = 3,
               available: set[str] | None = None, rng: random.Random | None = None) -> list[dict]:
    rng = rng or random
    history = list(recent or [])
    steps = []
    pool = [(name, weight) for name, weight in WEIGHTS if available is None or name in available]
    if not pool:
        return []
    for _ in range(count):
        varied = [item for item in pool if item[0] not in history[-2:]] or pool
        names = [name for name, _weight in varied]
        weights = [weight for _name, weight in varied]
        chosen = rng.choices(names, weights=weights, k=1)[0]
        steps.append({"clip": chosen, "pause_ms": irregular_pause_ms(rng), "source": "library"})
        history.append(chosen)
    return steps


def normalize_model_steps(payload: object, available: set[str]) -> list[dict]:
    """Accept only known clip ids and a pause inside the irregular range."""
    if not isinstance(payload, dict):
        return []
    raw = payload.get("steps")
    if not isinstance(raw, list):
        return []
    steps = []
    for item in raw[:3]:
        if not isinstance(item, dict):
            continue
        clip = item.get("clip")
        pause = item.get("pause_ms")
        if not isinstance(clip, str) or clip not in available:
            continue
        if isinstance(pause, bool) or not isinstance(pause, (int, float)):
            pause = irregular_pause_ms()
        pause_ms = int(max(PAUSE_MIN_MS, min(PAUSE_MAX_MS, pause)))
        steps.append({"clip": clip, "pause_ms": pause_ms, "source": "model"})
    return steps
