# rate_limiter.py — 轻量级内存速率限制，无外部依赖
import time
from collections import defaultdict
from functools import wraps


class RateLimiter:
    """基于滑动窗口的简易速率限制器"""

    def __init__(self):
        self._windows: dict[str, list[float]] = defaultdict(list)

    def _clean(self, key: str, window_sec: float, now: float) -> None:
        cutoff = now - window_sec
        self._windows[key] = [t for t in self._windows[key] if t > cutoff]
        if not self._windows[key]:
            del self._windows[key]  # 清空无活动记录的键，避免字典无界增长

    def is_allowed(self, key: str, max_requests: int, window_sec: float = 60) -> bool:
        now = time.time()
        self._clean(key, window_sec, now)
        if len(self._windows[key]) >= max_requests:
            return False
        self._windows[key].append(now)
        return True


# 全局单例
limiter = RateLimiter()


def rate_limit(max_requests: int, window_sec: float = 60):
    """FastAPI 依赖：对同一 IP 限制请求频率"""
    from fastapi import Request, HTTPException

    async def dependency(request: Request):
        client_ip = request.client.host if request.client else "127.0.0.1"
        key = f"{request.url.path}:{client_ip}"
        if not limiter.is_allowed(key, max_requests, window_sec):
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "请求过于频繁，请稍后重试",
                    "code": "RATE_LIMITED",
                    "retry_after": window_sec,
                }
            )
        return True

    return dependency
