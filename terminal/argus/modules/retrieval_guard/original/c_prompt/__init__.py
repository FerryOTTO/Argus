"""
适配器 C：提示词工程包装。
只替换 OpenClaw 的 START/END 标记，不篡改其他逻辑。

设计来源：
  Spotlighting (Google DeepMind)     — 动态标记区分数据与指令
  Self-Reminder  (Nature MI)         — 数据前植入行为契约
  Random Sequence Enclosure (社区)    — 同一随机序列两头封
  Post-prompting  (社区)             — 安全指令在数据后，利用 recency bias
"""
import yaml
import random
import string
from pathlib import Path


class PromptWrapper:

    def __init__(self):
        cfg = yaml.safe_load(open(Path(__file__).parent / "config.yaml", encoding="utf-8"))
        self._rand_len = cfg["random_length"]
        self._self_reminder = cfg["self_reminder"].strip()
        self._post_prompting = cfg["post_prompting"].strip()

    def wrap(self, content: str, metadata: str = "", warning: str = "") -> str:
        """
        content  — replaceMarkers 后的纯文本
        metadata — JS 侧拼好的 "Source: Web Search\n..."（保留原逻辑）
        warning  — JS 侧拼好的警告语或空串（保留原逻辑）
        """
        tag = self._random_seq()
        return (
            f"{warning}"                    # ← JS 原逻辑
            f"── [{tag}] ──\n"             # Random Sequence + Spotlighting
            f"\n"
            f"{self._self_reminder}\n"      # Self-Reminder（数据前）
            f"\n"
            f"{metadata}\n"                 # ← JS 原逻辑
            f"{'-' * 40}\n"
            f"{content}\n"                  # ← 数据在中间
            f"{'-' * 40}\n"
            f"\n"
            f"── [{tag}] ──\n"             # 同一序列闭合
            f"\n"
            f"{self._post_prompting}\n"     # Post-prompting（数据后）
        )

    def _random_seq(self) -> str:
        return ''.join(random.choices(
            string.ascii_letters + string.digits, k=self._rand_len
        ))
