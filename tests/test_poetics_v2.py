import json
import unittest
from experiments.classical_expression.poetics_v2 import generate,reader_payload,audit

class PoeticsTests(unittest.TestCase):
    def test_reader_has_no_author_explanation(self):
        p={'title':'题','lines':['诗句'],'intention':'secret','claim':'secret'}
        self.assertNotIn('secret',json.dumps(reader_payload('题',p,[])))
    def test_generation_preserves_task_and_meter(self):
        seen=[]
        class Fake:
            def complete(self,system,user,**kwargs):
                seen.append(json.loads(user))
                return {'content':json.dumps({'title':'题','lines':['一句']})}
        generate('原题禁词要求',Fake(),genre='qijue',max_lines=4,meter_target={'tones':['PPZZZPP']})
        self.assertEqual(seen[0]['prompt'],'原题禁词要求')
        self.assertEqual(seen[0]['metrical_target']['tones'],['PPZZZPP'])
    def test_multiple_supported_sources_allowed(self):
        poem={'title':'题','lines':['甲乙丙丁']};cards=[{'id':'one'},{'id':'two'}]
        class Fake:
            def call_json(self,**kw):
                data={'reading':'共同作用','references':[{'card_id':i,'quote':q,'function':'作用','direction':'顺用'} for i,q in [('one','甲乙'),('two','丙丁')]],'issues':[],'decision':'keep'}
                self_errors=kw['validator'](data)
                assert not self_errors
                return data,{}
        self.assertEqual(len(audit('题',poem,cards,Fake())['data']['references']),2)

if __name__=='__main__':unittest.main()
