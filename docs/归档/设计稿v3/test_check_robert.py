import sys
sys.path.insert(0, 'E:\\tiaozhanbei\\MAC\\v1\\auth-gateway-extracted')
from auth_gateway import check, check_reason, _store

# 重新加载规则
_store.reload()

# 检查用户等级
print('robertwright level:', _store.get_user_level('robertwright'))

# 测试 check
path = 'C:\\Users\\admin\\'
result = check('robertwright', path, '', '')
print('check result:', result)

# 测试 check_reason
ok, reason = check_reason('robertwright', path, '', '')
print('check_reason:', ok, reason)
