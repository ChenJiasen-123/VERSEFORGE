"""Named ci profile, with explicit limits on rhyme-system coverage."""
import json
import re
from pathlib import Path
from .prosody import validate
from .rhyme_data import historical_lexicon


def specification(name):
    data = json.loads((Path(__file__).parent / 'data/ci-profiles.json').read_text(encoding='utf-8'))
    if name not in data['profiles']:
        raise ValueError('不支持该词谱体')
    return {'id': name, 'source': data['source'], **data['profiles'][name]}


def check_shape(lines, name):
    profile = specification(name)
    issues = []
    if len(lines) != len(profile['line_lengths']):
        issues.append(f"该词谱体须{len(profile['line_lengths'])}句，每句单独一个lines元素")
    for i, (line, expected) in enumerate(zip(lines, profile['line_lengths']), 1):
        chars = re.sub(r'[\s，。！？；、：,.!?;:‘’“”"—…]', '', line)
        if len(chars) != expected or any(not '\u4e00' <= c <= '\u9fff' for c in chars):
            issues.append(f'词第{i}句须为{expected}个汉字（不计常见标点）')
    return issues


def evidence(lines, name):
    profile = specification(name)
    normalized = [''.join(re.findall(r'[\u4e00-\u9fff]', line)) for line in lines]
    report = validate(normalized, profile['tones'], [], historical_lexicon(), profile['source'])
    report['findings'] = [f for f in report['findings'] if f['kind'] != 'rhyme']
    statuses = {f['status'] for f in report['findings']}
    report['status'] = 'failed' if 'failed' in statuses else ('unknown' if 'unknown' in statuses else 'pass')
    report['scope'] = 'named_ci_profile_tones_against_web_main_table'
    return {'status': 'unknown', 'tone_check': report, 'rhyme_status': 'not_covered',
            'profile': name, 'limitations': profile['limitations']}
