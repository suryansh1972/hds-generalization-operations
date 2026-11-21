"""HTTP API for semgen, built on Litestar (optional extra: ``pip install 'semgen[api]'``).

``create_app()`` returns a Litestar application over one ``SemgenEngine``; the core library never imports this
package, so ``import semgen`` works without Litestar installed.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from semgen.api.app import ApiLimits

__all__ = ["ApiLimits", "create_app"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        try:
            from semgen.api import app
        except ImportError as e:   # pragma: no cover - exercised only without the extra
            raise ImportError("semgen.api needs the 'api' extra: pip install 'semgen[api]'") from e
        return getattr(app, name)
    raise AttributeError(name)
