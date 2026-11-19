"""Compare identical-target rule findings, not literary merit or final readings."""
import hashlib
import json
import re


def _hash(lines):
    return hashlib.sha256(json.dumps(lines, ensure_ascii=False).encode('utf-8')).hexdigest()


def _index(lines, report):
    normalized = [''.join(re.findall(r'[\u4e00-\u9fff]', line)) for line in lines]
    result = {}
    for finding in report['findings']:
        check = finding.get('check', 'meter')
        if finding['kind'] == 'shape':
            return None
        if finding['kind'] == 'rhyme':
            key = (check, 'rhyme', tuple((p['line'], p['character']) for p in finding['positions']))
        elif 'line' in finding and 'character' in finding:
            i, j = finding['line'] - 1, finding['character'] - 1
            if not (0 <= i < len(normalized) and 0 <= j < len(normalized[i])
                    and normalized[i][j] == finding['text']):
                raise ValueError('格律变化记录与诗稿字位不一致')
            key = (check, 'position', i, j, finding['expected_tone'])
        else:
            continue
        if key in result:
            raise ValueError('格律变化记录有重复检查项')
        result[key] = finding
    return result


def compare_meter(before_lines, after_lines, before, after):
    result = {'protocol': 'meter-transition-0.1', 'before_body_sha256': _hash(before_lines),
              'after_body_sha256': _hash(after_lines), 'literary_quality_verified': False}
    a, b = _index(before_lines, before), _index(after_lines, after)
    if a is None or b is None or before['rule_source'] != after['rule_source'] or a.keys() != b.keys():
        return {**result, 'applicable': False, 'reason': 'shape_or_target_not_comparable'}
    categories = {name: [] for name in ('fixed_failures', 'remaining_failures', 'failures_now_unknown',
                  'new_failures', 'passed_checks_lost', 'newly_resolved_checks')}
    for key, old in a.items():
        new = b[key]
        item = {'check': old.get('check', 'meter'), 'kind': key[1],
                'before_status': old['status'], 'after_status': new['status']}
        if key[1] == 'position':
            item.update(line=old['line'], character=old['character'], before_text=old['text'],
                        after_text=new['text'], expected_tone=old['expected_tone'])
        else:
            item.update(before_positions=old['positions'], after_positions=new['positions'])
        old_status, new_status = old['status'], new['status']
        if old_status == 'failed':
            name = {'pass': 'fixed_failures', 'failed': 'remaining_failures',
                    'unknown': 'failures_now_unknown'}.get(new_status)
            if name:
                categories[name].append(item)
        if old_status != 'failed' and new_status == 'failed':
            categories['new_failures'].append(item)
        if old_status == 'pass' and new_status != 'pass':
            categories['passed_checks_lost'].append(item)
        if old_status == 'unknown' and new_status == 'pass':
            categories['newly_resolved_checks'].append(item)
    return {**result, 'applicable': True, **categories,
            'counts': {key: len(value) for key, value in categories.items()},
            'instruction': '先核对修复是否命中原问题，兼顾新错误与已通过位置的退步。failed变unknown不算修好；unknown不等于错误。允许必要的语义重组，每稿仍查全篇；这些变化不证明诗意或完整格律。'}
