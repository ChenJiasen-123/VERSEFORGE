import json
import unittest
from poetry_agent.narrative_review import review_narrative

class Client:
    def __init__(self,rows):self.rows=rows
    def complete(self,*args,**kwargs):return {'content':json.dumps({'issues':self.rows})}

class NarrativeTests(unittest.TestCase):
    def test_two_quotes_are_bound_to_their_lines(self):
        row={'kind':'ambiguity','line_a':1,'quote_a':'三楼','line_b':2,'quote_b':'不住三楼','problem':'楼层指向','alternative_reading':'第二人可能在另一楼层，但正文未明确'}
        r=review_narrative('题',{'lines':['来到三楼','他说不住三楼']},Client([row]))
        self.assertFalse(r['semantics_verified'])
        row['quote_b']='从未搬家'
        with self.assertRaises(ValueError):review_narrative('题',{'lines':['来到三楼','他说不住三楼']},Client([row]))

    def test_empty_report_does_not_certify_semantics(self):
        self.assertFalse(review_narrative('题',{'lines':['风坐下来']},Client([]))['semantics_verified'])
