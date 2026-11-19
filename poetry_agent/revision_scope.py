"""Mechanical edit limits; no claim about preservation of meaning or quality."""
from difflib import SequenceMatcher


def limits(lines):
    characters = sum(map(len, lines))
    return {
        'protocol': 'local-edit-0.1',
        'max_lines': len(lines),
        'max_changed_lines': max(1, len(lines) // 3),
        'max_body_characters': characters + min(12, max(2, (characters + 9) // 10)),
        'instruction': '局部修订：遵守行数、改动行数及总字符上限；其他行逐字保留。标题不计入。改动范围不证明原意或美感得到保留。',
    }


def inspect_revision(before, after):
    policy = limits(before)
    changes = []
    for kind, start, end, new_start, new_end in SequenceMatcher(
            None, before, after, autojunk=False).get_opcodes():
        if kind != 'equal':
            changes.append({'kind': kind, 'before_slice': [start, end],
                            'after_slice': [new_start, new_end],
                            'changed_lines': max(end - start, new_end - new_start)})
    changed = sum(item['changed_lines'] for item in changes)
    characters = sum(map(len, after))
    issues = []
    if len(after) > policy['max_lines']:
        issues.append('局部修订不得增加正文行数')
    if changed > policy['max_changed_lines']:
        issues.append(f"局部修订改动{changed}行，超过{policy['max_changed_lines']}行上限")
    if characters > policy['max_body_characters']:
        issues.append(f"局部修订正文{characters}字符，超过{policy['max_body_characters']}字符上限")
    return {'limits': policy, 'changed_lines': changed, 'body_characters': characters,
            'changes': changes, 'slice_convention': 'zero_based_half_open',
            'issues': issues, 'status': 'passed' if not issues else 'failed',
            'meaning_preservation_verified': False}
