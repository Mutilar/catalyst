"""Retired compatibility surface for the former verify-on-stop loop.

Verification evidence remains passive in :mod:`agent.verification_evidence`.
Catalyst must not synthesize repository verification work or prescribe commands;
project instructions, plugins, LUCID, and the executing control plane own that
lifecycle.
"""

from __future__ import annotations

from typing import Any, Iterable


def verify_on_stop_enabled(config: dict[str, Any] | None = None) -> bool:
    """Return ``False``: Catalyst no longer owns an active verification loop."""
    del config
    return False


def build_verify_on_stop_nudge(
    *,
    session_id: str | None,
    changed_paths: Iterable[str],
    attempts: int = 0,
    max_attempts: int = 2,
) -> None:
    """Return no synthetic turn; retained for extension compatibility only."""
    del session_id, changed_paths, attempts, max_attempts
    return None


__all__ = ["build_verify_on_stop_nudge", "verify_on_stop_enabled"]
