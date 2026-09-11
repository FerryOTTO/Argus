"""
适配器 B：注入检测。
model + window 串联，配置自含。
"""
import yaml
from pathlib import Path
from .model import PIGuardModel
from .window import SlidingWindow


class InjectionGuard:
    def __init__(self, model_path: str = None):
        cfg = yaml.safe_load(open(Path(__file__).parent / "config.yaml", encoding="utf-8"))

        print("[B] 加载 PIGuard...")
        self._model = PIGuardModel(model_path=model_path)
        print(f"[B] 设备: {self.device_name}")

        self._window = SlidingWindow(
            self._model,
            threshold=cfg["threshold"],
            window_size=cfg["window_size"],
            step=cfg["step"],
        )
        print(f"[B] 窗口={self.window_size} 步长={self.step} 阈值={self.threshold}")

    @property
    def device_name(self):   return self._model.device_name
    @property
    def window_size(self):   return self._window.window_size
    @property
    def step(self):          return self._window.step
    @property
    def threshold(self):     return self._window.threshold

    def check(self, text: str) -> dict:
        """text in → {safe, score, hit_window?} out"""
        return self._window.scan(text)
