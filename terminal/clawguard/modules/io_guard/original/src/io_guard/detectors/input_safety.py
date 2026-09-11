from __future__ import annotations

import re

from io_guard.detectors.base import Detector
from io_guard.normalization import normalize_text, safe_snippet
from io_guard.types import Evidence, GuardRequest, RiskType, SourceType


class MaliciousUserInstructionDetector(Detector):
    """Detect explicit harmful user intent, separate from prompt injection."""

    name = "malicious_user_instruction_detector"

    _BENIGN_CONTEXT = re.compile(
        r"(?:防止|防范|检测|识别|阻止|拒绝|不要|避免|危害|风险|法律后果|"
        r"安全研究|安全教育|新闻报道|历史介绍|概述|解释为什么|"
        r"prevent|detect|defend|mitigate|avoid|risk|safety|educational)",
        re.IGNORECASE,
    )
    _ACTION = re.compile(
        r"(?:如何|怎么|怎样|帮我|替我|教我|给出|生成|编写|制作|制造|"
        r"部署|执行|入侵|攻击|窃取|盗取|泄露|绕过|破解|投毒|下毒|"
        r"how\s+to|help\s+me|write|build|make|create|deploy|execute|"
        r"hack|steal|exfiltrate|bypass|poison)",
        re.IGNORECASE,
    )
    _HARMFUL_OBJECT = re.compile(
        r"(?:炸弹|炸药|爆炸物|武器|毒气|毒品|恶意软件|木马|勒索软件|"
        r"病毒|后门|键盘记录器|钓鱼页面|他人账号|密码|访问令牌|"
        r"银行卡|身份证信息|人肉|自杀方法|自残方法|"
        r"bomb|explosive|weapon|malware|trojan|ransomware|virus|"
        r"backdoor|keylogger|phishing|credential|password|access token|"
        r"suicide method|self-harm method)",
        re.IGNORECASE,
    )
    _CONTACT_OBJECT = re.compile(
        r"(?:电话号码|手机号码|手机号|联系电话|联系方式|电子邮箱|邮箱地址|邮箱|"
        r"phone(?: number)?|mobile(?: number)?|contact details?|e-?mail(?: address)?)",
        re.IGNORECASE,
    )
    _UNAUTHORIZED_CONTACT_ACTION = re.compile(
        r"(?:窃取|盗取|泄露|倒卖|贩卖|公开|曝光|"
        r"绕过(?:权限|授权|验证)|未经(?:授权|许可)|未授权(?:查询|获取)?|"
        r"steal|exfiltrate|leak|dox|bypass\s+(?:permission|authorization))",
        re.IGNORECASE,
    )
    _THIRD_PARTY = re.compile(
        r"(?:他人|别人|同事|前女友|前男友|陌生人|客户|用户|受害者|"
        r"someone\s+else|coworker|customer|user|victim)",
        re.IGNORECASE,
    )
    _CONTACT_ACCESS_ACTION = re.compile(
        r"(?:查询|查找|获取|调取|导出|搜集|收集|告诉我|给我|"
        r"look\s+up|find|get|obtain|export|collect|give\s+me)",
        re.IGNORECASE,
    )

    def detect(self, request: GuardRequest) -> list[Evidence]:
        if request.source_type != SourceType.USER_PROMPT:
            return []
        text = normalize_text(request.content)
        if not text or self._BENIGN_CONTEXT.search(text):
            return []
        contact = self._CONTACT_OBJECT.search(text)
        unauthorized = self._UNAUTHORIZED_CONTACT_ACTION.search(text)
        third_party = self._THIRD_PARTY.search(text)
        contact_access = self._CONTACT_ACCESS_ACTION.search(text)
        if contact is not None and (
            unauthorized is not None
            or (third_party is not None and contact_access is not None)
        ):
            matches = [
                item
                for item in (
                    contact,
                    unauthorized,
                    third_party,
                    contact_access,
                )
                if item is not None
            ]
            start = min(item.start() for item in matches)
            end = max(item.end() for item in matches)
            return [
                Evidence(
                    detector=self.name,
                    risk_type=(
                        RiskType.MALICIOUS_USER_INSTRUCTION_OR_JAILBREAK
                    ),
                    message="unauthorized contact-information request",
                    score=0.94,
                    snippet=safe_snippet(text, start, end),
                    start=start,
                    end=end,
                    field_path="$.text",
                    step_id=str(
                        request.metadata.get("step_id") or "user-input"
                    ),
                )
            ]
        action = self._ACTION.search(text)
        harmful_object = self._HARMFUL_OBJECT.search(text)
        if action is None or harmful_object is None:
            return []
        start = min(action.start(), harmful_object.start())
        end = max(action.end(), harmful_object.end())
        return [
            Evidence(
                detector=self.name,
                risk_type=(
                    RiskType.MALICIOUS_USER_INSTRUCTION_OR_JAILBREAK
                ),
                message="explicit harmful user instruction",
                score=0.94,
                snippet=safe_snippet(text, start, end),
                start=start,
                end=end,
                field_path="$.text",
                step_id=str(request.metadata.get("step_id") or "user-input"),
            )
        ]
