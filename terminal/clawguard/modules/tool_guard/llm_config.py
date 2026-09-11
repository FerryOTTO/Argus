"""Tool Guard 意图匹配裁判的 LLM 配置管理。

默认值来源优先级(从低到高):
1. 内置默认值;
2. ``configs/modules.yaml`` 中 ``modules.tool_guard`` 段的显式配置;
3. 环境变量 ``TOOL_GUARD_LLM_*``;
4. 运行期通过 ``PUT /v1/tool_guard/config`` 修改(仅内存生效,重启后回退到 2/3)。

API key 提供脱敏查看,避免通过配置接口泄露明文。
"""

from __future__ import annotations

import os
import threading
from typing import Any


_DEFAULTS = {
    "base_url": "https://api.deepseek.com/v1",
    "api_key": "",
    "model": "deepseek-chat",
    "block_threshold": 0.4,
    "review_threshold": 0.7,
    "timeout_seconds": 30.0,
}


class ToolGuardLLMConfig:
    """线程安全的运行期 LLM 配置单例。"""

    _instance: "ToolGuardLLMConfig | None" = None
    _instance_lock = threading.Lock()

    def __init__(self, yaml_config: dict[str, Any] | None = None) -> None:
        self._lock = threading.RLock()
        values: dict[str, Any] = dict(_DEFAULTS)
        yaml_config = yaml_config or {}
        for key in values:
            if key in yaml_config:
                values[key] = yaml_config[key]
        # 环境变量覆盖 yaml
        env_map = {
            "base_url": "TOOL_GUARD_LLM_BASE_URL",
            "api_key": "TOOL_GUARD_LLM_API_KEY",
            "model": "TOOL_GUARD_LLM_MODEL",
            "block_threshold": "TOOL_GUARD_BLOCK_THRESHOLD",
            "review_threshold": "TOOL_GUARD_REVIEW_THRESHOLD",
            "timeout_seconds": "TOOL_GUARD_LLM_TIMEOUT",
        }
        for key, env_name in env_map.items():
            raw = os.getenv(env_name)
            if raw is None or raw == "":
                continue
            if isinstance(values[key], bool):
                values[key] = raw.lower() in {"1", "true", "yes", "on"}
            elif isinstance(values[key], float):
                try:
                    values[key] = float(raw)
                except ValueError:
                    pass
            elif isinstance(values[key], int):
                try:
                    values[key] = int(raw)
                except ValueError:
                    pass
            else:
                values[key] = raw
        self._values = values

    @classmethod
    def instance(cls, yaml_config: dict[str, Any] | None = None) -> "ToolGuardLLMConfig":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls(yaml_config)
        return cls._instance

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._values.get(key, default)

    def configured(self) -> bool:
        """LLM 调用所需配置是否齐备。

        远程服务必须提供 api_key;无 api_key 时仅允许本地地址(如 Ollama)。
        """
        with self._lock:
            base_url = str(self._values.get("base_url") or "")
            if not base_url or not self._values.get("model"):
                return False
            if self._values.get("api_key"):
                return True
            local_markers = ("localhost", "127.0.0.1", "0.0.0.0", "::1")
            return any(marker in base_url for marker in local_markers)

    def snapshot(self) -> dict[str, Any]:
        """当前配置快照,api_key 脱敏为 ***。"""
        with self._lock:
            snap = dict(self._values)
        if snap.get("api_key"):
            snap["api_key"] = "***"
        return snap

    @classmethod
    def defaults(cls) -> dict[str, Any]:
        """内置默认配置(不含运行期修改)。"""
        return dict(_DEFAULTS)

    def reset(self) -> dict[str, Any]:
        """重置为内置默认值(仅内存生效),返回脱敏快照。"""
        with self._lock:
            self._values = dict(_DEFAULTS)
        return self.snapshot()

    def update(self, patch: dict[str, Any]) -> dict[str, Any]:
        """运行期更新配置,仅接受已知键;返回更新后的脱敏快照。"""
        known = set(_DEFAULTS)
        with self._lock:
            for key, value in patch.items():
                if key not in known or value is None:
                    continue
                self._values[key] = value
        return self.snapshot()


def build_config(yaml_config: dict[str, Any] | None = None) -> ToolGuardLLMConfig:
    """供启动期初始化单例使用;重复调用返回同一实例。"""
    return ToolGuardLLMConfig.instance(yaml_config)
