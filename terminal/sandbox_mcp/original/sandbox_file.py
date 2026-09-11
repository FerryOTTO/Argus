#!/usr/bin/env python3
"""
沙箱文件读取器 (sandbox_file)

通过独立的 Docker 容器读取文件内容，与执行容器完全隔离。
提供：
- 只读文件访问
- 文件内容有害检测
- 路径白名单/黑名单
- 文件大小限制
- 文件类型检测
"""

import subprocess
import os
import json
import sys
import time
import shlex
import platform
import tempfile
from dataclasses import dataclass, field
from typing import Optional, List, Dict

from harm_detector import HarmDetector, HarmReport, Severity, standard_detector


# ============================================================
# 配置
# ============================================================
DOCKER_IMAGE = "sandbox-file:latest"
DOCKER_BINARY = "docker"
WSL_DISTRO = "Ubuntu-24.04"


def _docker_command() -> list:
    """根据运行环境返回 docker 调用前缀。

    Windows 宿主通过 WSL2 桥接调用 docker；原生 Linux / macOS 直接调用 docker。
    """
    if platform.system() == "Windows":
        return ["wsl", "-d", WSL_DISTRO, "--", "sudo", DOCKER_BINARY]
    return [DOCKER_BINARY]

# 默认限制
DEFAULT_MEMORY = "64m"
DEFAULT_CPUS = "0.5"
DEFAULT_TIMEOUT = 30  # 秒
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

# 禁止读取的路径模式
FORBIDDEN_PATHS = [
    "/etc/shadow",
    "/etc/passwd",
    "/root/",
    "/home/*/.ssh/",
    "/home/*/.aws/",
    "/home/*/.gcloud/",
    "/proc/",
    "/sys/",
    "/dev/",
    "~/.hermes/.env",
    "*.pem",
    "*.key",
    "id_rsa*",
]


@dataclass
class FileReadResult:
    """文件读取结果"""
    path: str = ""
    content: str = ""
    size_bytes: int = 0
    line_count: int = 0
    file_type: str = ""
    exists: bool = False
    is_directory: bool = False
    error: str = ""
    harm_report: Optional[HarmReport] = None
    blocked: bool = False
    block_reason: str = ""

    @property
    def success(self) -> bool:
        return self.exists and not self.blocked and not self.error

    def to_dict(self) -> dict:
        d = {
            "path": self.path,
            "size_bytes": self.size_bytes,
            "line_count": self.line_count,
            "file_type": self.file_type,
            "exists": self.exists,
            "is_directory": self.is_directory,
            "error": self.error,
            "blocked": self.blocked,
            "block_reason": self.block_reason,
            "success": self.success,
        }
        if self.blocked:
            d["content"] = f"[BLOCKED] {self.block_reason}"
        else:
            d["content"] = self.content
        if self.harm_report:
            d["harm_report"] = self.harm_report.to_dict()
        return d


class SandboxFileReader:
    """
    Docker 沙箱文件读取器。

    使用独立的 sandbox-file 容器，仅提供只读文件访问。

    用法：
        reader = SandboxFileReader()
        result = reader.read("/path/to/file.txt")
        print(result.content)
    """

    def __init__(
        self,
        image: str = DOCKER_IMAGE,
        memory: str = DEFAULT_MEMORY,
        cpus: str = DEFAULT_CPUS,
        timeout: int = DEFAULT_TIMEOUT,
        max_file_size: int = MAX_FILE_SIZE,
        harm_detector: Optional[HarmDetector] = None,
        allowed_dirs: Optional[List[str]] = None,
    ):
        self.image = image
        self.memory = memory
        self.cpus = cpus
        self.timeout = timeout
        self.max_file_size = max_file_size
        self.harm_detector = harm_detector or standard_detector
        self.allowed_dirs = allowed_dirs or [
            os.path.expanduser("~"),
            "/mnt/c/Users",
            "/tmp",
        ]

    def _check_path_safety(self, path: str) -> Optional[str]:
        """检查路径是否安全可读。返回错误信息，None 表示安全。"""
        # 路径规范化
        real_path = os.path.realpath(os.path.expanduser(path))

        # 检查禁止路径
        for forbidden in FORBIDDEN_PATHS:
            if forbidden.endswith("/") and real_path.startswith(forbidden):
                return f"路径被禁止：匹配禁读模式 '{forbidden}'"
            if forbidden.startswith("*.") and real_path.endswith(forbidden[1:]):
                return f"文件类型被禁止：匹配禁读模式 '{forbidden}'"
            if os.path.basename(real_path).startswith("id_rsa"):
                return "SSH 密钥文件禁止读取"
            if real_path.startswith("/proc/") or real_path.startswith("/sys/"):
                return "系统目录禁止读取"

        # 检查是否在允许目录内
        allowed = False
        for allowed_dir in self.allowed_dirs:
            allowed_real = os.path.realpath(os.path.expanduser(allowed_dir))
            if real_path.startswith(allowed_real):
                allowed = True
                break

        if not allowed:
            return f"路径不在允许目录白名单内：{real_path}"

        # 检查文件大小
        if os.path.isfile(real_path):
            size = os.path.getsize(real_path)
            if size > self.max_file_size:
                return f"文件过大：{size} bytes（限制 {self.max_file_size} bytes）"

        return None

    def _wsl_path(self, windows_path: str) -> str:
        """将 Windows 路径转换为 WSL 路径
        C:\\Users\\xxx -> /mnt/c/Users/xxx
        """
        if len(windows_path) >= 2 and windows_path[1] == ':':
            drive = windows_path[0].lower()
            rest = windows_path[2:].replace('\\', '/')
            return f"/mnt/{drive}{rest}"
        return windows_path

    def _build_docker_read_cmd(self, path: str, offset: int = 1, limit: int = 500) -> list:
        """构建 docker run 读取文件命令参数（不含二进制前缀，前缀由 _docker_command 统一提供）"""
        cmd = [
            "run",
            "--rm",
            "--network=none",
            f"--memory={self.memory}",
            f"--cpus={self.cpus}",
            "--pids-limit=20",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--read-only",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=32m",
        ]

        # 挂载源目录（只读）
        wsl_path = self._wsl_path(os.path.abspath(path))
        mount_dir = os.path.dirname(wsl_path)
        cmd.extend(["-v", f"{mount_dir}:/data:ro"])

        # 构建读取命令
        file_basename = os.path.basename(wsl_path)
        read_cmd = (
            f"python3 -c \"\n"
            f"import os, sys, json\n"
            f"filepath = '/data/{file_basename}'\n"
            f"if not os.path.exists(filepath):\n"
            f"    print(json.dumps({{'exists': False, 'error': 'file not found'}}))\n"
            f"    sys.exit(0)\n"
            f"if os.path.isdir(filepath):\n"
            f"    entries = sorted(os.listdir(filepath))[:200]\n"
            f"    print(json.dumps({{'exists': True, 'is_directory': True, 'entries': entries, 'size': len(entries)}}))\n"
            f"    sys.exit(0)\n"
            f"size = os.path.getsize(filepath)\n"
            f"with open(filepath, 'r', encoding='utf-8', errors='replace') as f:\n"
            f"    lines = f.readlines()\n"
            f"total = len(lines)\n"
            f"start = {offset} - 1\n"
            f"end = min(start + {limit}, total)\n"
            f"selected = lines[start:end]\n"
            f"print(json.dumps({{'exists': True, 'is_directory': False, 'size': size, 'total_lines': total, 'offset': {offset}, 'limit': {limit}, 'lines': selected}}, ensure_ascii=False))\n"
            f"\""
        )

        cmd.append(self.image)
        cmd.extend(["bash", "-c", read_cmd])

        return cmd

    def read(self, path: str, offset: int = 1, limit: int = 500) -> FileReadResult:
        """
        通过沙箱读取文件内容。

        Args:
            path: 文件路径（Windows 或 WSL 格式）
            offset: 起始行号（1-indexed）
            limit: 最大行数

        Returns:
            FileReadResult
        """
        result = FileReadResult(path=path)

        # 展开路径
        expanded = os.path.expanduser(path)
        if not os.path.isabs(expanded):
            expanded = os.path.abspath(expanded)
        expanded = os.path.normpath(expanded)
        result.path = expanded

        # 安全检查
        safety_error = self._check_path_safety(expanded)
        if safety_error:
            result.error = safety_error
            result.blocked = True
            result.block_reason = safety_error
            return result

        # 如果文件不存在（主机端检查失败），直接返回
        if not os.path.exists(expanded):
            result.error = f"文件不存在：{expanded}"
            return result

        if os.path.isdir(expanded):
            result.exists = True
            result.is_directory = True
            try:
                entries = sorted(os.listdir(expanded))
                result.content = "\n".join(entries)
                result.line_count = len(entries)
                result.file_type = "directory"
            except PermissionError:
                result.error = "无权限读取目录"
            return result

        # 构建 Docker 命令
        docker_cmd = _docker_command() + self._build_docker_read_cmd(expanded, offset, limit)

        start_time = time.time()

        try:
            proc = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout + 10,
                encoding="utf-8",
                errors="replace",
            )

            # 解析 JSON 输出
            json_output = proc.stdout.strip()
            if proc.stderr:
                docker_stderr = proc.stderr.strip()
                # 尝试从混合输出中提取 JSON
                for line in proc.stdout.split("\n"):
                    line = line.strip()
                    if line.startswith("{"):
                        json_output = line
                        break

            data = json.loads(json_output)

            if not data.get("exists"):
                result.error = data.get("error", "文件在容器中不存在")
                return result

            if data.get("is_directory"):
                result.exists = True
                result.is_directory = True
                result.content = "\n".join(data.get("entries", []))
                result.line_count = len(data.get("entries", []))
                result.file_type = "directory"
                return result

            result.exists = True
            result.size_bytes = data.get("size", 0)
            result.line_count = data.get("total_lines", 0)
            result.content = "".join(data.get("lines", []))
            result.file_type = os.path.splitext(expanded)[1] or "text"

        except subprocess.TimeoutExpired:
            result.error = "文件读取超时"
            return result
        except (json.JSONDecodeError, KeyError) as e:
            # Docker 输出可能包含非 JSON 内容
            result.error = f"解析容器输出失败：{e}"
            result.content = proc.stdout[:500] if proc.stdout else ""
            return result

        # === 有害内容检测 ===
        if result.content:
            harm = self.harm_detector.scan(result.content, source=f"file:{os.path.basename(expanded)}")
            result.harm_report = harm

            if harm.blocked:
                result.blocked = True
                result.block_reason = harm.summary
                result.content = f"[SANDBOX BLOCKED] 文件内容被阻止：{harm.summary}"

        return result

    def read_raw(self, path: str) -> FileReadResult:
        """读取整个文件（绕过行数限制，但仍受文件大小限制）"""
        return self.read(path, offset=1, limit=1000000)

    @staticmethod
    def quick_check() -> bool:
        """快速检查沙箱是否可用"""
        try:
            r = subprocess.run(
                _docker_command() + ["image", "inspect", DOCKER_IMAGE],
                capture_output=True, text=True, timeout=10
            )
            return r.returncode == 0
        except Exception:
            return False


# ============================================================
# 预配置的读取器
# ============================================================
default_reader = SandboxFileReader()


# ============================================================
# CLI 入口
# ============================================================
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="沙箱文件读取器")
    parser.add_argument("--read", "-r", required=True, help="要读取的文件路径")
    parser.add_argument("--offset", type=int, default=1, help="起始行号")
    parser.add_argument("--limit", type=int, default=500, help="最大行数")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出")
    args = parser.parse_args()

    reader = SandboxFileReader()
    result = reader.read(args.read, offset=args.offset, limit=args.limit)

    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(result.content)

    sys.exit(0 if result.success else 1)
