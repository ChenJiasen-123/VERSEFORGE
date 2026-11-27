import json
import tempfile
import unittest
from pathlib import Path
from experiments.classical_expression.audit import audit

class AuditTests(unittest.TestCase):
    def test_incomplete_run_is_not_complete_or_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            status,packet,mapping=audit(Path(directory))
        self.assertFalse(status['automated_evidence_complete'])
        self.assertEqual(len(status['missing_held_out']),18)
        self.assertFalse(any(status['formal_acceptance'].values()))
        self.assertEqual(packet,[])

    def test_packet_excludes_strategy_and_model_judgment(self):
        row={'workflow':{'poem':{'title':'题','lines':['诗句']},'checks':{
            'hard':[],'meter':[{}, {'status':'unknown'}],
            'requirements':{'confirmed':True,'violations':[]}}},
            'strategy':'SECRET_STRATEGY','planning':'SECRET_INTENTION',
            'blind':'SECRET_JUDGMENT','expression_proxy':1}
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            (folder/'C-test-01.json').write_text(json.dumps(row),encoding='utf8')
            status,packet,mapping=audit(folder)
        self.assertNotIn('SECRET',json.dumps(packet))
        self.assertNotIn('group',packet[0])
        self.assertEqual(mapping[0]['group'],'C')
        self.assertFalse(status['formal_acceptance']['C'])

if __name__=='__main__':unittest.main()
