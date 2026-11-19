import json
import re
import tempfile
import unittest
from pathlib import Path
from import_cilin_snapshot import extract, main_characters
from poetry_agent.cilin import rhyme_evidence
from poetry_agent.ci import specification
from poetry_agent.core import Task, Poem, check, metrical_revision_feedback

ROOT = Path(__file__).parents[1]
PROFILE = 'baixiang_yijiangnan_liyu'


def with_feet(feet):
    lines = ['東' * n for n in [3, 5, 7, 7, 5]]
    for i, char in zip((1, 3, 4), feet):
        lines[i] = lines[i][:-1] + char
    return lines


class CilinTests(unittest.TestCase):
    def test_parenthetical_glosses_do_not_become_main_characters(self):
        self.assertEqual(main_characters('中（中間）冬[注釋]風'), '中冬風')
        with self.assertRaises(ValueError): main_characters('中（中間')
        with self.assertRaises(ValueError): main_characters('東*冬')

    def test_snapshot_gap_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'incomplete.txt'
            path.write_text('L170: ## 第一部\nL578: end\n', encoding='utf-8')
            with self.assertRaises(ValueError): extract([path])

    def test_extraction_is_reproducible_and_contains_nineteen_parts(self):
        paths = sorted((ROOT/'research/source-snapshots').glob('cilin-web-*.txt'))
        # Stable relative paths keep provenance identical across machines.
        generated = extract(paths)
        saved = json.loads((ROOT/'poetry_agent/data/cilin-main.json').read_text(encoding='utf-8'))
        self.assertEqual(generated, saved)
        self.assertEqual({g['part'] for g in generated['groups']}, set(range(1, 20)))

    def test_deleted_subgroup_is_rejected_despite_contiguous_lines(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = []
            for source in sorted((ROOT/'research/source-snapshots').glob('cilin-web-*.txt')):
                out = Path(folder)/source.name
                out.write_text(re.sub(r'^L178:.*$', 'L178: ', source.read_text(encoding='utf-8'), flags=re.M), encoding='utf-8')
                paths.append(out)
            with self.assertRaises(ValueError): extract(paths)

    def test_dong_and_dong_can_share_ci_part_without_merging_pingshui_groups(self):
        from poetry_agent.prosody import Reading
        # Explicit synthetic reading isolates the rhyme-system rule. Without it,
        # OpenCC's 冬/鼕 alternatives now expose a missing Cilin main-table form.
        lines = with_feet('東冬風')
        self.assertEqual(rhyme_evidence(lines, specification(PROFILE))['status'], 'unknown')
        report = rhyme_evidence(lines, specification(PROFILE),
                                {(3, 6): [Reading('P', '詞林第1部', 'test fixture: supplied winter reading')]})
        self.assertEqual(report['status'], 'pass')
        self.assertEqual(report['findings'][-1]['groups'], ['詞林第1部'] * 3)

    def test_half_rhyme_is_split_by_character(self):
        self.assertEqual(rhyme_evidence(with_feet('灰灰開'), specification(PROFILE))['status'], 'failed')

    def test_multiple_parts_are_not_picked_to_fit(self):
        self.assertEqual(rhyme_evidence(with_feet('佳佳花'), specification(PROFILE))['status'], 'unknown')

    def test_ambiguous_tone_is_not_picked_to_fit_a_ping_foot(self):
        self.assertEqual(rhyme_evidence(with_feet('中東風'), specification(PROFILE))['status'], 'unknown')

    def test_wrong_rhyme_tone_cannot_hide_behind_shared_part(self):
        self.assertEqual(rhyme_evidence(with_feet('夢東風'), specification(PROFILE))['status'], 'failed')

    def test_ci_rhyme_failure_reaches_hard_check_and_repair_feedback(self):
        lines = with_feet('灰灰開')
        task = Task('題', genre='ci', ci_profile=PROFILE)
        self.assertTrue(any('词林' in item for item in check(Poem('題', lines), task)))
        feedback = metrical_revision_feedback({'lines': lines}, task)
        self.assertTrue(any(x['kind'] == 'rhyme' and x['status'] == 'failed' for x in feedback['findings_to_review']))
