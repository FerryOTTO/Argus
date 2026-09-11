"""
滑动窗口引擎。
调用 model.predict()，窗口逐块扫描，检出即停。
"""
from .model import PIGuardModel


class SlidingWindow:
    def __init__(self, model: PIGuardModel, threshold: float = 0.5,
                 window_size: int = 400, step: int = 200):
        self._model = model
        self.threshold = threshold
        self.window_size = window_size
        self.step = step

    def scan(self, text: str) -> dict:
        """text in → {safe, score, hit_window?} out"""
        with self._model._lock:
            tokenizer = self._model.tokenizer
            tokens = tokenizer.encode(text, add_special_tokens=False)
        total = len(tokens)

        if total <= self.window_size:
            print(f"[window] single predict, tokens={total} (≤{self.window_size})")
            score = self._model.predict(text)
            return self._result(score)

        print(f"[window] sliding start: tokens={total} window={self.window_size} step={self.step}")
        max_score = 0.0
        windows_checked = 0
        for start in range(0, total - self.window_size + 1, self.step):
            windows_checked += 1
            with self._model._lock:
                chunk = tokenizer.decode(
                    tokens[start:start + self.window_size],
                    skip_special_tokens=True, clean_up_tokenization_spaces=True,
                )
            score = self._model.predict(chunk)
            if score > max_score:
                max_score = score
            if max_score >= self.threshold:          # 检出即停
                print(f"[window] BLOCKED at window {windows_checked}: score={score:.4f}")
                return self._result(max_score, {
                    "start": start, "end": start + self.window_size,
                    "snippet": chunk[:120],
                })

        print(f"[window] all {windows_checked} windows checked, max_score={max_score:.4f}")
        return self._result(max_score)

    def _result(self, score: float, hit: dict | None = None) -> dict:
        return {"safe": score < self.threshold, "score": round(score, 4),
                "hit_window": hit}
