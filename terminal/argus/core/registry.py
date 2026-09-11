"""加载配置并集中保存各安全模块 Adapter。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from argus.adapters.access_control_adapter import AccessControlAdapter
from argus.adapters.audit_adapter import AuditAdapter
from argus.adapters.base import BaseAdapter
from argus.adapters.io_guard_adapter import IoGuardAdapter
from argus.adapters.retrieval_guard_adapter import RetrievalGuardAdapter
from argus.adapters.tool_guard_adapter import ToolGuardAdapter
from argus.common.models import Action
from argus.modules.tool_guard.llm_config import build_config


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _resolve_config_path(environment_name: str, default: str) -> Path:
    configured = os.getenv(environment_name, default)
    path = Path(configured)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as stream:
        return yaml.safe_load(stream) or {}


class AdapterRegistry:
    """按名称注册和取得 Adapter，不包含具体安全判断逻辑。"""

    def __init__(self) -> None:
        self.config_path = _resolve_config_path(
            "ARGUS_CONFIG", "configs/modules.yaml"
        )
        self.policy_path = _resolve_config_path(
            "ARGUS_POLICY", "configs/policy.yaml"
        )
        self.config = _load_yaml(self.config_path)
        self.policy = _load_yaml(self.policy_path)

        io_guard = IoGuardAdapter()
        rg_cfg = self.config.get("modules", {}).get("retrieval_guard", {})
        tg_cfg = self.config.get("modules", {}).get("tool_guard", {})
        # 用 modules.yaml 的 tool_guard 段初始化 LLM 裁判配置单例(环境变量优先)
        build_config(tg_cfg)
        self._adapters: dict[str, BaseAdapter] = {
            "io_guard_input": io_guard,
            "io_guard_context": io_guard,
            "io_guard_output": io_guard,
            "access_control": AccessControlAdapter(),
            "tool_guard": ToolGuardAdapter(
                on_error=str(tg_cfg.get("on_error", "block"))
            ),
            "retrieval_guard": RetrievalGuardAdapter(
                model_path=rg_cfg.get("model_path"),
                guards=rg_cfg.get("guards"),
            ),
            "audit": AuditAdapter(),
        }

    @property
    def action_priority(self) -> list[Action]:
        configured = self.policy.get("actions", {}).get("priority")
        if configured:
            return configured
        return ["block", "human_review", "rewrite", "allow"]

    def get(self, name: str) -> BaseAdapter:
        if name not in self._adapters:
            raise KeyError(f"Adapter 未注册: {name}")
        return self._adapters[name]

    def module_config(self, name: str) -> dict[str, Any]:
        return self.config.get("modules", {}).get(name, {})

    def is_enabled(self, name: str) -> bool:
        return bool(self.module_config(name).get("enabled", True))

    def on_error(self, name: str) -> str:
        return str(self.module_config(name).get("on_error", "allow"))

    def health(self) -> dict[str, str]:
        groups = {
            "io_guard": (
                self.is_enabled("io_guard_input")
                or self.is_enabled("io_guard_context")
                or self.is_enabled("io_guard_output")
            ),
            "access_control": self.is_enabled("access_control"),
            "tool_guard": self.is_enabled("tool_guard"),
            "retrieval_guard": self.is_enabled("retrieval_guard"),
            "audit": self.is_enabled("audit"),
        }
        return {name: "ok" if enabled else "disabled" for name, enabled in groups.items()}


registry = AdapterRegistry()
