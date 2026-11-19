"""Extract main-character memberships from contiguous attributed web snapshots."""
import hashlib
import json
import re
import unicodedata
from pathlib import Path

SOURCE = 'https://zh.wikisource.org/w/index.php?title=詞林正韻&oldid=12977287'
NUMBERS = ['一','二','三','四','五','六','七','八','九','十','十一','十二','十三','十四','十五','十六','十七','十八','十九']


def main_characters(body):
    stack, result = [], []
    pairs = {'（': '）', '(': ')', '[': ']', '【': '】'}
    for char in body:
        if char in pairs:
            stack.append(pairs[char])
        elif char in pairs.values():
            if not stack or stack.pop() != char:
                raise ValueError('Unbalanced annotation')
        elif not stack:
            if char.isspace():
                continue
            if not unicodedata.name(char, '').startswith(('CJK UNIFIED IDEOGRAPH', 'CJK COMPATIBILITY IDEOGRAPH')):
                raise ValueError('Unrecognized main-list content')
            result.append(char)
    if stack:
        raise ValueError('Unclosed annotation')
    # Rendered traditional conversion appears to expand 宏 into 巨集 here.
    # Omit this suspicious token rather than silently correcting the source.
    return ''.join(result).replace('巨集', '')


def extract(paths):
    lines, sources = {}, []
    for path in paths:
        raw = path.read_bytes()
        sources.append({'snapshot_file': path.name, 'sha256': hashlib.sha256(raw).hexdigest()})
        for number, text in re.findall(r'^L(\d+): ?(.*)$', raw.decode('utf-8'), re.M):
            index = int(number)
            if index in lines and lines[index] != text:
                raise ValueError('Conflicting overlapping snapshots')
            lines[index] = text
    if not all(i in lines for i in range(170, 579)):
        raise ValueError('Incomplete source line coverage')
    if 'oldid=12977287' not in lines.get(588, ''):
        raise ValueError('Snapshot revision does not match the pinned source')
    groups, part, tone, found = [], None, None, []
    for number in range(170, 579):
        line = lines[number]
        heading = re.fullmatch(r'## 第(.+)部', line)
        if heading:
            part = NUMBERS.index(heading[1]) + 1
            found.append(part)
            tone = None
        elif line.startswith('### '):
            tone = 'P' if line.startswith('### 平聲') else 'Z' if line.startswith(('### 仄聲', '### 入聲')) else None
            if tone is None:
                raise ValueError('Unknown tone heading')
        elif line.startswith('〖'):
            match = re.fullmatch(r'〖([^〗]+)〗(.+)', line)
            if not match or part is None or tone is None:
                raise ValueError('Unattributed character list')
            groups.append({'part': part, 'tone': tone, 'subgroup': match[1],
                           'characters': ''.join(dict.fromkeys(main_characters(match[2]))),
                           'source_line': number, 'annotated_body': match[2]})
    if found != list(range(1, 20)):
        raise ValueError('Expected all nineteen parts in order')
    expected_sections = {(part, tone) for part in range(1, 20)
                         for tone in (('P', 'Z') if part <= 14 else ('Z',))}
    if len(groups) != 115 or {(g['part'], g['tone']) for g in groups} != expected_sections:
        raise ValueError('Incomplete subgroup coverage for fixed web revision')
    return {'source': SOURCE, 'snapshot_inputs': sources, 'groups': groups,
            'scope': 'web_main_character_memberships_not_contextual_readings',
            'limitations': ['网页转录未核原书影印，不认证字形、完整性或每项读音',
                '括注保留供审读但不自动展开异体、字义或通部备注',
                '半韵按网页逐字归部，不合并整个平水韵目',
                '网页疑似字形转换巨集暂排除，不自动改作宏',
                '归部仍需语境辨音；不自动简繁转换']}


if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    paths = sorted((root/'research/source-snapshots').glob('cilin-web-*.txt'))
    data = extract(paths)
    out = root/'poetry_agent/data/cilin-main.json'
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'parts': len({x['part'] for x in data['groups']}), 'subgroups': len(data['groups'])}))
