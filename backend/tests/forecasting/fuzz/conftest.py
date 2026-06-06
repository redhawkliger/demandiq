"""Hypothesis profiles for the math-soundness fuzz bot.

`ci`      — deterministic, bounded; the PR gate. Zero flakes.
`nightly` — deep, randomized; the scheduled bot.

Select with `pytest -p no:randomly --hypothesis-profile=ci` or via
HYPOTHESIS_PROFILE; the session hook below honors the env var, default `ci`.
"""
import os

from hypothesis import HealthCheck, settings

settings.register_profile(
    "ci",
    max_examples=150,
    deadline=2000,                 # ms per example; pure math is fast
    derandomize=True,              # fixed example stream -> reproducible gate
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile(
    "nightly",
    max_examples=5000,
    deadline=None,                 # deep exploration, no per-example clock
    derandomize=False,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci"))
