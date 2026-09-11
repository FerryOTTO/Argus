#!/usr/bin/env python3
"""
沙箱有害内容检测引擎
对命令执行结果（stdout/stderr）和文件内容进行多层扫描，
检测并阻止恶意/有害输出。
"""

import re
import json
import hashlib
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from enum import Enum

# Severity 排名（模块级字典，绕过 Enum 将类变量当作成员的坑）
_rank = {"safe": 0, "suspicious": 1, "dangerous": 2}


class Severity(Enum):
    SAFE = "safe"
    SUSPICIOUS = "suspicious"
    DANGEROUS = "dangerous"

    def __lt__(self, other):
        if isinstance(other, Severity):
            return _rank[self.value] < _rank[other.value]
        return NotImplemented

    def __le__(self, other):
        if isinstance(other, Severity):
            return _rank[self.value] <= _rank[other.value]
        return NotImplemented

    def __gt__(self, other):
        if isinstance(other, Severity):
            return _rank[self.value] > _rank[other.value]
        return NotImplemented

    def __ge__(self, other):
        if isinstance(other, Severity):
            return _rank[self.value] >= _rank[other.value]
        return NotImplemented


@dataclass
class HarmMatch:
    """单次有害匹配记录"""
    pattern_name: str
    severity: Severity
    matched_text: str
    line_number: int = -1
    offset: int = -1


@dataclass
class HarmReport:
    """有害检测报告"""
    is_safe: bool = True
    blocked: bool = False
    severity: Severity = Severity.SAFE
    matches: List[HarmMatch] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "is_safe": self.is_safe,
            "blocked": self.blocked,
            "severity": self.severity.value,
            "match_count": len(self.matches),
            "matches": [
                {
                    "pattern": m.pattern_name,
                    "severity": m.severity.value,
                    "matched": m.matched_text[:200],
                    "line": m.line_number,
                }
                for m in self.matches
            ],
            "summary": self.summary,
        }


class HarmDetector:
    """
    多层有害内容检测器。

    检测层次：
    1. 危险命令模式 —— 反弹shell、下载执行、权限提升等
    2. 敏感文件泄露 —— /etc/shadow, ~/.ssh, 环境变量泄露
    3. 数据外泄模式 —— base64大段编码后的数据、curl外传
    4. 恶意代码模式 —— eval/exec混淆、编码绕过
    5. 内容安全 —— 明显的诈骗、钓鱼模式
    """

    # ============================================================
    # 第1层：危险命令/代码执行模式
    # ============================================================
    DANGEROUS_COMMAND_PATTERNS = [
        # 反弹 shell
        (r"\b(bash|sh|nc|ncat|netcat)\s+.*>\s*&.*(/dev/tcp|/dev/udp)", "reverse_shell", Severity.DANGEROUS),
        (r"bash\s+-i\s+>&", "reverse_shell_bash", Severity.DANGEROUS),
        (r"python3?\s+-c\s+.*socket\.connect\s*\(.*\(\s*['\"](\d{1,3}\.){3}\d{1,3}['\"]", "reverse_shell_python", Severity.DANGEROUS),
        (r"php\s+-r\s+.*fsockopen\s*\(", "reverse_shell_php", Severity.DANGEROUS),

        # 下载并执行
        (r"\b(curl|wget)\s+.*\|\s*(bash|sh|python|perl|ruby)", "download_and_exec", Severity.DANGEROUS),
        (r"\b(curl|wget)\s+.*\s+-O\s+/tmp/.*&&\s*(bash|sh|python|chmod)", "download_to_tmp_and_exec", Severity.DANGEROUS),

        # 权限提升
        (r"\b(chmod\s+[0-7]*7[0-7]*7|chmod\s+.*\+s\s)", "chmod_dangerous", Severity.DANGEROUS),
        (r"\bsudo\s+su\b", "sudo_su", Severity.SUSPICIOUS),

        # 内核模块/系统调用
        (r"\b(insmod|modprobe|rmmod)\s", "kernel_module", Severity.DANGEROUS),
        (r"\bmount\s+-o\s+.*\b(bind|remount)\b", "mount_bind", Severity.DANGEROUS),

        # 直接磁盘操作
        (r"\bdd\s+if=.*of=/dev/(sd|hd|nvme|xvd)", "dd_disk_write", Severity.DANGEROUS),
        (r"\bmkfs\.\w+\s+/dev/", "mkfs", Severity.DANGEROUS),
    ]

    # ============================================================
    # 第2层：敏感文件泄露
    # ============================================================
    SENSITIVE_FILE_PATTERNS = [
        (r"/etc/(shadow|passwd|sudoers|hosts\.allow|hosts\.deny)", "sensitive_etc", Severity.SUSPICIOUS),
        (r"(~|/home/\w+)/\.ssh/(id_rsa|id_ed25519|authorized_keys)", "ssh_key_leak", Severity.DANGEROUS),
        (r"(~|/home/\w+)/\.(aws|gcloud|azure|config)/", "cloud_credential", Severity.DANGEROUS),
        (r"(-----BEGIN\s+(RSA|EC|DSA|OPENSSH|PGP)\s+PRIVATE\s+KEY-----)", "private_key_content", Severity.DANGEROUS),
        (r"-----BEGIN\s+CERTIFICATE-----", "certificate_content", Severity.SUSPICIOUS),
    ]

    # ============================================================
    # 第3层：数据外泄 / 网络探测
    # ============================================================
    EXFILTRATION_PATTERNS = [
        # base64 大段数据后跟 curl/wget POST
        (r"base64\s+.*-w0.*\|\s*(curl|wget)", "base64_exfil", Severity.DANGEROUS),
        # DNS 隧道特征
        (r"\b(nslookup|dig|host)\s+.*\.[a-z0-9]{30,}\.", "dns_tunnel", Severity.SUSPICIOUS),
        # 内网扫描
        (r"\b(nmap|masscan|zmap)\s", "network_scan", Severity.DANGEROUS),
    ]

    # ============================================================
    # 第4层：恶意代码模式
    # ============================================================
    MALICIOUS_CODE_PATTERNS = [
        # eval/exec 混淆绕过
        (r"\b(eval|exec|execfile|compile)\s*\(\s*(__import__|base64|chr\(|ord\(|''\.join)", "obfuscated_exec", Severity.SUSPICIOUS),
        # 从字符串构建危险调用
        (r"getattr\s*\(\s*__import__\s*\(\s*['\"]os['\"]\s*\)\s*,\s*['\"]system['\"]\s*\)", "getattr_os_system", Severity.DANGEROUS),
        # subprocess 危险调用
        (r"subprocess\.(call|Popen|run|check_output)\s*\(\s*['\"].*?\|\s*(bash|sh)", "subprocess_pipe_shell", Severity.SUSPICIOUS),
        # base64 解码后执行（编码绕过：echo xxx | base64 -d | bash）
        (r"base64\s+(-d|--decode)\b[^|]*\|\s*(bash|sh|zsh|dash)", "base64_decode_exec", Severity.DANGEROUS),
    ]

    # ============================================================
    # 第5层：内容安全（钓鱼/诈骗/恶意链接）
    # ============================================================
    CONTENT_SAFETY_PATTERNS = [
        # 已知恶意域名模式
        (r"https?://(?:[a-z0-9-]+\.)*?(?:ngrok|serveo|localtunnel|pagekite)\.\w+/", "tunnel_domain", Severity.SUSPICIOUS),
        # 加密货币挖矿
        (r"\b(minerd|cpuminer|xmrig|claymore|ethminer)\b", "crypto_miner", Severity.DANGEROUS),
        # 可疑的 .onion 链接
        (r"https?://[a-z2-7]{16,}\.onion", "onion_link", Severity.SUSPICIOUS),
    ]

    # 所有模式合并
    ALL_PATTERNS = (
        [("dangerous_cmd",) + x for x in DANGEROUS_COMMAND_PATTERNS] +
        [("sensitive_file",) + x for x in SENSITIVE_FILE_PATTERNS] +
        [("exfiltration",) + x for x in EXFILTRATION_PATTERNS] +
        [("malicious_code",) + x for x in MALICIOUS_CODE_PATTERNS] +
        [("content_safety",) + x for x in CONTENT_SAFETY_PATTERNS]
    )

    def __init__(
        self,
        block_on: Severity = Severity.DANGEROUS,
        warn_on: Severity = Severity.SUSPICIOUS,
        max_output_scan_bytes: int = 1024 * 1024,  # 1MB
    ):
        self.block_on = block_on
        self.warn_on = warn_on
        self.max_output_scan_bytes = max_output_scan_bytes
        # 编译所有正则
        self._compiled: List[Tuple[str, str, re.Pattern, Severity]] = []
        for category, pattern, name, severity in self.ALL_PATTERNS:
            try:
                self._compiled.append((category, name, re.compile(pattern, re.IGNORECASE | re.MULTILINE), severity))
            except re.error:
                pass

    def scan(self, text: str, source: str = "stdout") -> HarmReport:
        """
        扫描文本内容，返回有害检测报告。

        Args:
            text: 待扫描文本
            source: 来源标识（stdout/stderr/file_content）

        Returns:
            HarmReport 对象
        """
        report = HarmReport()

        if not text:
            report.summary = f"[{source}] 空内容，跳过扫描"
            return report

        # 截断超大输出
        if len(text) > self.max_output_scan_bytes:
            text = text[:self.max_output_scan_bytes]
            report.summary = f"[{source}] 输出过大，仅扫描前 {self.max_output_scan_bytes} 字节"

        lines = text.split("\n")

        for category, name, pattern, severity in self._compiled:
            for match in pattern.finditer(text):
                matched = match.group(0)
                line_no = -1
                # 找行号
                pos = match.start()
                for i, line in enumerate(lines):
                    if pos < len(line) + 1:
                        line_no = i + 1
                        break
                    pos -= len(line) + 1

                hm = HarmMatch(
                    pattern_name=name,
                    severity=severity,
                    matched_text=matched[:200],
                    line_number=line_no,
                    offset=match.start(),
                )
                report.matches.append(hm)

        # 计算总体安全等级
        if not report.matches:
            report.is_safe = True
            report.severity = Severity.SAFE
            report.summary = f"{report.summary} | [{source}] 安全，未检测到有害内容"
        else:
            max_sev = max(m.severity for m in report.matches)
            report.severity = max_sev

            if max_sev.value == Severity.DANGEROUS.value:
                report.is_safe = False
                report.blocked = True
                report.summary = (
                    f"{report.summary} | [{source}] 检测到 {len(report.matches)} 个匹配，"
                    f"其中包含危险模式，已阻止"
                )
            elif max_sev.value == Severity.SUSPICIOUS.value:
                report.is_safe = False  # 可疑也算不安全，但默认不阻止
                report.blocked = (self.block_on == Severity.SUSPICIOUS)
                report.summary = (
                    f"{report.summary} | [{source}] 检测到 {len(report.matches)} 个可疑匹配"
                )

        return report

    def scan_multi(self, sources: dict) -> HarmReport:
        """
        扫描多个来源的内容（stdout + stderr + file 等）。

        Args:
            sources: {"stdout": "...", "stderr": "...", "file": "..."}

        Returns:
            合并的 HarmReport
        """
        merged = HarmReport()
        for source, text in sources.items():
            if text:
                r = self.scan(str(text), source)
                merged.matches.extend(r.matches)
                if r.blocked:
                    merged.blocked = True
                if r.severity.value != Severity.SAFE.value:
                    merged.is_safe = False

        if not merged.matches:
            merged.is_safe = True
            merged.severity = Severity.SAFE
            merged.summary = "所有来源安全，未检测到有害内容"
        else:
            max_sev = max(m.severity for m in merged.matches)
            merged.severity = max_sev
            merged.summary = (
                f"多源扫描：{len(merged.matches)} 个匹配，"
                f"最高严重度={max_sev.value}，"
                f"阻止={merged.blocked}"
            )

        return merged

    # --- 静态工具方法 ---
    @staticmethod
    def hash_content(text: str) -> str:
        """内容哈希，用于审计追踪"""
        return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


# ============================================================
# 预配置的检测器实例（生产默认值）
# ============================================================
# 严格模式：危险+可疑都阻止
strict_detector = HarmDetector(block_on=Severity.SUSPICIOUS)

# 标准模式：只阻止危险级别（默认）
standard_detector = HarmDetector(block_on=Severity.DANGEROUS)
