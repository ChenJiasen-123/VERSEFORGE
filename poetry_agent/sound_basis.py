"""Validate narrow textual facts; never certify syntax, sound, or beauty."""
import unicodedata


def validate_basis(lines, quote, basis):
    if not isinstance(basis, dict):
        raise ValueError('文本声音依据缺失或无效')
    kind = basis.get('kind')
    if kind == 'interpretation':
        reason = basis.get('why_unverified')
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError('文本声音解释须说明未验证范围')
        return {'kind': kind, 'status': 'not_program_verified', 'why_unverified': reason}
    if kind == 'literal_repeat':
        fragment, claimed = basis.get('fragment'), basis.get('occurrence_count')
        if (not isinstance(fragment, str) or not 2 <= len(fragment) <= 8
                or not all(c.isalnum() for c in fragment) or type(claimed) is not int or claimed < 2
                or fragment not in ''.join(quote.splitlines())):
            raise ValueError('文本重复依据无效')
        stream = ''.join(lines)
        starts = [i for i in range(len(stream) - len(fragment) + 1) if stream.startswith(fragment, i)]
        if claimed != len(starts):
            raise ValueError('文本重复次数与原文不一致')
        return {'kind': kind, 'status': 'literal_fact_verified', 'fragment': fragment,
                'occurrence_count': len(starts), 'character_offsets_zero_based': starts,
                'scope': 'overlapping_literal_spans_line_breaks_removed_only'}
    if kind == 'line_pair':
        first, second = basis.get('first_line'), basis.get('second_line')
        adjacent = basis.get('is_next_line')
        relation = basis.get('length_relation')
        if (type(first) is not int or type(second) is not int or first == second
                or not 1 <= first <= len(lines) or not 1 <= second <= len(lines)
                or type(adjacent) is not bool):
            raise ValueError('文本行位依据无效')
        if adjacent != (second == first + 1):
            raise ValueError('文本相邻关系与原文不一致')
        if quote not in lines[first - 1] and quote not in lines[second - 1]:
            raise ValueError('文本行位依据未包含所引原文')
        def length(text):
            return sum(not c.isspace() and not unicodedata.category(c).startswith('P') for c in text)
        lengths = [length(lines[i-1]) for i in (first, second)]
        actual = 'equal' if lengths[0] == lengths[1] else 'first_longer' if lengths[0] > lengths[1] else 'first_shorter'
        if relation not in ('not_claimed', actual):
            raise ValueError('文本字数关系与原文不一致')
        return {'kind': kind, 'status': 'literal_fact_verified', 'first_line': first,
                'second_line': second, 'is_next_line': adjacent,
                'nonspace_nonpunctuation_lengths': lengths, 'actual_length_relation': actual,
                'scope': 'character_counts_not_sentence_length_or_metrical_feet'}
    raise ValueError('文本声音依据类型无效')
