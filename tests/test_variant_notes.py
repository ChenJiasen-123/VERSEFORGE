import unittest
from poetry_agent.rhyme_data import lookup_excerpt

class VariantNoteTests(unittest.TestCase):
    def test_variant_evidence_does_not_select_reading(self):
        r=lookup_excerpt('暖')
        self.assertEqual(r['supplemental_variant_note']['related_character'],'煖')
        self.assertFalse(r['reading_resolved'])
        self.assertFalse(r['supplemental_variant_note']['context_selected'])
        self.assertEqual(r['memberships'],[])

    def test_unrelated_character_receives_no_variant_claim(self):
        self.assertIsNone(lookup_excerpt('中')['supplemental_variant_note'])
