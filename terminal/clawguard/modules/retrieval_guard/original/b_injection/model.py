"""
PIGuard 模型加载 + 单次推理。
只加载一次，线程安全。
"""
import os
import torch
import threading
from pathlib import Path
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    pipeline,
)


# 项目根 = ClawguardV2.1（model.py 位于 .../clawguard/modules/retrieval_guard/original/b_injection/）
PROJECT_ROOT = Path(__file__).resolve().parents[5]
# 约定模型目录（README 9.7）：clawguard/modules/retrieval_guard/models/，gitignore 排除不提交
DEFAULT_MODEL_PATH = PROJECT_ROOT / "clawguard" / "modules" / "retrieval_guard" / "models" / "PIGuard"


class PIGuardModel:
    def __init__(self, model_path: str = None):
        if model_path is None:
            model_path = str(DEFAULT_MODEL_PATH)
        else:
            # config 传的路径：相对项目根解析，绝对路径原样用
            p = Path(model_path)
            if not p.is_absolute():
                p = PROJECT_ROOT / p
            model_path = str(p)

        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        self.device = 0 if torch.cuda.is_available() else -1

        model = AutoModelForSequenceClassification.from_pretrained(
            model_path, trust_remote_code=True, local_files_only=True
        )
        tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)

        self._pipe = pipeline(
            "text-classification", model=model, tokenizer=tokenizer,
            device=self.device, truncation=True, max_length=512,
        )
        self._tokenizer = tokenizer
        self._lock = threading.Lock()

    @property
    def device_name(self) -> str:
        return "cuda" if self.device == 0 else "cpu"

    @property
    def tokenizer(self):
        return self._tokenizer

    def predict(self, text: str) -> float:
        """单次推理。高分 = 注入。"""
        with self._lock:
            r = self._pipe(text)[0]
        return r["score"] if r["label"] == "injection" else 1.0 - r["score"]
