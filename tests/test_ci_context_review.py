import copy
import json
import unittest
from pathlib import Path
from poetry_agent.context_review import apply_review

ROOT = Path(__file__).parents[1]
PROFILE = 'baixiang_yijiangnan_liyu'


class CiContextTests(unittest.TestCase):
    def setUp(self):
        self.poem = json.loads((ROOT/'runs/8855e36e0d544d249a33613b1a3a31ba.json').read_text(encoding='utf-8'))['poem']
        self.ledger = json.loads((ROOT/'runs/ci-rain-town-reading-ledger.json').read_text(encoding='utf-8'))

    def test_exact_poem_passes_supplied_tone_and_separate_cilin_review(self):
        result = apply_review(self.poem, PROFILE, self.ledger, genre='ci')
        self.assertEqual(result['tone_check']['status'], 'pass')
        self.assertEqual(result['rhyme_check']['status'], 'pass')
        self.assertEqual(result['basic_target_check']['status'], 'pass')
        self.assertFalse(result['overall_literary_quality_verified'])

    def test_pingshui_reading_does_not_implicitly_resolve_cilin(self):
        del self.ledger['decisions'][0]['ci_rhyme_part']
        result = apply_review(self.poem, PROFILE, self.ledger, genre='ci')
        self.assertEqual(result['tone_check']['status'], 'pass')
        self.assertEqual(result['rhyme_check']['status'], 'unknown')
        self.assertEqual(result['basic_target_check']['status'], 'unknown')

    def test_cilin_override_requires_valid_part_and_its_own_source(self):
        for part in (0, 20, True):
            ledger = copy.deepcopy(self.ledger)
            ledger['decisions'][0]['ci_rhyme_part'] = part
            with self.assertRaises(ValueError): apply_review(self.poem, PROFILE, ledger, genre='ci')
        self.ledger['decisions'][0]['ci_rhyme_source'] = ''
        with self.assertRaises(ValueError): apply_review(self.poem, PROFILE, self.ledger, genre='ci')

    def test_poem_change_and_genre_mismatch_reject_the_record(self):
        self.poem['lines'][0] += '。'
        with self.assertRaises(ValueError): apply_review(self.poem, PROFILE, self.ledger, genre='ci')
        with self.assertRaises(ValueError): apply_review(self.poem, 'ping_rhyme', self.ledger)

    def test_rhyme_pass_cannot_mask_a_wrong_tone_elsewhere(self):
        next(d for d in self.ledger['decisions'] if d['character'] == '燕')['tone'] = 'P'
        result = apply_review(self.poem, PROFILE, self.ledger, genre='ci')
        self.assertEqual(result['rhyme_check']['status'], 'pass')
        self.assertEqual(result['tone_check']['status'], 'failed')
        self.assertEqual(result['basic_target_check']['status'], 'failed')
