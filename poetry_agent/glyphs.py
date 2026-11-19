"""Attributed character candidates, never phrase conversion or sense selection."""
import hashlib
from pathlib import Path

COMMIT = '178f05dbc5dbcedd09d4ab39d501094f4d9d8820'
SOURCE = f'https://raw.githubusercontent.com/BYVoid/OpenCC/{COMMIT}/data/dictionary/STCharacters.txt'
SHA256 = 'a0ca1601c70648cf48b33c3c6210ccbecc5c7eead4b4c3daf76587ba2c03582b'


class GlyphLexicon(dict):
    """A normal membership lookup with separately attributed glyph ambiguity."""


def with_glyph_candidates(base):
    path = Path(__file__).resolve().parents[1] / 'third_party/opencc/STCharacters.txt'
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SHA256:
        raise ValueError('字形候选字典校验失败')
    result = GlyphLexicon({char: tuple(readings) for char, readings in base.items()})
    result.glyph_evidence = {}
    for line in raw.decode('utf-8').splitlines():
        if not line or line.startswith('#'):
            continue
        key, values = line.split('\t')
        variants = list(dict.fromkeys(values.split()))
        if len(key) != 1 or any(len(char) != 1 for char in variants):
            raise ValueError('字形候选必须为单字')
        if variants == [key]:
            continue
        # Retain direct memberships too; never replace them by a preferred form.
        if key in base and key not in variants:
            variants.append(key)
        readings = tuple(sorted({reading for char in variants for reading in base.get(char, ())},
                                key=lambda r: (r.tone, r.rhyme, r.source)))
        missing = [char for char in variants if not base.get(char)]
        result[key] = readings
        result.glyph_evidence[key] = {
            'source': SOURCE, 'sha256': SHA256, 'candidates': variants,
            'missing_candidates': missing,
            'candidate_memberships': [
                {'character': char, 'memberships': [
                    {'tone': reading.tone, 'rhyme': reading.rhyme, 'source': reading.source}
                    for reading in sorted(set(base.get(char, ())), key=lambda r: (r.tone, r.rhyme, r.source))]}
                for char in variants],
            'sense_selected': False,
        }
    return result
