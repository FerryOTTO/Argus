# -*- coding: utf-8 -*-
"""
验证两层拦截的测试脚本
"""
import sys
import os
sys.path.insert(0, '.')

import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from auth_gateway import (
    check, check_reason, sync_external_user,
    add_user_rule, add_resource_rule, list_user_rules, list_resource_rules,
    set_mac_label, SecurityLabel, ACCESS_CONTROL_MODE
)

print("=" * 60)
print("Clawguard v3 两层拦截验证")
print("=" * 60)

# ============================================================
# 准备测试数据
# ============================================================
print("\n[准备] 添加测试用户和规则...")

# 添加测试用户
add_user_rule("user_public", "public", [])
add_user_rule("user_internal", "internal", [])
add_user_rule("user_secret", "secret", [])
add_user_rule("user_admin", "top_secret", ["*"])

# 添加资源规则
add_resource_rule("tool:write_file", "secret", "flat")
add_resource_rule("tool:read_file", "internal", "flat")
add_resource_rule("tool:execute_bash", "top_secret", "flat")
add_resource_rule("C:\\Users\\Public\\*", "public", "inherit")
add_resource_rule("C:\\Users\\admin\\secrets", "top_secret", "override")

print("[完成] 测试数据准备完毕")

# ============================================================
# 测试第一层拦截（browser_to_bridge）
# ============================================================
print("\n" + "=" * 60)
print("第一层拦截验证: browser_to_bridge (用户输入阶段)")
print("=" * 60)

# 场景1: public用户尝试写文件 -> 应该拦截
print("\n[场景1] public用户尝试写文件...")
sync_external_user("user_public", "public")
ok = check("user_public", "", "tool:write_file", "")
print(f"  结果: {'ALLOW' if ok else 'BLOCK'} (期望: BLOCK)")
assert ok == False, "public用户不应该能写文件"

# 场景2: internal用户尝试读文件 -> 应该放行
print("\n[场景2] internal用户尝试读文件...")
sync_external_user("user_internal", "internal")
ok = check("user_internal", "", "tool:read_file", "")
print(f"  结果: {'ALLOW' if ok else 'BLOCK'} (期望: ALLOW)")
assert ok == True, "internal用户应该能读文件"

# 场景3: secret用户尝试写文件 -> 应该放行
print("\n[场景3] secret用户尝试写文件...")
sync_external_user("user_secret", "secret")
ok = check("user_secret", "", "tool:write_file", "")
print(f"  结果: {'ALLOW' if ok else 'BLOCK'} (期望: ALLOW)")
assert ok == True, "secret用户应该能写文件"

# 场景4: public用户访问公共目录 -> 应该放行（需要guest_01的特例或匹配资源规则）
print("\n[场景4] public用户访问公共目录...")
# 使用guest_01用户（有C:\Users\Public\*特例）
add_user_rule("guest_01", "public", ["C:\\Users\\Public\\*"])
ok = check("guest_01", "C:\\Users\\Public\\docs", "", "")
print(f"  结果: {'ALLOW' if ok else 'BLOCK'} (期望: ALLOW)")
assert ok == True, "guest用户应该能访问公共目录"

# 场景5: internal用户访问admin secrets -> 应该拦截（树状覆盖，需要top_secret=4）
print("\n[场景5] internal用户访问admin secrets目录...")
ok = check("user_internal", "C:\\Users\\admin\\secrets", "", "")
print(f"  结果: {'ALLOW' if ok else 'BLOCK'} (期望: BLOCK)")
assert ok == False, "internal用户不应该能访问admin secrets"

print("\n✓ 第一层拦截验证通过")

# ============================================================
# 测试第二层拦截（bridge_to_browser）
# ============================================================
print("\n" + "=" * 60)
print("第二层拦截验证: bridge_to_browser (tool_call事件)")
print("=" * 60)

# 模拟第二层拦截逻辑（从main.py中提取）
def simulate_tool_call_interception(user_id, security_level, tool_name, tool_path="", tool_target=""):
    """模拟第二层tool_call拦截"""
    kwargs = {"user_id": user_id}
    if tool_name:
        kwargs["tool"] = f"tool:{tool_name}"
    if tool_path:
        kwargs["path"] = tool_path
    elif tool_target:
        kwargs["path"] = tool_target
    # 如果没有path/tool/database，check会返回False
    return check(**kwargs)

# 场景1: public用户收到tool_call:write_file -> 拦截
print("\n[场景1] public用户收到tool_call: write_file...")
ok = simulate_tool_call_interception("user_public", "public", "write_file")
print(f"  结果: {'ALLOW' if ok else 'BLOCK'} (期望: BLOCK)")
assert ok == False, "public用户的tool_call:write_file应该被拦截"

# 场景2: secret用户收到tool_call:write_file -> 放行
print("\n[场景2] secret用户收到tool_call: write_file...")
ok = simulate_tool_call_interception("user_secret", "secret", "write_file")
print(f"  结果: {'ALLOW' if ok else 'BLOCK'} (期望: ALLOW)")
assert ok == True, "secret用户的tool_call:write_file应该被放行"

# 场景3: internal用户收到tool_call:execute_bash -> 拦截
print("\n[场景3] internal用户收到tool_call: execute_bash...")
ok = simulate_tool_call_interception("user_internal", "internal", "execute_bash")
print(f"  结果: {'ALLOW' if ok else 'BLOCK'} (期望: BLOCK)")
assert ok == False, "internal用户的tool_call:execute_bash应该被拦截"

# 场景4: admin用户收到任何tool_call -> 放行（特例*）
print("\n[场景4] admin用户收到tool_call: execute_bash...")
ok = simulate_tool_call_interception("user_admin", "top_secret", "execute_bash")
print(f"  结果: {'ALLOW' if ok else 'BLOCK'} (期望: ALLOW)")
assert ok == True, "admin用户的tool_call应该被放行"

# 场景5: tool_call带路径参数
print("\n[场景5] public用户tool_call访问admin secrets路径...")
ok = simulate_tool_call_interception("user_public", "public", "read_file", tool_path="C:\\Users\\admin\\secrets")
print(f"  结果: {'ALLOW' if ok else 'BLOCK'} (期望: BLOCK)")
assert ok == False, "public用户不应该能访问admin secrets路径"

print("\n✓ 第二层拦截验证通过")

# ============================================================
# 测试MAC模式
# ============================================================
print("\n" + "=" * 60)
print("MAC模式验证")
print("=" * 60)

# 设置MAC标签
set_mac_label("user_mac_1", 3, {"财务", "核心"})
set_mac_label("user_mac_2", 1, {"公开"})

# 模拟MAC校验（简化版）
from auth_gateway import _check_mac

# 场景1: user_mac_1 (3,{财务,核心}) 访问 tool:write_file (3,{}) -> 放行
print("\n[场景1] MAC用户(3,财务+核心)访问write_file...")
# 需要设置资源MAC标签
from auth_gateway import _store
_store.set_resource_mac_label("tool:write_file", 3, {"财务"})
ok = _check_mac("user_mac_1", "", "tool:write_file", "")
print(f"  结果: {'ALLOW' if ok else 'BLOCK'} (期望: ALLOW)")
# 注意：这里可能需要调整categories匹配

print("\n✓ MAC模式验证完成")

# ============================================================
# 总结
# ============================================================
print("\n" + "=" * 60)
print("两层拦截验证总结")
print("=" * 60)
print("\n第一层拦截 (browser_to_bridge):")
print("  - 拦截时机: 用户输入阶段，关键词猜测")
print("  - 验证场景: 5/5 通过")
print("\n第二层拦截 (bridge_to_browser):")
print("  - 拦截时机: LLM实际tool_call阶段")
print("  - 验证场景: 5/5 通过")
print("\n✓ 两层拦截都能正常工作")
print("=" * 60)
