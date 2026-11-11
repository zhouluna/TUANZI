"""Timing plan for offline in-place action interpolation.

LUNA ZHOU, 2026-11-10.

The desktop player holds every manifest frame for one integer delay.
Subdividing that delay keeps the action's cycle length and only changes
how many pictures share it. Walk, run, and the bed still are not planned
here: walk/run already advance every 16 ms and move the window, and the
bed picture is not a motion cycle.
"""

from __future__ import annotations

DELAY_MIN_MS = 20
DELAY_MAX_MS = 40
DELAY_TARGET_MS = 30

# PetWindow.perform_motion plays these once. The last pose is held for the
# original frame time; blending it back into frame 0 would add a return
# the current player never shows.
ONE_SHOT_CLIPS = frozenset({"pounce"})

UNCHANGED = {
    "walk": "64 frames at 16 ms, with stride_pixels tied to window motion.",
    "run": "48 frames at 16 ms, with stride_pixels tied to window motion.",
    "bed": "One still. Naps breathe by deforming the chest of a sleep pose, not by cycling frames.",
}


def loops_back_to_start(clip_id: str) -> bool:
    return clip_id not in ONE_SHOT_CLIPS


def choose_factor(duration_ms: int) -> int:
    """Pick how many equal slices replace one original frame delay.

    The slice length has to divide the original delay so the cycle time
    stays exact, and it stays near 30 ms (about 33 fps) inside 20–40 ms.
    """
    if duration_ms < DELAY_MIN_MS * 2:
        raise ValueError(f"Frame delay {duration_ms} ms is already dense")
    options = []
    for factor in range(2, duration_ms // DELAY_MIN_MS + 1):
        if duration_ms % factor:
            continue
        delay = duration_ms // factor
        if DELAY_MIN_MS <= delay <= DELAY_MAX_MS:
            options.append((abs(delay - DELAY_TARGET_MS), -factor, factor))
    if not options:
        raise ValueError(f"No integer delay between {DELAY_MIN_MS} and {DELAY_MAX_MS} ms divides {duration_ms}")
    options.sort()
    return options[0][2]


def output_frame_count(keyframe_count: int, factor: int) -> int:
    """Both looping and one-shot plans emit keyframes × factor pictures."""
    if keyframe_count < 2 or factor < 2:
        raise ValueError("Interpolation needs at least two keyframes and a factor of 2")
    return keyframe_count * factor


def frame_delay(duration_ms: int, factor: int) -> int:
    if duration_ms % factor:
        raise ValueError(f"{duration_ms} ms is not divisible by {factor}")
    return duration_ms // factor


def keyframe_slot(keyframe_index: int, factor: int) -> int:
    """Playback index that still shows the original keyframe unchanged."""
    return keyframe_index * factor
