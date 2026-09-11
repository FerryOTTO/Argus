"""
适配器 A：URL 白名单。
is_trusted(url) / filter_results(results) / filter_urls(urls)
"""
import fnmatch
import yaml
from pathlib import Path
from typing import List


class URLWhitelist:
    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = str(Path(__file__).parent / "whitelist.yaml")
        with open(config_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        self.trusted = cfg.get("trusted", [])
        self.blocked = cfg.get("blocked", [])

    def is_trusted(self, url: str) -> bool:
        # 提取纯域名 (https://x.com/ → x.com)
        from urllib.parse import urlparse
        host = urlparse(url).hostname or url
        for p in self.blocked:
            if fnmatch.fnmatch(host, p):
                return False
        for p in self.trusted:
            if fnmatch.fnmatch(host, p):
                return True
        return False  # 不在白名单也不在黑名单 →  不放行但不可信

    def in_whitelist(self, url: str) -> bool:
        for p in self.trusted:
            if fnmatch.fnmatch(url, p):
                return True
        return False

    def filter_results(self, results: List[dict]) -> List[dict]:
        return [r for r in results if self.is_trusted(r.get("url", ""))]

    def filter_urls(self, urls: List[str]) -> List[str]:
        return [u for u in urls if self.is_trusted(u)]
