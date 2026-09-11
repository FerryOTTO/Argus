"""所有安全模块 Adapter 的最小公共模板。"""

from __future__ import annotations

from abc import ABC, abstractmethod

from clawguard.common.models import ModuleResult, SecurityRequest


class BaseAdapter(ABC):
    name = "base"

    @abstractmethod
    async def run(self, request: SecurityRequest) -> ModuleResult:
        """调用原安全模块，并把结果转换为 ModuleResult。"""
