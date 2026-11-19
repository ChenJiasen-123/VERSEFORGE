"""Observable character-level facts, not prosody, syntax parsing, or quality scores."""
import unicodedata


def inspect_structure(lines):
    lengths, endings, phrases = [], [], {}
    for index, line in enumerate(lines, 1):
        visible = [c for c in line if not c.isspace() and not unicodedata.category(c).startswith('P')]
        lengths.append({'line': index, 'nonspace_nonpunctuation_characters': len(visible)})
        endings.append({'line': index, 'last_character': visible[-1] if visible else None})
        for width in range(2, min(8, len(line)) + 1):
            for start in range(len(line) - width + 1):
                fragment = line[start:start + width]
                if all(c.isalnum() for c in fragment):
                    phrases.setdefault(fragment, set()).add(index)
    repeated = [(s, positions) for s, positions in phrases.items() if len(positions) > 1]
    repeated.sort(key=lambda x: (-len(x[0]), x[0]))
    kept = []
    for fragment, positions in repeated:
        if any(fragment in item['fragment'] and positions == set(item['lines']) for item in kept):
            continue
        kept.append({'fragment': fragment, 'lines': sorted(positions)})
        if len(kept) == 12:
            break
    return {'line_lengths': lengths, 'line_end_characters': endings,
            'cross_line_literal_repetitions': kept,
            'scope': 'character_level_observations_only',
            'limitations': ['重复仅检索2—8字连续片段，最多列12项，不是分词或完整穷举',
                            '字数不等于音步，末字相同不认证押韵，未执行语法分析',
                            '这些事实不构成文学质量或音韵美分数']}
