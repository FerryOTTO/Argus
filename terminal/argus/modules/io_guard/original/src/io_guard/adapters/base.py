from __future__ import annotations

from abc import ABC, abstractmethod

try:
    from argus.common.models import ModuleResult, SecurityRequest
except ModuleNotFoundError:
    # The standalone module uses its compatibility contract in unit tests.
    # In the integration repository the canonical Argus models win.
    from io_guard.argus_contracts import ModuleResult, SecurityRequest


class BaseAdapter(ABC):
    name: str

    @abstractmethod
    async def run(self, request: SecurityRequest) -> ModuleResult:
        """Run one security module without leaking module exceptions."""
