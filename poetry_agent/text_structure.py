"""Observable character-level facts, not prosody, syntax parsing, or quality scores."""
import unicodedata


def literal_repetitions(lines):
    """Count overlapping spans; remove line breaks only, never punctuation."""
    stream = ''.join(lines)
    locations = [(i, j) for i, line in enumerate(lines, 1)
                 for j in range(1, len(line) + 1)]
    spans = {}
    for start in range(len(stream)):
        for width in range(2, min(8, len(stream) - start) + 1):
            fragment = stream[start:start + width]
            if all(c.isalnum() for c in fragment):
                spans.setdefault(fragment, []).append(start)
    repeated = sorted(((s, starts) for s, starts in spans.items() if len(starts) > 1),
                      key=lambda item: (-len(item[0]), item[0]))
    kept = []
    for fragment, starts in repeated:
        if any(len(starts) == len(other_starts) and
               all(any(k <= start and start + len(fragment) <= k + len(other)
                       for k in other_starts) for start in starts)
               for other, other_starts in kept):
            continue
        kept.append((fragment, starts))
        if len(kept) > 12:
            break
    return {'items': [{'fragment': fragment, 'occurrence_count': len(starts),
                      'occurrences': [{'start_line': locations[k][0],
                                       'start_character': locations[k][1],
                                       'end_line': locations[k + len(fragment) - 1][0],
                                       'end_character': locations[k + len(fragment) - 1][1]}
                                      for k in starts[:32]],
                      'occurrence_positions_truncated': len(starts) > 32}
                     for fragment, starts in kept[:12]],
            'truncated': len(kept) > 12,
            'scope': 'literal_character_stream_with_line_breaks_removed_only',
            'limitations': ['统计2—8字连续片段，最多12项各列32个位置；可跨分行，保留空白标点；允许重叠，不等于词或句法重复',
                            '位置按原行Unicode字符从1计；次数不评价节奏或文学质量']}


def compare_lineation(a, b):
    """Locate changed boundaries only when wording and punctuation are identical."""
    if ''.join(a) != ''.join(b):
        return {'applicable': False, 'reason': 'different_character_streams'}
    text = ''.join(a)
    def boundaries(lines):
        offset, positions = 0, []
        for line in lines[:-1]:
            offset += len(line)
            positions.append(offset)
        return positions
    a_offsets, b_offsets = boundaries(a), boundaries(b)
    changed = sorted(set(a_offsets) ^ set(b_offsets))
    return {'applicable': True, 'same_wording_and_punctuation': True,
            'a_line_count': len(a), 'b_line_count': len(b),
            'changed_boundaries': [
                {'character_offset': pos, 'break_in_a': pos in a_offsets,
                 'break_in_b': pos in b_offsets,
                 'before': text[max(0, pos - 12):pos], 'after': text[pos:pos + 12]}
                for pos in changed[:24]],
            'truncated': len(changed) > 24,
            'scope': 'literal_boundaries_not_predicted_pauses_or_quality',
            'empty_lines_present': any(not line for line in a + b)}


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
            'literal_repetition_occurrences': literal_repetitions(lines),
            'scope': 'character_level_observations_only',
            'limitations': ['重复仅检索2—8字连续片段，最多列12项，不是分词或完整穷举',
                            '字数不等于音步，末字相同不认证押韵，未执行语法分析',
                            '这些事实不构成文学质量或音韵美分数']}
