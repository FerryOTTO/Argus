#!/usr/bin/env python3
"""
沙箱命令执行器 (sandbox_exec)

通过 Docker 容器隔离执行任意命令，提供：
- 资源限制（CPU/内存/磁盘）
- 网络隔离
- 超时控制
- 有害内容检测
- 非 root 执行
"""

import subprocess
import json
import sys
import time
import os
import shlex
import platform
import tempfile
from dataclasses import dataclass, field
from typing import Optional, Dict

from harm_detector import HarmDetector, HarmReport, Severity, standard_detector


# ============================================================
# 配置
# ============================================================
DOCKER_IMAGE = "sandbox-exec:latest"
DOCKER_BINARY = "docker"
WSL_DISTRO = "Ubuntu-24.04"


def _docker_command() -> list:
    """根据运行环境返回 docker 调用前缀。

    Windows 宿主通过 WSL2 桥接调用 docker；原生 Linux / macOS 直接调用 docker。
    用于消除代码与特定运行环境的强耦合。
    """
    if platform.system() == "Windows":
        return ["wsl", "-d", WSL_DISTRO, "--", "sudo", DOCKER_BINARY]
    return [DOCKER_BINARY]

# 默认资源限制
DEFAULT_MEMORY = "512m"
DEFAULT_CPUS = "1.0"
DEFAULT_TIMEOUT = 120  # 秒
DEFAULT_MAX_OUTPUT = 1024 * 1024  # 1MB stdout 上限

# 允许挂载的主机目录白名单
ALLOWED_MOUNTS = [
     os.environ.get("SANDBOX_WORKSPACE", "/tmp/sandbox_workspace"),
    "/tmp/sandbox_workspace",
]


@dataclass
class SandboxResult:
    """沙箱执行结果"""
    stdout: str = ""
    stderr: str = ""
    exit_code: int = -1
    timed_out: bool = False
    execution_time_ms: int = 0
    harm_report: Optional[HarmReport] = None
    blocked: bool = False
    block_reason: str = ""
    container_id: str = ""

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.blocked and not self.timed_out

    def to_dict(self) -> dict:
        d = {
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "execution_time_ms": self.execution_time_ms,
            "blocked": self.blocked,
            "block_reason": self.block_reason,
            "success": self.success,
        }
        if self.harm_report:
            d["harm_report"] = self.harm_report.to_dict()
        return d


class SandboxExecutor:
    """
    Docker 沙箱命令执行器。

    用法：
        sb = SandboxExecutor()
        result = sb.run("python3 -c 'print(2+2)'")
        print(result.stdout)  # "4"
    """

    def __init__(
        self,
        image: str = DOCKER_IMAGE,
        memory: str = DEFAULT_MEMORY,
        cpus: str = DEFAULT_CPUS,
        timeout: int = DEFAULT_TIMEOUT,
        network: str = "none",
        harm_detector: Optional[HarmDetector] = None,
        workspace_mount: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
    ):
        self.image = image
        self.memory = memory
        self.cpus = cpus
        self.timeout = timeout
        self.network = network
        self.harm_detector = harm_detector or standard_detector
        self.workspace_mount = workspace_mount
        self.env = env or {}

    def _build_docker_cmd(self, command: str) -> list:
        """构建 docker run 命令参数（不含二进制前缀，前缀由 _docker_command 统一提供）"""
        cmd = [
            "run",
            "--rm",                          # 执行后自动删除容器
            f"--network={self.network}",     # 网络隔离
            f"--memory={self.memory}",       # 内存限制
            f"--memory-swap={self.memory}",  # 交换空间限制（与内存相同）
            f"--cpus={self.cpus}",           # CPU 限制
            "--pids-limit=50",               # 进程数限制
            "--ulimit", "nofile=64:128",     # 文件描述符限制
            "--cap-drop=ALL",                # 移除所有内核能力
            "--security-opt=no-new-privileges",  # 禁止提权
            "--read-only",                   # 根文件系统只读
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=32m",  # /tmp 独立 tmpfs
        ]

        # 工作区挂载
        if self.workspace_mount:
            cmd.extend(["-v", f"{self.workspace_mount}:/workspace:rw"])
        else:
            # 默认用 tmpfs 做工作区
            cmd.extend(["--tmpfs", "/workspace:rw,noexec,nosuid,size=128m"])

        # 环境变量
        for k, v in self.env.items():
            cmd.extend(["-e", f"{k}={v}"])

        cmd.append(self.image)

        # timeout 包装
        timeout_cmd = f"timeout {self.timeout} bash -c {shlex.quote(command)}"
        cmd.extend(["bash", "-c", timeout_cmd])

        return cmd

    def run(self, command: str) -> SandboxResult:
        """
        在沙箱中执行命令。

        Args:
            command: 要执行的 shell 命令

        Returns:
            SandboxResult 包含 stdout, stderr, exit_code 等
        """
        result = SandboxResult()
        start_time = time.time()

        # === 命令执行前扫描命令字符串本身（事前拦截） ===
        pre_harm = self.harm_detector.scan(command, source="command")
        if pre_harm.blocked:
            result.harm_report = pre_harm
            result.blocked = True
            result.block_reason = pre_harm.summary
            result.exit_code = 126  # 命令无法执行
            result.stdout = f"[SANDBOX BLOCKED] 命令被拦截：{pre_harm.summary}"
            result.execution_time_ms = int((time.time() - start_time) * 1000)
            return result

        docker_cmd = _docker_command() + self._build_docker_cmd(command)

        try:
            proc = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout + 10,  # 给 docker 额外 10 秒
                encoding="utf-8",
                errors="replace",
            )

            result.stdout = proc.stdout[:DEFAULT_MAX_OUTPUT]
            result.stderr = proc.stderr[:DEFAULT_MAX_OUTPUT]
            result.exit_code = proc.returncode

            # 检测 timeout（timeout 命令的退出码是 124）
            if proc.returncode == 124:
                result.timed_out = True

        except subprocess.TimeoutExpired:
            result.timed_out = True
            result.exit_code = -1
            result.stderr = "Docker execution timed out (host-level timeout)"

        result.execution_time_ms = int((time.time() - start_time) * 1000)

        # === 有害内容检测 ===
        harm = self.harm_detector.scan_multi({
            "stdout": result.stdout,
            "stderr": result.stderr,
        })

        result.harm_report = harm

        if harm.blocked:
            result.blocked = True
            result.block_reason = harm.summary
            # 阻止有害内容：清空输出，替换为安全信息
            result.stdout = f"[SANDBOX BLOCKED] 执行结果被阻止：{harm.summary}"
            result.stderr = ""
            result.exit_code = 126  # 命令无法执行

        return result

    def run_python(self, code: str) -> SandboxResult:
        """在沙箱中执行 Python 代码"""
        # 将代码写入临时脚本，在沙箱中执行
        escaped = code.replace("'", "'\"'\"'")
        return self.run(f"python3 -c '{escaped}'")

    def run_script(self, script_path: str) -> SandboxResult:
        """在沙箱中执行脚本文件"""
        return self.run(f"bash {shlex.quote(script_path)}")

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
# 预配置的执行器
# ============================================================

# 标准执行器
default_executor = SandboxExecutor()

# 轻量执行器（更小资源限制）
light_executor = SandboxExecutor(memory="128m", cpus="0.5", timeout=30)

# 构建用执行器（更大资源）
build_executor = SandboxExecutor(memory="1g", cpus="2.0", timeout=300, network="none")


# ============================================================
# CLI 入口
# ============================================================
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="沙箱命令执行器")
    parser.add_argument("--command", "-c", required=True, help="要执行的命令")
    parser.add_argument("--memory", default=DEFAULT_MEMORY, help="内存限制")
    parser.add_argument("--cpus", default=DEFAULT_CPUS, help="CPU 限制")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="超时（秒）")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出")
    args = parser.parse_args()

    sb = SandboxExecutor(
        memory=args.memory,
        cpus=args.cpus,
        timeout=args.timeout,
    )

    result = sb.run(args.command)

    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(result.stdout)

    if result.blocked:
        sys.exit(126)
    sys.exit(result.exit_code if result.exit_code >= 0 else 1)
