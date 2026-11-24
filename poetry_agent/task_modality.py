"""Narrow correction of verbatim optional clauses, not semantic paraphrase proof."""
import re

def preserve_optional_clauses(prompt,requirements):
    clauses=[x.strip() for x in re.split(r'[；。\n]',prompt) if x.strip()]
    replacements={}
    for clause in clauses:
        match=re.fullmatch(r'(?:不必|无需|无须)(.+)',clause)
        if not match:
            continue
        content=match.group(1).strip()
        # Do not erase an independently explicit prohibition elsewhere.
        if any(other in ('不得'+content,'禁止'+content,'不能'+content,'不许'+content) for other in clauses):
            continue
        for mistaken in ('不'+content,'不得'+content,'禁止'+content,'不能'+content,'不许'+content):
            replacements[mistaken]=clause
    return [replacements.get(value.strip().rstrip('。；'),value) for value in requirements]
