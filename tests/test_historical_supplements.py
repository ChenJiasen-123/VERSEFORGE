import unittest
from poetry_agent.rhyme_data import lookup_excerpt,historical_lexicon
from poetry_agent.prosody import validate

class SupplementTests(unittest.TestCase):
    def test_xian_retains_multiple_attested_readings_and_sources(self):
        r=lookup_excerpt('先');groups={x['rhyme'] for x in r['memberships']}
        self.assertTrue({'下平聲一先','去聲十七霰','上聲十六銑'}<=groups)
        self.assertTrue(any('sou-yun' in x['source'] for x in r['membership_sources']))

    def test_missing_candidate_correction_does_not_auto_select_ping(self):
        r=validate(['先'],['P'],[],historical_lexicon(),'test')
        self.assertEqual(r['findings'][0]['status'],'unknown')
