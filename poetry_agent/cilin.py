"""Cilin web-main-table rhyme evidence, independent from Pingshui rhyme groups."""
import json
from pathlib import Path
from functools import lru_cache
from .prosody import Reading, validate
from .glyphs import with_glyph_candidates


@lru_cache(maxsize=1)
def lexicon():
    data = json.loads((Path(__file__).parent/'data/cilin-main.json').read_text(encoding='utf-8'))
    result = {}
    for group in data['groups']:
        for char in group['characters']:
            result.setdefault(char, []).append(Reading(group['tone'], f"詞林第{group['part']}部", data['source']))
    return with_glyph_candidates(result), data['source']


def rhyme_evidence(lines, profile, contextual_readings=None):
    data, source = lexicon()
    positions = [(i-1, profile['line_lengths'][i-1]-1) for i in profile['rhyme_lines_1based']]
    tones = [['X'] * width for width in profile['line_lengths']]
    for i, j in positions:
        tones[i][j] = profile['rhyme_tone']
    report = validate(lines, [''.join(row) for row in tones], positions, data, source, contextual_readings)
    report['findings'] = [f for f in report['findings'] if f.get('kind') in ('shape', 'rhyme')
                          or (f.get('line', 0)-1, f.get('character', 0)-1) in positions]
    report['scope'] = 'named_ci_rhyme_feet_against_cilin_web_main_table'
    return report
