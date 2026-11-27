import unittest
from poetry_agent.reading_bridge import match_source_cards
from poetry_agent.context_review import body_hash

class BridgeTests(unittest.TestCase):
    def proposal(self,line,pinyin,sense):
        return match_source_cards({'lines':[line]},{'body_sha256':body_hash([line]),'readings':[{'id':'1-1','pinyin':pinyin,'sense':sense,'basis':line}]})
    def test_modern_fourth_tone_is_not_mapped_to_an_arbitrary_ze_reading(self):
        self.assertEqual(self.proposal('中奖','zhòng','获奖')['decisions'],[])
    def test_same_pinyin_different_sense_does_not_match(self):
        self.assertEqual(self.proposal('犹如','yóu','如同')['decisions'],[])
    def test_source_tone_requires_both_reading_and_supported_sense(self):
        r=self.proposal('犹未回','yóu','仍然；还')
        self.assertEqual(r['decisions'][0]['tone'],'P');self.assertFalse(r['context_choice_verified'])
