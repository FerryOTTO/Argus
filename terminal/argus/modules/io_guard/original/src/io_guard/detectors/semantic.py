from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Protocol

from io_guard.detectors.base import Detector
from io_guard.detectors.stage_classifier import StageAwareCharClassifier
from io_guard.types import Evidence, GuardRequest, RiskType, SourceType


class SemanticClassifier(Protocol):
    def __call__(
        self,
        text: str,
        source_type: SourceType,
    ) -> tuple[bool, float, str]: ...


class SemanticDetector(Detector):
    """Single production semantic backend for the narrowed taxonomy."""

    name = "semantic_detector"

    # The retained character model overweights short fragments such as
    # ``我的`` and ``是多少``.  Only bypass that model for a complete,
    # narrowly-scoped request to view the requester's own contact details.
    # Rule detectors still run before this detector, and extra instructions
    # make the full match fail.
    # Bare "电话" is included so combined phrases ("电话邮箱", "电话和邮箱")
    # match as two contact nouns rather than falling through to the model.
    _CONTACT_TERM = (
        r"(?:电话号码|手机号码|手机号|联系电话|电子邮箱|邮箱地址|"
        r"联系方式|电话|邮箱)"
    )
    _CONTACT_PHRASE = (
        rf"(?:{_CONTACT_TERM}"
        rf"(?:[、,，\s]*(?:和|或|与|以及)?[、,，\s]*{_CONTACT_TERM})*)"
    )
    _SELF_CONTACT_QUERY = re.compile(
        rf"^(?:"
        rf"(?:请问)?(?:你知道)?"
        rf"(?:我(?:自己)?的|我本人的|本人的|自己的)"
        rf"{_CONTACT_PHRASE}"
        rf"(?:各)?(?:是|为)?(?:什么|多少)?(?:吗|呢)?"
        rf"|"
        rf"(?:请|麻烦)?(?:帮我)?(?:查询|查看|显示|告诉我|查)(?:一下)?"
        rf"(?:我(?:自己)?的|我本人的|本人的|自己的)"
        rf"{_CONTACT_PHRASE}"
        rf"(?:吗|呢)?"
        rf")$",
        re.IGNORECASE,
    )
    _BENIGN_SUMMARY_TASK = re.compile(
        r"^(?:请|麻烦)?(?:帮我)?(?:总结|整理|概括)(?:一下)?"
        r"(?:今天|本次|这次|刚才)?(?:的)?"
        r"(?:会议纪要|会议记录|讨论内容|会议内容)[。.!！?？]*$",
        re.IGNORECASE,
    )
    _BENIGN_FILE_OPERATION = re.compile(
        r"(?:保存|写入|写到|创建|读取|展示|确认|备忘录|"
        r"\bwrite\b|\bread\b)",
        re.IGNORECASE,
    )
    _BENIGN_FILE_DESTINATION = re.compile(
        r"(?:/tmp/[A-Za-z0-9][A-Za-z0-9._-]{0,100}|"
        r"临时(?:文件|备忘录)|普通备忘录|"
        r"\b(?:write|read)\s*工具)",
        re.IGNORECASE,
    )
    _BENIGN_FILE_CONTENT = re.compile(
        r"(?:hello(?:\s+argus)?|普通(?:测试)?文本|非敏感|"
        r"项目联调|联调测试|这句话|内容为\s*hello|"
        r"“[^”\r\n]{1,100}”|\"[^\"\r\n]{1,100}\")",
        re.IGNORECASE,
    )
    _OPERATIONAL_TASK_RISK = re.compile(
        r"(?:忽略|绕过|越狱|泄露|窃取|盗取|未经授权|"
        r"系统提示|系统指令|开发者消息|隐藏指令|隐藏配置|"
        r"密码|口令|验证码|动态码|令牌|凭证|密钥|"
        r"身份证|银行卡|恶意软件|木马|勒索软件|病毒|后门|"
        r"炸弹|炸药|爆炸物|武器|毒品|自杀|自残|"
        r"删除|清空|格式化|提权|反向\s*shell|执行|运行|"
        r"\b(?:ignore|disregard|override|jailbreak|reveal|bypass|"
        r"password|passcode|secret|token|credential|api\s*key|otp|"
        r"malware|ransomware|virus|backdoor|bomb|explosive|weapon|"
        r"delete|remove|format|execute|run|shell|powershell|cmd|bash|"
        r"sudo|curl|wget)\b)",
        re.IGNORECASE,
    )
    _UNSAFE_LOCAL_PATH = re.compile(
        r"(?:\.\.[\\/]|/(?:etc|proc|sys|dev|root|home)/|"
        r"[A-Za-z]:[\\/](?:Windows|Program Files|Users)[\\/]|"
        r"\.ssh[\\/])",
        re.IGNORECASE,
    )

    def __init__(
        self,
        classifier: SemanticClassifier | None = None,
        threshold: float = 0.55,
        disabled_reason: str | None = None,
    ) -> None:
        self.classifier = classifier
        self.threshold = float(threshold)
        self.disabled_reason = disabled_reason

    @classmethod
    def from_config(
        cls,
        config: dict[str, Any],
        *,
        base_dir: Path,
    ) -> "SemanticDetector":
        backend = str(config.get("backend", "stage_char_classifier"))
        if backend != "stage_char_classifier":
            raise ValueError(
                "only stage_char_classifier is supported by the narrowed IO Guard"
            )
        model_dir = Path(str(config["model_dir"]))
        if not model_dir.is_absolute():
            model_dir = (base_dir / model_dir).resolve()
        classifier = StageAwareCharClassifier(
            model_dir=model_dir,
            policy_score=float(config.get("policy_score", 0.90)),
            threshold_overrides={
                str(key): float(value)
                for key, value in dict(
                    config.get("threshold_overrides", {})
                ).items()
            },
        )
        return cls(
            classifier=classifier,
            threshold=float(config.get("detector_threshold", 0.55)),
        )

    def status(self) -> dict[str, Any]:
        if self.classifier is None:
            status: dict[str, Any] = {
                "enabled": False,
                "backend": "none",
            }
            if self.disabled_reason:
                status["reason"] = self.disabled_reason
            return status
        status_method = getattr(self.classifier, "status", None)
        if callable(status_method):
            return dict(status_method())
        return {"enabled": True, "backend": "custom_classifier"}

    def detect(self, request: GuardRequest) -> list[Evidence]:
        if self.classifier is None or not request.content:
            return []
        if (
            self._is_self_contact_query(request)
            or self._is_clearly_benign_user_task(request)
        ):
            return []
        unsafe, score, label = self.classifier(
            request.content,
            request.source_type,
        )
        score = max(0.0, min(float(score), 1.0))
        if not unsafe or score < self.threshold:
            return []
        category_name = label.split(";", 1)[0].strip().lower()
        try:
            risk_type = RiskType(category_name)
        except ValueError:
            risk_type = self._fallback_type(request.source_type)
        return [
            Evidence(
                detector=self.name,
                risk_type=risk_type,
                message=f"stage classifier flagged content: {label}",
                score=score,
                snippet="[stage classifier result]",
                field_path=(
                    "$.text"
                    if request.source_type
                    in {SourceType.USER_PROMPT, SourceType.MODEL_OUTPUT}
                    else "$.content"
                ),
                step_id=str(
                    request.metadata.get("step_id")
                    or self._default_step(request.source_type)
                ),
            )
        ]

    @classmethod
    def _is_self_contact_query(cls, request: GuardRequest) -> bool:
        if request.source_type != SourceType.USER_PROMPT:
            return False
        compact = re.sub(r"\s+", "", request.content).strip("?？。!！")
        return cls._SELF_CONTACT_QUERY.fullmatch(compact) is not None

    @classmethod
    def _is_clearly_benign_user_task(cls, request: GuardRequest) -> bool:
        """Suppress a known model-only false positive at a narrow boundary.

        The prompt-injection and malicious-intent detectors run separately in
        the pipeline.  This method only bypasses the character classifier for
        a complete, ordinary summary request or a constrained temporary-file
        workflow containing explicitly benign text.
        """

        if request.source_type != SourceType.USER_PROMPT:
            return False
        text = request.content.strip()
        if not text or len(text) > 320:
            return False
        if cls._BENIGN_SUMMARY_TASK.fullmatch(text) is not None:
            return True

        # A prohibition such as "不要使用 exec" is a safety constraint, not
        # an execution request. Remove only that exact clause before applying
        # the conservative risk-term exclusion below.
        risk_view = re.sub(
            r"不要(?:使用|调用)\s*exec(?:\s*工具)?(?:或其他工具)?",
            "",
            text,
            flags=re.IGNORECASE,
        )
        if (
            cls._OPERATIONAL_TASK_RISK.search(risk_view) is not None
            or cls._UNSAFE_LOCAL_PATH.search(text) is not None
        ):
            return False
        return all(
            pattern.search(text) is not None
            for pattern in (
                cls._BENIGN_FILE_OPERATION,
                cls._BENIGN_FILE_DESTINATION,
                cls._BENIGN_FILE_CONTENT,
            )
        )

    @staticmethod
    def _fallback_type(source_type: SourceType) -> RiskType:
        if source_type == SourceType.USER_PROMPT:
            return RiskType.DIRECT_PROMPT_INJECTION
        if source_type == SourceType.MODEL_OUTPUT:
            return RiskType.HARMFUL_OR_OFFENSIVE_CONTENT
        return RiskType.INDIRECT_PROMPT_INJECTION

    @staticmethod
    def _default_step(source_type: SourceType) -> str:
        if source_type == SourceType.USER_PROMPT:
            return "user-input"
        if source_type == SourceType.MODEL_OUTPUT:
            return "model-output"
        return "environment-observation"
