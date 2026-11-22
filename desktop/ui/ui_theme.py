"""Backwards-compatible theme entry point.

The full QSS theme lives in `desktop/ui/theme.py` (light + dark with an
explicit palette so Windows dark mode can never dim the UI). This module
delegates so existing imports keep working.
"""

from __future__ import annotations

from .theme import apply_theme, configured_theme, current_qss

__all__ = ["apply_theme", "configured_theme", "current_qss"]
