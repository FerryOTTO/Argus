import fnmatch

# 测试路径匹配
p1 = 'C:\\Users\\admin\\'
pat = 'C:\\Users\\admin\\*'
print('fnmatch result:', fnmatch.fnmatch(p1, pat))
print('depth:', p1.count('\\') + p1.count('/'))

# 测试不带尾部反斜杠
p2 = 'C:\\Users\\admin'
pat2 = 'C:\\Users\\admin\\*'
print('fnmatch without trailing slash:', fnmatch.fnmatch(p2, pat2))

# 测试实际文件路径
p3 = 'C:\\Users\\admin\\test.txt'
print('fnmatch file:', fnmatch.fnmatch(p3, pat))
