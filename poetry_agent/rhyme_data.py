"""Bibliographic membership lookup. Partial excerpts cannot resolve readings."""
import json
import hashlib
import re
from pathlib import Path
from functools import lru_cache
from .prosody import Reading, validate
from .glyphs import with_glyph_candidates,SHA256 as GLYPH_SHA256
from .qijue_profiles import specification
from .variant_notes import variant_note


@lru_cache(maxsize=1)
def historical_lexicon():
    raw=(Path(__file__).parent/'data/pingshui-excerpts.json').read_bytes()
    data = json.loads(raw)
    lexicon = {}
    for group in data['groups']:
        for char in group['characters']:
            lexicon.setdefault(char, []).append(Reading(group['tone'], group['name'], data['source']))
    supplemental_raw=(Path(__file__).parent/'data/historical-supplements.json').read_bytes()
    supplements=json.loads(supplemental_raw)
    for entry in supplements['entries']:
        lexicon.setdefault(entry['character'],[]).append(Reading(entry['tone'],entry['rhyme'],entry['source']))
    result=with_glyph_candidates(lexicon)
    result.provenance={'main_sha256':hashlib.sha256(raw).hexdigest(),
                       'supplements_sha256':hashlib.sha256(supplemental_raw).hexdigest(),
                       'glyph_dictionary_sha256':GLYPH_SHA256,
                       'complete_reading_inventory':False}
    return result


def lookup_excerpt(character):
    if not isinstance(character, str) or len(character) != 1:
        raise ValueError('Expected one character')
    path = Path(__file__).parent / 'data' / 'pingshui-excerpts.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    lexicon = historical_lexicon()
    return {'character': character, 'memberships': [
        {'tone': tone, 'rhyme': rhyme} for tone, rhyme in sorted({
            (r.tone, r.rhyme) for r in lexicon.get(character, ())})], 'source': data['source'],
        'glyph_evidence': lexicon.glyph_evidence.get(character),
        'reading_resolved': False, 'coverage': 'partial',
        'membership_sources':[{'tone':r.tone,'rhyme':r.rhyme,'source':r.source} for r in lexicon.get(character,())],
        'supplemental_variant_note': variant_note(character),
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
                            '不改写原稿；字形候选有独立来源，一对多、多音及缺字仍待核']}
    if profile:
        target = specification(profile)
        lexicon = historical_lexicon()
        normalized = [''.join(re.findall(r'[\u4e00-\u9fff]', line)) for line in lines]
        result['basic_target_check'] = validate(normalized, target['tones'],
            [(i - 1, 6) for i in target['rhyme_lines_1based']], lexicon, target['source'])
        result['basic_target_check']['scope'] = 'selected_basic_target_against_web_main_table'
        result['limitations'][0] = '只核所选基本谱与网页主表；语境音义、异文及其他合法变格未认证'
    return result
