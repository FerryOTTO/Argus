import sys
sys.path.insert(0, 'E:\\tiaozhanbei\\MAC\\v1\\auth-gateway-extracted')

from auth_gateway import _resource_required_level_tree, _match_pattern, _store

# 重新加载规则
_store.reload()

# 打印所有资源规则
print("=== 资源规则 ===")
for pattern, level, mode in _store.resources:
    print(f"  {pattern} | {level} | {mode}")

print()

# 测试匹配
test_paths = [
    'C:\\Users\\admin\\',
    'C:\\Users\\admin\\test.txt',
    'C:\\Users\\',
]

for path in test_paths:
    level = _resource_required_level_tree(path)
    print(f"路径: {path}")
    print(f"  所需等级: {level}")

    # 检查哪些规则匹配
    for pattern, lvl, mode in _store.resources:
        if _match_pattern(pattern, path):
            print(f"    匹配: {pattern} | {lvl} | {mode}")
    print()
