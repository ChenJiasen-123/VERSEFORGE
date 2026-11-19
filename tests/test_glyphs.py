import unittest
from unittest.mock import patch
from poetry_agent.glyphs import with_glyph_candidates, SOURCE
from poetry_agent.prosody import Reading, validate
from poetry_agent.rhyme_data import historical_lexicon, lookup_excerpt


def tone(char, expected, lexicon=None, overrides=None):
    return validate([char], [expected], [], historical_lexicon() if lexicon is None else lexicon,
                    'test target', overrides)['findings'][0]


class GlyphTests(unittest.TestCase):
    def test_common_simplified_forms_reach_source_without_rewriting_text(self):
        for char, target in [('灯', '燈'), ('门', '門'), ('风', '風')]:
            result = tone(char, 'P')
            self.assertEqual(result['status'], 'pass')
            self.assertEqual(result['text'], char)
            self.assertEqual(result['glyph_evidence']['candidates'], [target])
            self.assertEqual(result['glyph_evidence']['source'], SOURCE)
            self.assertFalse(result['glyph_evidence']['sense_selected'])

    def test_multiple_tones_are_not_chosen_to_fit_either_target(self):
        for expected in ('P', 'Z'):
            result = tone('干', expected)
            self.assertEqual(result['status'], 'unknown')
            self.assertIn('乾', result['glyph_evidence']['candidates'])
            self.assertIn('幹', result['glyph_evidence']['candidates'])

    def test_agreeing_candidates_can_check_tone_without_selecting_sense(self):
        result = tone('发', 'Z')
        self.assertEqual(result['status'], 'pass')
        self.assertEqual(set(result['glyph_evidence']['candidates']), {'發', '髮'})
        self.assertFalse(result['glyph_evidence']['sense_selected'])

    def test_partial_candidate_coverage_cannot_pass_or_fail_from_known_subset(self):
        base = {'發': [Reading('P', 'group', 'test source')]}
        lexicon = with_glyph_candidates(base)
        for expected in ('P', 'Z'):
            result = tone('发', expected, lexicon)
            self.assertEqual(result['status'], 'unknown')
            self.assertEqual(result['glyph_evidence']['missing_candidates'], ['髮'])
        self.assertNotIn('发', base)

    def test_same_tone_different_rhyme_does_not_resolve_rhyme(self):
        lexicon = with_glyph_candidates({'發': [Reading('P', 'one', 'test')],
                                        '髮': [Reading('P', 'two', 'test')]})
        result = validate(['发发'], ['PP'], [(0, 0), (0, 1)], lexicon, 'test')
        self.assertEqual(result['findings'][0]['status'], 'pass')
        self.assertEqual(result['findings'][-1]['status'], 'unknown')

    def test_explicit_position_reading_can_resolve_ambiguous_glyph(self):
        result = tone('干', 'P', overrides={(0, 0): [Reading('P', 'group', 'named test reading')]})
        self.assertEqual(result['status'], 'pass')
        self.assertEqual(result['reading_basis'], 'context_review')

    def test_lookup_labels_derived_membership_and_unknown_character_stays_missing(self):
        self.assertTrue(lookup_excerpt('灯')['glyph_evidence'])
        self.assertFalse(lookup_excerpt('灯')['reading_resolved'])
        self.assertEqual(tone('🙂', 'P')['kind'], 'missing_reading')

    def test_changed_dictionary_fails_closed(self):
        with patch('poetry_agent.glyphs.Path.read_bytes', return_value=b'changed'):
            with self.assertRaises(ValueError): with_glyph_candidates({})
