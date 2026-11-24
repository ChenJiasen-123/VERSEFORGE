import unittest
from poetry_agent.studio import meter_revision_guard

def report(char,status):
    return {'target':{'tones':['P']},'report':{'rule_source':'test','findings':[{'kind':'tone','status':status,'line':1,'character':1,'text':char,'expected_tone':'P'}]}}

class MeterGuardTests(unittest.TestCase):
    def compare(self,a,b):
        return meter_revision_guard({'lines':['春']},{'lines':['夜']},report('春',a),report('夜',b))

    def test_pass_cannot_become_failed_or_unknown(self):
        for status in ('failed','unknown'):self.assertFalse(self.compare('pass',status)['accepted'])

    def test_failed_becoming_unknown_is_not_repair(self):
        self.assertFalse(self.compare('failed','unknown')['accepted'])

    def test_real_repair_accepted_without_certifying_entire_poem(self):
        r=self.compare('failed','pass');self.assertTrue(r['accepted']);self.assertFalse(r['overall_meter_certified'])

    def test_modern_no_target_unchanged(self):
        self.assertTrue(meter_revision_guard({}, {},None,None)['accepted'])
