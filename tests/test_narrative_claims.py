import json
import unittest
from poetry_agent.narrative_claims import extract_claims

class Client:
    def __init__(self,rows):self.rows=rows
    def complete(self,*args,**kwargs):return {'content':json.dumps({'claims':self.rows})}

class ClaimTests(unittest.TestCase):
    def test_quote_must_exist_at_claimed_position(self):
        row={'line':1,'quote':'只有编号','statement':'没有文字','mode':'asserted','scope':'正文'}
        self.assertEqual(len(extract_claims({'lines':['只有编号']},Client([row]))['claims']),1)
        with self.assertRaises(ValueError):extract_claims({'lines':['附件有字']},Client([row]))

    def test_hypothesis_is_not_forced_to_asserted(self):
        row={'line':1,'quote':'假如你回来','statement':'你回来','mode':'hypothesis','scope':'假设'}
        r=extract_claims({'lines':['假如你回来']},Client([row]))
        self.assertEqual(r['claims'][0]['mode'],'hypothesis');self.assertFalse(r['interpretation_verified'])
