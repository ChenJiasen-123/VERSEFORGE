"""Import a saved, line-numbered web snapshot, excluding marked 詞 appendices.

This imports memberships only; it does not establish unique contextual readings.
"""
import hashlib
import json
import re
from pathlib import Path


def is_cjk_text(text):
    return bool(text) and all(0x3400 <= ord(c) <= 0x9fff or 0xf900 <= ord(c) <= 0xfaff
                             or 0x20000 <= ord(c) <= 0x323af for c in text)


def extract(text):
    groups, current = [], None
    previous_line = None
    for raw in text.splitlines():
        numbered = re.match(r'^L(\d+):', raw)
        if not numbered:
            continue
        number = int(numbered.group(1))
        if previous_line is not None and number != previous_line + 1:
            current = None  # Missing browser lines may contain a new group heading.
        previous_line = number
        line = re.sub(r'^L\d+:\s*', '', raw).strip()
        if line.startswith('此作品在全世界'):
            if current and current['name'] == '入聲十七洽' and current['characters']:
                groups.append(current)
            current = None
            break
        if re.fullmatch(r'(上平聲|下平聲|上聲|去聲|入聲)[一二三四五六七八九十]+[\u3400-\u9fff]', line):
            if current and current['characters']:
                groups.append(current)
            current = {'name': line, 'tone': 'P' if line.startswith(('上平', '下平')) else 'Z', 'characters': ''}
        elif current and line.startswith('〖詞〗'):
            continue
        elif current and is_cjk_text(line):
            current['characters'] += line
        elif current and line and not line.startswith(('〖', '[', '##', '【')):
            raise ValueError('Unrecognized content inside rhyme group; inspect snapshot before importing')
    # Final group may be cut off by the browser. Require the next heading.
    return groups


if __name__ == '__main__':
    root = Path(__file__).parent
    snapshots = sorted((root / 'tmp').glob('pingshui-web-*.txt'))
    groups_by_name = {}
    hashes = {}
    for snapshot in snapshots:
        text = snapshot.read_text(encoding='utf-8')
        hashes[snapshot.name] = hashlib.sha256(snapshot.read_bytes()).hexdigest()
        for group in extract(text):
            if group['name'] in groups_by_name and groups_by_name[group['name']] != group:
                raise ValueError('Conflicting snapshots')
            groups_by_name[group['name']] = group
    groups = list(groups_by_name.values())
    data = {'source': 'https://zh.wikisource.org/wiki/平水韻', 'accessed': '2026-11-18',
            'snapshot_sha256': hashes,
            'status': 'web_main_table_memberships_not_contextual_readings',
            'group_count': len(groups),
            'revision_url': 'https://zh.wikisource.org/w/index.php?title=平水韻&oldid=8264804',
            'limitations': ['浏览文本快照局部覆盖，未核原书影印', '不含标记〖詞〗附列',
                            '不得将单一已见归部当成唯一读音', '不作简繁自动转换'], 'groups': groups}
    (root / 'poetry_agent/data/pingshui-excerpts.json').write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Imported groups:', len(groups))
