#!/usr/bin/env python3
"""
环境检测脚本 — 检测 WSL2 和 Docker 是否可用

用法:
    python check_env.py
    python check_env.py --json
    python check_env.py --fix  # 尝试自动修复（启用 WSL2 等）

返回码:
    0 - 环境就绪
    1 - 环境有问题，需要手动修复
"""

import subprocess
import sys
import os
import json
import platform

# ── 配置 ──────────────────────────────────────────────────────────
WSL_DISTRO = "Ubuntu-24.04"
DOCKER_IMAGE = "sandbox-exec:latest"

# ── 颜色输出 ──────────────────────────────────────────────────────
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    END = '\033[0m'

def ok(text): return f"{Colors.GREEN}✓{Colors.END} {text}"
def fail(text): return f"{Colors.RED}✗{Colors.END} {text}"
def warn(text): return f"{Colors.YELLOW}⚠{Colors.END} {text}"
def info(text): return f"{Colors.BLUE}ℹ{Colors.END} {text}"

# ── 检测函数 ──────────────────────────────────────────────────────

def check_wsl2():
    """检测 WSL2 是否已安装"""
    try:
        result = subprocess.run(
            ["wsl", "--version"],
            capture_output=True,
            timeout=10,
            shell=True
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False

def check_wsl_distro():
    """检测指定 WSL 发行版是否可用"""
    try:
        result = subprocess.run(
            ["wsl", "-l", "-v"],
            capture_output=True,
            timeout=10,
            shell=True
        )
        output = result.stdout.decode('utf-8', errors='replace')
        return WSL_DISTRO in output
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False

def check_docker():
    """检测 Docker 是否可用"""
    try:
        result = subprocess.run(
            ["docker", "version"],
            capture_output=True,
            timeout=10,
            shell=True
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False

def check_docker_wsl():
    """检测 WSL 内 Docker 是否可用"""
    try:
        result = subprocess.run(
            ["wsl", "-d", WSL_DISTRO, "--", "sudo", "docker", "version"],
            capture_output=True,
            timeout=10,
            shell=True
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False

def check_docker_image():
    """检测沙箱镜像是否存在"""
    try:
        result = subprocess.run(
            ["wsl", "-d", WSL_DISTRO, "--", "sudo", "docker", "image", "inspect", DOCKER_IMAGE],
            capture_output=True,
            timeout=10,
            shell=True
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False

def enable_wsl2():
    """启用 WSL2 和虚拟机平台"""
    print("[fix] 启用 WSL2 和虚拟机平台...")
    try:
        subprocess.run(
            ["dism.exe", "/online", "/enable-feature", "/featurename:Microsoft-Windows-Subsystem-Linux", "/all", "/norestart"],
            capture_output=True, timeout=60, shell=True
        )
        subprocess.run(
            ["dism.exe", "/online", "/enable-feature", "/featurename:VirtualMachinePlatform", "/all", "/norestart"],
            capture_output=True, timeout=60, shell=True
        )
        print("[fix] WSL2 和虚拟机平台已启用，需要重启系统。")
        return True
    except Exception as e:
        print(f"[fix] 启用失败: {e}")
        return False

# ── 报告输出 ──────────────────────────────────────────────────────

def print_report(results):
    """打印格式化的环境检测报告"""
    print()
    print(f"{Colors.BOLD}{Colors.CYAN}╔══════════════════════════════════════════════╗{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}║     WSL2 & Docker 环境检测报告             ║{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}╚══════════════════════════════════════════════╝{Colors.END}")
    print()
    
    # WSL2
    if results["wsl2"]:
        print(ok(f"WSL2: 已安装"))
    else:
        print(fail(f"WSL2: 未安装"))
        print(f"      {Colors.YELLOW}建议: wsl --install{Colors.END}")
    
    # WSL Distro
    if results["wsl_distro"]:
        print(ok(f"WSL 发行版 ({WSL_DISTRO}): 已安装"))
    else:
        print(fail(f"WSL 发行版 ({WSL_DISTRO}): 未安装"))
        print(f"      {Colors.YELLOW}建议: wsl --install -d {WSL_DISTRO}{Colors.END}")
    
    # Docker
    if results["docker"]:
        print(ok(f"Docker (Windows): 已安装"))
    else:
        print(fail(f"Docker (Windows): 未安装"))
        print(f"      {Colors.YELLOW}建议: winget install Docker.DockerDesktop{Colors.END}")
    
    # Docker in WSL
    if results["docker_wsl"]:
        print(ok(f"Docker (WSL): 可用"))
    else:
        print(fail(f"Docker (WSL): 不可用"))
        if results["docker"]:
            print(f"      {Colors.YELLOW}建议: 在 WSL 内安装 Docker (sudo apt install docker.io){Colors.END}")
    
    # Docker Image
    if results["docker_image"]:
        print(ok(f"沙箱镜像 ({DOCKER_IMAGE}): 已构建"))
    else:
        print(fail(f"沙箱镜像 ({DOCKER_IMAGE}): 未构建"))
        print(f"      {Colors.YELLOW}建议: cd docker && build_images.sh{Colors.END}")
    
    # Summary
    print()
    print(f"{Colors.BOLD}{'─' * 48}{Colors.END}")
    
    if results["ready"]:
        print(f"{Colors.GREEN}{Colors.BOLD}状态: 环境就绪，可以开始使用沙箱！{Colors.END}")
    else:
        print(f"{Colors.RED}{Colors.BOLD}状态: 环境有问题，需要修复{Colors.END}")
        print()
        print("修复步骤:")
        if not results["wsl2"]:
            print(f"  1. 启用 WSL2: wsl --install")
        elif not results["wsl_distro"]:
            print(f"  1. 安装发行版: wsl --install -d {WSL_DISTRO}")
        elif not results["docker"]:
            print(f"  1. 安装 Docker Desktop: winget install Docker.DockerDesktop")
        elif not results["docker_wsl"]:
            print(f"  1. 在 WSL 内安装 Docker: sudo apt install docker.io")
        elif not results["docker_image"]:
            print(f"  1. 构建沙箱镜像: cd docker && ./build_images.sh")
        print(f"  2. 重启系统")
        print(f"  3. 重新运行此脚本验证")
    
    print(f"{Colors.BOLD}{'═' * 48}{Colors.END}")
    print()

def main():
    import argparse
    parser = argparse.ArgumentParser(description="检测 WSL2 和 Docker 环境")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    parser.add_argument("--fix", action="store_true", help="尝试自动修复")
    args = parser.parse_args()
    
    # 执行检测
    results = {
        "wsl2": check_wsl2(),
        "wsl_distro": check_wsl_distro(),
        "docker": check_docker(),
        "docker_wsl": check_docker_wsl(),
        "docker_image": check_docker_image(),
    }
    
    # 判断是否就绪
    results["ready"] = all(results.values())
    
    # 自动修复
    if args.fix and not results["ready"]:
        if not results["wsl2"]:
            enable_wsl2()
        print("[fix] 请重启系统后重新运行此脚本。")
        return 1
    
    # JSON 输出
    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return 0 if results["ready"] else 1
    
    # 标准报告
    print_report(results)
    
    return 0 if results["ready"] else 1

if __name__ == "__main__":
    sys.exit(main())
