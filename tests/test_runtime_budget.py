import unittest
from unittest.mock import patch
from poetry_agent.runtime_budget import BudgetedClient

class Client:
    model='fixture'
    def complete(self,*args,**kwargs):self.settings=kwargs;return {'content':'{}'}

class BudgetTests(unittest.TestCase):
    def test_remaining_deadline_clamps_every_request(self):
        c=Client()
        with patch('poetry_agent.runtime_budget.time.monotonic',side_effect=[10,17]):
            b=BudgetedClient(c,10,2);b.complete('s','u',timeout=60)
        self.assertEqual(c.settings['timeout'],3)

    def test_call_ceiling_prevents_next_request(self):
        b=BudgetedClient(Client(),10,1);b.complete('s','u')
        with self.assertRaisesRegex(RuntimeError,'预算'):b.complete('s','u')

    def test_expired_deadline_does_not_contact_client(self):
        with patch('poetry_agent.runtime_budget.time.monotonic',side_effect=[0,11]):
            b=BudgetedClient(Client(),10)
            with self.assertRaises(RuntimeError):b.complete('s','u')
        self.assertEqual(b.calls,0)
