import json
import unittest
from poetry_agent.automatic_readings import propose_readings,sense_conflict

class Client:
    def __init__(self,rows):self.rows=rows;self.payload=None
    def complete(self,system,user,**kwargs):self.payload=json.loads(user);return {'content':json.dumps({'decisions':self.rows})}

class AutomaticReadingTests(unittest.TestCase):
    def test_conflicting_compounds_cannot_be_overridden_by_model(self):
        for line in ('中奖归来','中毒未醒','中举归乡','中流矢'):
            c=Client([{'line':1,'position':1,'card_id':'zhong_inside','rationale':'强套内部'}])
            r=propose_readings({'title':'测试','lines':[line]},c)
            self.assertEqual(r['decisions'],[]);self.assertTrue(r['abstentions'][0]['veto'])

    def test_simile_is_vetoed_but_locative_is_not(self):
        self.assertTrue(sense_conflict('此影犹如故人',3,'you_still'))
        self.assertIsNone(sense_conflict('人在风雨中',5,'zhong_inside'))
    def test_source_card_is_bound_to_actual_position_and_target_hidden(self):
        c=Client([{'line':1,'position':3,'card_id':'zhong_inside','rationale':'在雨声里面'}])
        r=propose_readings({'title':'雨','lines':['雨声中']},c)
        self.assertEqual(r['decisions'][0]['tone'],'P')
        self.assertNotIn('profile',c.payload);self.assertNotIn('tone',c.payload['positions'][0]['cards'][0])

    def test_wrong_character_card_is_rejected(self):
        with self.assertRaises(ValueError):propose_readings({'title':'雨','lines':['雨声中']},Client([{'line':1,'position':3,'card_id':'nuan_warm','rationale':'测试'}]))
