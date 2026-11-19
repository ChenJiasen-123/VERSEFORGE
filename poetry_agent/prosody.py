"""Conservative rule evaluation. Readings must come from a named historical source.

Multiple readings are unresolved, never silently selected to fit a template.
This engine does not supply or certify a complete lexicon or poem pattern.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Reading:
    tone: str
    rhyme: str
    source: str

    def __post_init__(self):
        if self.tone not in ('P', 'Z') or not self.rhyme or not self.source:
            raise ValueError('Reading requires P/Z, rhyme group, and source')


def validate(lines, tones, rhyme_positions, lexicon, rule_source, contextual_readings=None):
    """Positions are zero-based (line, character); X means unconstrained tone.

    Input lines contain only poetic characters, without punctuation. Returns
    pass/failed/unknown for the supplied rules only, never overall 合律.
    """
    if not rule_source or not tones or any(set(t) - set('PZX') for t in tones):
        raise ValueError('An attributed valid tone pattern is required')
    if any(not 0 <= i < len(tones) or not 0 <= j < len(tones[i]) for i, j in rhyme_positions):
        raise ValueError('Rhyme position outside pattern')
    findings = []
    if len(lines) != len(tones) or any(len(a) != len(b) for a, b in zip(lines, tones)):
        return {'status': 'failed', 'rule_source': rule_source,
                'findings': [{'kind': 'shape', 'status': 'failed'}], 'scope': 'supplied_rules_only'}
    resolved = {}
    for i, (line, pattern) in enumerate(zip(lines, tones)):
        for j, (char, expected) in enumerate(zip(line, pattern)):
            overrides = contextual_readings or {}
            readings = set(overrides.get((i, j), lexicon.get(char, ())))
            candidates = {(r.tone, r.rhyme) for r in readings}
            item = {'line': i + 1, 'character': j + 1, 'text': char,
                    'expected_tone': expected, 'sources': sorted({r.source for r in readings})}
            item['reading_basis'] = 'context_review' if (i, j) in overrides else 'web_table'
            if expected == 'X':
                # No tone requirement here; this is not a resolved reading.
                rhyme_candidates = {rhyme for tone, rhyme in candidates}
                if len(rhyme_candidates) == 1:
                    resolved[(i, j)] = next(iter(rhyme_candidates))
                item.update(kind='tone', status='not_required', reading_resolved=False,
                            attested_tones=sorted({tone for tone, rhyme in candidates}))
                findings.append(item)
                continue
            tone_candidates = {tone for tone, rhyme in candidates}
            rhyme_candidates = {rhyme for tone, rhyme in candidates}
            if len(tone_candidates) != 1:
                item.update(status='unknown', kind='missing_reading' if not candidates else 'ambiguous_reading')
            else:
                tone = next(iter(tone_candidates))
                if len(rhyme_candidates) == 1:
                    resolved[(i, j)] = next(iter(rhyme_candidates))
                item.update(actual_tone=tone, rhyme_candidates=sorted(rhyme_candidates), kind='tone',
                            status='pass' if expected in ('X', tone) else 'failed')
            findings.append(item)
    groups = [resolved.get(pos) for pos in rhyme_positions]
    rhyme_status = 'unknown' if len(groups) < 2 or None in groups else ('pass' if len(set(groups)) == 1 else 'failed')
    findings.append({'kind': 'rhyme', 'status': rhyme_status, 'groups': groups,
                     'positions': [
                         {'line': i + 1, 'character': j + 1, 'text': lines[i][j],
                          'resolved_group': resolved.get((i, j))}
                         for i, j in rhyme_positions]})
    statuses = {x['status'] for x in findings}
    return {'status': 'failed' if 'failed' in statuses else ('unknown' if 'unknown' in statuses else 'pass'),
            'rule_source': rule_source, 'findings': findings, 'scope': 'supplied_rules_only'}
