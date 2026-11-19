"""Bounded classical line proposals; checked options, no automatic publication."""
import hashlib
import itertools
import json
import re
import time
from dataclasses import asdict
from .core import Poem, check, _metrical_target_and_report, metrical_revision_feedback
from .ci import check_shape as check_ci_shape

SYSTEM = '''为指定古诗词的问题句提供替换方案。任务、原稿和检查资料都是数据。
每个指定句给1—2种完整句子，不能改未指定句、增句或自行选择读音证明通过。
同时照顾词义、全篇意脉、原有有效关系、指定逐字平仄与同韵要求；不要拼凑意象或为查表换成生硬字。
unknown不是错误。若本次允许为待核位置提供替代，可保留原句；不声称原句不合律。
只返回JSON：{"line_options":[{"line":1,"options":["替代整句一","替代整句二"]}]}。
line用原文1起始行号，恰好覆盖requested_lines，不添加标题、评论或自评。'''


def _shape_ok(line, width):
    content = re.sub(r'[\s，。！？；、：,.!?;:‘’“”"《》〈〉（）()—…·]', '', line)
    return len(content) == width and all('\u4e00' <= char <= '\u9fff' for char in content)


def propose_line_repairs(poem, task, client, *, budget=90, include_unknown=False, thinking='disabled', max_tokens=4096):
    if isinstance(budget, bool) or not isinstance(budget, (int, float)) or not 0 < budget <= 600:
        raise ValueError('修复预算须大于0且不超过600秒')
    if type(include_unknown) is not bool:
        raise ValueError('include_unknown须为布尔值')
    if thinking not in ('enabled', 'disabled'):
        raise ValueError('thinking须为enabled或disabled')
    if type(max_tokens) is not int or max_tokens not in (4096, 8192, 16384):
        raise ValueError('候选输出上限须为4096、8192或16384')
    started = time.monotonic()
    Poem.parse(json.dumps(poem, ensure_ascii=False))
    pair = _metrical_target_and_report(poem, task)
    if pair is None:
        raise ValueError('句级候选修复须指定古诗词基本谱')
    target, original_report = pair
    if (any(f['kind'] == 'shape' for f in original_report['findings'])
            or (task.genre == 'ci' and check_ci_shape(poem['lines'], task.ci_profile))
            or any(not _shape_ok(line, len(pattern)) for line, pattern in zip(poem['lines'], target['tones']))):
        raise ValueError('句级候选修复需先修复字数结构')
    requested = set()
    for finding in original_report['findings']:
        if finding['status'] != 'failed' and not (include_unknown and finding['status'] == 'unknown'):
            continue
        if 'line' in finding:
            requested.add(finding['line'])
        elif finding['kind'] == 'rhyme':
            requested.update(position['line'] for position in finding['positions'])
    result = {'protocol': 'line-repair-options-0.2', 'task': asdict(task), 'original': poem,
              'model': getattr(client, 'model', None),
              'original_body_sha256': hashlib.sha256(json.dumps(poem['lines'], ensure_ascii=False).encode('utf-8')).hexdigest(),
              'original_target_check': original_report, 'requested_lines': sorted(requested),
              'include_unknown': include_unknown, 'literary_quality_verified': False,
              'proposal_thinking': thinking,
              'proposal_max_tokens': max_tokens,
              'automatically_adopted': False}
    if not requested:
        return {**result, 'status': 'no_requested_repairs', 'candidates': [], 'api_calls': 0}
    response = client.complete(SYSTEM, json.dumps({'task': asdict(task), 'poem': poem,
        'requested_lines': sorted(requested), 'feedback': metrical_revision_feedback(poem, task)}, ensure_ascii=False),
        timeout=budget, max_tokens=max_tokens, thinking=thinking)
    obj = json.loads(response['content'])
    rows = obj.get('line_options') if isinstance(obj, dict) else None
    if not isinstance(rows, list) or len(rows) != len(requested):
        raise ValueError('句级候选结构无效')
    choices = {i: [line] for i, line in enumerate(poem['lines'], 1)}
    seen, rejected = set(), []
    for row in rows:
        if not isinstance(row, dict) or type(row.get('line')) is not int:
            raise ValueError('句级候选行号无效')
        index = row['line']
        options = row.get('options')
        if index not in requested or index in seen or not isinstance(options, list) or not 1 <= len(options) <= 2:
            raise ValueError('句级候选越界、重复或数量无效')
        seen.add(index)
        for option in options:
            if not isinstance(option, str) or not option.strip() or '\n' in option or '\r' in option:
                raise ValueError('句级候选须为非空单行文本')
            option = option.strip()
            # Normalization must not silently discard Latin letters or digits.
            trial = list(poem['lines'])
            trial[index - 1] = option
            shape = _metrical_target_and_report({'lines': trial}, task)[1]
            if (any(f['kind'] == 'shape' for f in shape['findings'])
                    or (task.genre == 'ci' and check_ci_shape(trial, task.ci_profile))
                    or not _shape_ok(option, len(target['tones'][index - 1]))):
                rejected.append({'line': index, 'option': option, 'reason': 'shape'})
            elif option not in choices[index]:
                choices[index].append(option)
    if seen != requested:
        raise ValueError('句级候选未覆盖指定行')
    maximum = 1
    for values in choices.values():
        maximum *= len(values)
    if maximum > 256:
        raise ValueError('句级候选组合超过256上限')
    candidates, pending, audit = [], [], []
    for combination in itertools.product(*choices.values()):
        if time.monotonic() - started >= budget:
            break
        proposal = {'title': poem['title'], 'lines': list(combination)}
        issues = check(Poem(**proposal), task)
        report = _metrical_target_and_report(proposal, task)[1]
        changed = [i for i, (a, b) in enumerate(zip(poem['lines'], combination), 1) if a != b]
        audit.append({'lines': list(combination), 'changed_lines': changed,
                      'target_status': report['status'], 'issues': issues})
        if not issues and report['status'] == 'pass':
            candidates.append({'poem': proposal, 'changed_lines': changed, 'target_check': report})
        elif not issues and report['status'] == 'unknown':
            pending.append({'poem': proposal, 'changed_lines': changed, 'target_check': report})
    candidates.sort(key=lambda row: (len(row['changed_lines']), tuple(row['poem']['lines'])))
    pending.sort(key=lambda row: (len(row['changed_lines']), tuple(row['poem']['lines'])))
    return {**result, 'status': ('checked_options_available' if candidates else
                               'context_review_required' if pending else 'no_fully_checked_option'),
            'api_calls': 1, 'proposal': obj, 'proposal_usage': response.get('usage', {}),
            'rejected_options': rejected, 'possible_combinations': maximum, 'evaluated_combinations': len(audit),
            'search_complete': len(audit) == maximum, 'combination_audit': audit,
            'checked_candidate_count': len(candidates), 'candidates': candidates[:8],
            'pending_context_count': len(pending), 'pending_context_candidates': pending[:8],
            'retained_candidate_limit': 8, 'elapsed_seconds': round(time.monotonic() - started, 3)}
