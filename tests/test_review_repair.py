import json
import unittest
from poetry_agent.aesthetics import review,parse_review_response

class Client:
    def __init__(self,rows):self.rows=iter(rows);self.calls=0
    def complete(self,*args,**kwargs):
        self.calls+=1;return {'content':json.dumps(next(self.rows),ensure_ascii=False)}

class ReviewRepairTests(unittest.TestCase):
    def test_one_redundant_closer_is_normalized_but_other_trailing_content_rejected(self):
        row={'decision':'keep','preserve':'原有效果','problem':'可能太直白','suggestion':'','tradeoff':'','keep_reason':'原文成立','quote':'灯亮着'}
        raw=json.dumps(row,ensure_ascii=False)
        poem={'title':'灯','lines':['灯亮着']}
        r=parse_review_response({'content':raw+'}'},poem,{'genre':'qijue'})
        self.assertTrue(r['redundant_closing_brace_removed'])
        for suffix in ('解释','{}','}}'):
            with self.assertRaises(ValueError):parse_review_response({'content':raw+suffix},poem,{'genre':'qijue'})
    def test_single_wrapped_basis_is_validated_after_unwrapping(self):
        row={'decision':'keep','preserve':'原有效果','problem':'可能太直白','suggestion':'','tradeoff':'','keep_reason':'原文成立','quote':'灯亮着',
             'text_sound':{'quote':'灯亮着','mechanism':'灯亮着重复','semantic_effect':'延续','uncertainty':'未必有意'}}
        c=Client([row,{'sound_basis':[{'kind':'literal_repeat','fragment':'灯亮着','occurrence_count':2}]}])
        r=review({'title':'灯','lines':['灯亮着','灯亮着']},{'genre':'modern'},c,30)
        self.assertTrue(r['schema_repair_used'])
    def test_missing_quote_is_repaired_and_revalidated(self):
        row={'decision':'keep','preserve':'原有效果','problem':'可能太直白','suggestion':'','tradeoff':'','keep_reason':'原文成立'}
        fixed={'quote':'灯还亮着'}
        c=Client([row,fixed]);r=review({'title':'灯','lines':['灯还亮着']},{'genre':'qijue'},c,30)
        self.assertTrue(r['schema_repair_used']);self.assertEqual(c.calls,2)

    def test_repair_cannot_change_decision(self):
        row={'decision':'keep','preserve':'原有效果','problem':'可能太直白','suggestion':'','tradeoff':'','keep_reason':'原文成立'}
        c=Client([row,{**row,'decision':'revise','quote':'灯还亮着','suggestion':'改句','tradeoff':'代价'}])
        with self.assertRaisesRegex(ValueError,'改变审读判断'):
            review({'title':'灯','lines':['灯还亮着']},{'genre':'qijue'},c,30)
