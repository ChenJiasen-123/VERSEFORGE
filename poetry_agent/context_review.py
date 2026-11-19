"""Apply attributed, position-specific readings only to an identical poem body."""
import hashlib
import json
from .prosody import Reading, validate
from .rhyme_data import historical_lexicon
from .qijue_profiles import specification


def body_hash(lines):
    return hashlib.sha256(json.dumps(lines, ensure_ascii=False).encode('utf-8')).hexdigest()


def apply_review(poem, profile, ledger):
    if ledger.get('body_sha256') != body_hash(poem['lines']):
        raise ValueError('读音复核与当前诗稿不一致，不能复用')
    if ledger.get('reviewer_kind') not in ('assistant', 'human'):
        raise ValueError('须说明复核身份')
    import re
    lines = [''.join(re.findall(r'[\u4e00-\u9fff]', line)) for line in poem['lines']]
    overrides = {}
    for decision in ledger['decisions']:
        i, j = decision['line'] - 1, decision['position'] - 1
        if not 0 <= i < len(lines) or not 0 <= j < len(lines[i]) or lines[i][j] != decision['character']:
            raise ValueError('复核字位不一致')
        if (i, j) in overrides or not decision.get('sense') or not decision.get('rationale'):
            raise ValueError('复核须有独立字位、义项和理由')
        overrides[(i, j)] = [Reading(decision['tone'], decision['rhyme'], decision['source'])]
    target = specification(profile)
    report = validate(lines, target['tones'], [(i-1, 6) for i in target['rhyme_lines_1based']],
                      historical_lexicon(), target['source'], overrides)
    return {'basic_target_check': report, 'reviewer_kind': ledger['reviewer_kind'],
            'scope': 'exact_poem_and_selected_basic_target', 'overall_literary_quality_verified': False,
            'limitations': ['读音判断由具名复核记录提供，程序不独立认证其字书解释', '不覆盖全部合法变格或原创性']}
