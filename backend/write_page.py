import sys

content = sys.stdin.read()
with open(r'frontend\src\app\page.tsx', 'w', encoding='utf-8') as f:
    f.write(content)
print('Wrote page.tsx successfully, bytes:', len(content))
