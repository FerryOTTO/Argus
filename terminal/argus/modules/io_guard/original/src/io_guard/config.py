from __future__ import annotations


PROMPT_INJECTION_PATTERNS: list[tuple[str, str, float]] = [
    (
        r"\bignore\s+(?:all\s+)?(?:previous|prior|above)"
        r"(?:\s+(?:instructions?|rules?|prompts?))?\b",
        "ignore previous instructions",
        0.90,
    ),
    (r"disregard (all )?(previous|prior|above) (instructions|rules)", "disregard previous instructions", 0.90),
    (r"reveal (the )?(system prompt|developer message|hidden instruction)", "reveal hidden prompt", 0.95),
    (r"print (the )?(system prompt|developer message|hidden instruction)", "print hidden prompt", 0.92),
    (r"bypass (the )?(policy|permission|guardrail|restriction)", "bypass policy", 0.88),
    (r"you are now (dan|developer mode|unrestricted)", "role jailbreak", 0.85),
    (r"act as (dan|an unrestricted ai|a jailbroken ai)", "role jailbreak", 0.82),
    (
        r"忽略.*(之前|以上|上面|系统).*(指令|命令|规则|约束)",
        "忽略之前指令",
        0.92,
    ),
    (
        r"(?:忽略|无视|不理会|不要理会|忘掉|放弃|覆盖|撤销|作废)"
        r".{0,24}(?:之前|此前|先前|以上|上述|上面|原有|现有|系统)"
        r".{0,24}(?:指令|命令|规则|要求|约束)",
        "无视或覆盖既有指令",
        0.92,
    ),
    (
        r"(?:将|把).{0,24}(?:视为|当作)"
        r".{0,8}(?:系统|开发者|最高优先级)(?:指令|消息|命令)",
        "伪造高优先级指令",
        0.93,
    ),
    (
        r"(?:告诉|告知|显示|展示|给出|提供|透露|输出|打印)"
        r"(?:我|用户)?(?:你(?:的)?|当前(?:的)?|完整(?:的)?|原始(?:的)?|隐藏(?:的)?)"
        r".*(系统提示词?|系统指令|开发者消息|隐藏指令)",
        "请求披露隐藏提示",
        0.95,
    ),
    (r"泄露.*(系统提示|系统指令|开发者消息|隐藏指令)", "泄露系统提示", 0.95),
    (r"输出.*(系统提示|系统指令|开发者消息|隐藏指令)", "输出系统提示", 0.92),
    (r"绕过.*(权限|策略|限制|审核|安全)", "绕过权限或策略", 0.88),
    (r"你现在是.*(无限制|无约束|开发者模式|DAN)", "角色扮演越狱", 0.85),
    (
        r"(?:从现在(?:开始|起))?你.{0,8}"
        r"(?:不受|摆脱|取消|移除|关闭).{0,16}"
        r"(?:安全规则|安全策略|安全限制|政策限制|规则限制|约束)",
        "角色扮演越狱",
        0.92,
    ),
    (
        r"(?:把|将).{0,20}(?:前面|之前|此前|原来|当前)"
        r".{0,16}(?:任务|要求|指令|命令).{0,10}"
        r"(?:作废|取消|撤销|忽略|覆盖)",
        "无视或覆盖既有指令",
        0.92,
    ),
    (
        r"(?:输出|显示|泄露|提供).{0,24}"
        r"(?:系统|后台|内部).{0,16}"
        r"(?:密码|口令|密钥|令牌|验证码|凭证)",
        "请求泄露系统凭证",
        0.94,
    ),
    (r"(?:(?:进入|启用|切换到|开启)\s*DAN(?:\s*模式)?|DAN\s*模式)", "角色扮演越狱", 0.85),
    (r"不要遵守.*(安全|策略|规则|限制)", "要求不遵守安全规则", 0.86),
]


OUTPUT_LEAKAGE_PATTERNS: list[tuple[str, str, float, str]] = [
    (r"(?<!\d)1[3-9]\d{9}(?!\d)", "Chinese mobile phone", 0.75, "[PHONE]"),
    (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "email address", 0.65, "[EMAIL]"),
    (
        r"((?:(?:facebook|meta)\s+)?"
        r"(?:security|verification|one[- ]time|otp)\s+"
        r"(?:code|password|passcode|pin)\s*[:：]?\s*)"
        r"(?<!\d)\d{4,8}(?!\d)",
        "one-time verification code",
        0.88,
        r"\1[OTP]",
    ),
    (
        r"((?:短信|登录|安全|身份验证|二次验证|双因素|一次性)?"
        r"(?:验证码|校验码|动态码|口令)\s*(?:为|是)?\s*[:：]?\s*)"
        r"(?<!\d)\d{4,8}(?!\d)",
        "短信或登录验证码",
        0.88,
        r"\1[OTP]",
    ),
    (r"(?<!\d)\d{17}[\dXx](?!\d)", "Chinese citizen ID", 0.88, "[ID_CARD]"),
    (r"\b(?:sk|pk|ak)-[A-Za-z0-9_\-]{16,}\b", "API key", 0.95, "[API_KEY]"),
    (r"\b[A-Za-z0-9_\-]{24,}\.[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{20,}\b", "JWT-like token", 0.90, "[TOKEN]"),
    (r"(system prompt|developer message|hidden instruction)\s*[:：]", "system prompt leakage", 0.92, "[HIDDEN_PROMPT]"),
    (r"(系统提示|系统指令|开发者消息|隐藏指令)\s*[:：]", "系统提示泄露", 0.92, "[HIDDEN_PROMPT]"),
]


CLASSIFICATION_LEVELS: dict[str, int] = {
    "公开": 0,
    "内部": 1,
    "秘密": 2,
    "机密": 3,
    "绝密": 4,
    "public": 0,
    "internal": 1,
    "secret": 2,
    "confidential": 3,
    "top secret": 4,
}
