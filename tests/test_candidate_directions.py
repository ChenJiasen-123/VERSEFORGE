import unittest
from dataclasses import replace
from unittest.mock import patch
from poetry_agent.core import Task
from poetry_agent.client import MockClient
from poetry_agent.candidates import compose_candidates

class DirectionTests(unittest.TestCase):
    @patch('poetry_agent.candidates.compose',side_effect=[{'poem':{'lines':['甲']},'issues':[]},{'poem':{'lines':['乙']},'issues':[]}])
    def test_confirmed_candidate_precedes_known_violation(self,compose):
        reports=iter([{'confirmed':False,'violations':[{'problem':'缺失'}]},{'confirmed':True}])
        r=compose_candidates(Task('题'),MockClient(),count=2,candidate_evaluator=lambda _:next(reports))
        self.assertEqual(r['selected_candidate'],2)
    @patch('poetry_agent.candidates.compose',side_effect=[{'poem':{'lines':['甲']},'issues':[]},{'poem':{'lines':['乙']},'issues':[]}])
    def test_distinct_directions_share_constraints(self,compose):
        task=Task('题','modern',12)
        tasks=[replace(task,extra_requirements='方向一'),replace(task,extra_requirements='方向二')]
        r=compose_candidates(task,MockClient(),count=2,candidate_tasks=tasks)
        self.assertEqual([c.args[0].extra_requirements for c in compose.call_args_list],['方向一','方向二'])
        self.assertEqual(len(r['candidate_runs']),2)

    def test_direction_cannot_change_line_limit(self):
        task=Task('题','modern',12)
        with self.assertRaises(ValueError):compose_candidates(task,MockClient(),count=2,candidate_tasks=[task,replace(task,max_lines=20)])
