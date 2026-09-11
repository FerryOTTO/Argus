import re

# 匹配 Windows 绝对路径: C:\foo\bar（纯 ASCII，中文处自动截断）
PATH_RE = re.compile(r'([A-Za-z]:\\[a-zA-Z0-9_.\-\\]+)', re.IGNORECASE)

# 测试各种路径
test_messages = [
    "帮我看看 C:\\Users\\admin\\ 里面有什么",
    "看看 C:\\Windows\\System32",
    "读取 C:\\Users\\admin\\Documents\\file.txt",
    "C:\\Users\\admin\\",
    "C:\\Users\\admin",
]

for msg in test_messages:
    resources = []
    for m in PATH_RE.finditer(msg):
        p = m.group(0).rstrip('.,;:!?，。；：！？')
        resources.append(p)
    print(f'消息: {msg}')
    print(f'  提取路径: {resources}')
    print()
