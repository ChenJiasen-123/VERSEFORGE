import unittest
import json
from unittest.mock import patch
from experiments.classical_expression.protocol import blind_payload,validate_plan,review

class ExpressionProtocolTests(unittest.TestCase):
    def test_adopted_revision_serializes_without_cycle(self):
        from experiments.classical_expression.run import execute
        original={'title':'原','lines':['甲']*4};revised={'title':'改','lines':['乙']*4}
        class Client:
            def __init__(self,*a):self.n=0
            def complete(self,*a,**kw):
                self.n+=1;return {'content':json.dumps(original if self.n==1 else revised)}
        bad={'data':{'decision':'revise','gap':'缺口','device_risks':[]}}
        good={'data':{'decision':'keep','gap':'','device_risks':[]}}
        with patch('experiments.classical_expression.run.Adapter',Client),patch('experiments.classical_expression.run.plan',return_value={'data':{'options':[{}],'selected':0}}),patch('experiments.classical_expression.run.check',return_value=[]),patch('experiments.classical_expression.run._metrical_target_and_report',return_value=({}, {'status':'pass'})),patch('experiments.classical_expression.run.safe_review',return_value={'confirmed':True,'violations':[]}),patch('experiments.classical_expression.run.review',side_effect=[bad,good]):
            row=execute({'prompt':'题','genre':'qijue','pattern':'ping_rhyme'},'策略',None,'x')
        self.assertTrue(row['rounds'][0]['adopted'])
        self.assertEqual(json.loads(json.dumps(row))['workflow']['poem']['title'],'改')

    def test_rpe_validator_success_is_empty_error_list(self):
        row={k:'具体内容' for k in ('experience','movement','perspective','device','risk')}
        self.assertEqual(validate_plan({'options':[row,row,row],'selected':0}),[])

    def test_reader_receives_no_intention(self):
        poem={'title':'题','lines':['一行'],'intention':'secret','strategy':'secret'}
        self.assertEqual(set(blind_payload('题目',poem)['poem']),{'title','lines'})

    def test_three_distinct_slots_required(self):
        with self.assertRaises(ValueError):validate_plan({'options':[],'selected':0})

    def test_invented_evidence_rejected(self):
        class Fake:
            def call_json(self,**kw):
                return kw['validator']({'reading':'x','movement':'x','gap':'','device_risks':[],
                    'decision':'keep','evidence':[{'quote':'不存在','role':'x'}]}),{}
        with self.assertRaises(ValueError):review('题',{'title':'题','lines':['一行']},Fake())

if __name__=='__main__':unittest.main()
