"""Apply attributed, position-specific readings only to an identical poem body."""
import hashlib
import json
from .prosody import Reading, validate
from .rhyme_data import historical_lexicon
from .qijue_profiles import specification
from .wujue import specification as wujue_specification
from .ci import specification as ci_specification
from .cilin import rhyme_evidence


def body_hash(lines):
    return hashlib.sha256(json.dumps(lines, ensure_ascii=False).encode('utf-8')).hexdigest()


def apply_review(poem, profile, ledger, *, genre='qijue'):
    if genre not in ('qijue', 'wujue', 'ci'):
        raise ValueError('读音复核仅支持五言律绝、七绝与指定词谱')
    if ledger.get('genre', 'qijue') != genre:
        raise ValueError('复核体裁不一致；五言律绝与词记录须显式声明genre')
    if ledger.get('body_sha256') != body_hash(poem['lines']):
        raise ValueError('读音复核与当前诗稿不一致，不能复用')
    if ledger.get('reviewer_kind') not in ('assistant', 'human'):
        raise ValueError('须说明复核身份')
    import re
    lines = [''.join(re.findall(r'[\u4e00-\u9fff]', line)) for line in poem['lines']]
    target = (ci_specification(profile) if genre == 'ci' else
              wujue_specification(profile) if genre == 'wujue' else specification(profile))
    ci_feet = {(i-1, target['line_lengths'][i-1]-1) for i in target['rhyme_lines_1based']} if genre == 'ci' else set()
    overrides, ci_overrides = {}, {}
    for decision in ledger['decisions']:
        i, j = decision['line'] - 1, decision['position'] - 1
        if not 0 <= i < len(lines) or not 0 <= j < len(lines[i]) or lines[i][j] != decision['character']:
            raise ValueError('复核字位不一致')
        if (i, j) in overrides or not decision.get('sense') or not decision.get('rationale'):
            raise ValueError('复核须有独立字位、义项和理由')
        overrides[(i, j)] = [Reading(decision['tone'], decision['rhyme'], decision['source'])]
        if 'ci_rhyme_part' in decision:
            part = decision['ci_rhyme_part']
            source = decision.get('ci_rhyme_source')
            if ((i, j) not in ci_feet or type(part) is not int or not 1 <= part <= 19
                    or not isinstance(source, str) or not source.strip()):
                raise ValueError('词韵归部须指定实际韵脚、有效部号及独立来源')
            ci_overrides[(i, j)] = [Reading(decision['tone'], f'詞林第{part}部', source)]
    if genre == 'ci':
        tone_report = validate(lines, target['tones'], [], historical_lexicon(), target['source'], overrides)
        tone_report['findings'] = [f for f in tone_report['findings'] if f['kind'] != 'rhyme']
        tone_statuses = {f['status'] for f in tone_report['findings']}
        tone_report['status'] = 'failed' if 'failed' in tone_statuses else 'unknown' if 'unknown' in tone_statuses else 'pass'
        rhyme_report = rhyme_evidence(lines, target, ci_overrides)
        findings = ([{**f, 'check': 'tone'} for f in tone_report['findings']]
                    + [{**f, 'check': 'rhyme'} for f in rhyme_report['findings']])
        statuses = {tone_report['status'], rhyme_report['status']}
        report = {'status': 'failed' if 'failed' in statuses else 'unknown' if 'unknown' in statuses else 'pass',
                  'rule_source': target['source'] + ' ; ' + rhyme_report['rule_source'],
                  'findings': findings, 'scope': 'named_ci_tones_and_cilin_rhyme_with_exact_body_review'}
        return {'basic_target_check': report, 'tone_check': tone_report, 'rhyme_check': rhyme_report,
                'reviewer_kind': ledger['reviewer_kind'], 'genre': genre, 'profile': profile,
                'body_sha256': body_hash(poem['lines']), 'scope': 'exact_poem_and_selected_ci_target',
                'overall_literary_quality_verified': False,
                'limitations': ['平仄与词林归部分别核验；不从平水韵目自动推词林部',
                    '核音判断由具名记录提供，程序不独立认证字书解释或所有合法变格']}
    last = len(target['tones'][0]) - 1
    report = validate(lines, target['tones'], [(i-1, last) for i in target['rhyme_lines_1based']],
                      historical_lexicon(), target['source'], overrides)
    return {'basic_target_check': report, 'reviewer_kind': ledger['reviewer_kind'],
            'genre': genre, 'profile': profile, 'body_sha256': body_hash(poem['lines']),
            'scope': 'exact_poem_and_selected_basic_target', 'overall_literary_quality_verified': False,
            'limitations': ['读音判断由具名复核记录提供，程序不独立认证其字书解释', '不覆盖全部合法变格或原创性']}
