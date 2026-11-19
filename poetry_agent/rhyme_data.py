"""Bibliographic membership lookup. Partial excerpts cannot resolve readings."""
import json
import re
from pathlib import Path
from .prosody import Reading, validate
from .qijue_profiles import specification


def historical_lexicon():
    data = json.loads((Path(__file__).parent / 'data/pingshui-excerpts.json').read_text(encoding='utf-8'))
    lexicon = {}
    for group in data['groups']:
        for char in group['characters']:
            lexicon.setdefault(char, []).append(Reading(group['tone'], group['name'], data['source']))
    return lexicon


def lookup_excerpt(character):
    if not isinstance(character, str) or len(character) != 1:
        raise ValueError('Expected one character')
    path = Path(__file__).parent / 'data' / 'pingshui-excerpts.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    return {'character': character, 'memberships': [
        {'tone': g['tone'], 'rhyme': g['name']} for g in data['groups']
        if character in g['characters']], 'source': data['source'],
        'reading_resolved': False, 'coverage': 'partial',
        'limitations': data['limitations']}


def qijue_evidence(lines, profile=None):
    """Report attested rhyme-foot memberships without guessing a poem pattern."""
    feet = []
    tone_evidence = []
    for i, line in enumerate(lines, 1):
        chars = re.findall(r'[\u4e00-\u9fff]', line)
        if chars:
            feet.append({'line': i, **lookup_excerpt(chars[-1])})
        tone_evidence.append({'line': i, 'characters': [
            {'character': char, 'attested_tones': sorted({m['tone'] for m in lookup_excerpt(char)['memberships']}),
             'reading_resolved': False} for char in chars]})
    types = json.loads((Path(__file__).parent / 'data/qijue-line-types.json').read_text(encoding='utf-8'))
    required = [x for x in feet if x['line'] in (2, 4)]
    shared = set.intersection(*[
        {m['rhyme'] for m in x['memberships'] if m['tone'] == 'P'} for x in required
    ]) if len(required) == 2 else set()
    result = {'status': 'unknown', 'scope': 'rhyme_membership_evidence_only',
            'feet': feet, 'lines_2_4_shared_attested_ping_groups': sorted(shared),
            'tone_evidence': tone_evidence,
            'standard_line_types': types,
            'limitations': ['未指定起式及首句入韵方式，未验证平仄、粘对或拗救',
                            '归部交集不是语境读音判定，也不构成押韵通过',
                            '不自动转换简繁，缺字及多音仍需复核']}
    if profile:
        target = specification(profile)
        lexicon = historical_lexicon()
        normalized = [''.join(re.findall(r'[\u4e00-\u9fff]', line)) for line in lines]
        result['basic_target_check'] = validate(normalized, target['tones'],
            [(i - 1, 6) for i in target['rhyme_lines_1based']], lexicon, target['source'])
        result['basic_target_check']['scope'] = 'selected_basic_target_against_web_main_table'
        result['limitations'][0] = '只核所选基本谱与网页主表；语境音义、异文及其他合法变格未认证'
    return result
