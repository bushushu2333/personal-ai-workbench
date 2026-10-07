"""Build this explicitly selected demo board; never invoked by the server."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent.parent))
from workbench.sources import SourcesService


def build(root=ROOT):
    root = Path(root)
    items = []
    for path in sorted((root / 'tasks-data').glob('*.md')):
        if path.is_symlink():
            raise ValueError('示例生成器不读取软链接')
        item = SourcesService._parse_task(path)
        if item['id'] != path.stem or item['parent']:
            raise ValueError('示例生成器使用与文件名一致的 id，且仅支持平级任务')
        item['blocker'] = '\n'.join(item.pop('blockers'))
        item['subtitle'] = '虚构示例'
        item['strategy'] = []
        items.append(item)
    payload = json.dumps(items, ensure_ascii=False).replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')
    template = (root / 'template.html').read_text(encoding='utf-8')
    if template.count('__TASK_DATA__') != 1:
        raise ValueError('示例模板标记不唯一')
    html = template.replace('__TASK_DATA__', payload)
    (root / 'index.html').write_text(html, encoding='utf-8')
    return len(items)


if __name__ == '__main__':
    print('已生成 %d 个示例任务。' % build())
