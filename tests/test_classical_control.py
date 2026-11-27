import unittest
from unittest.mock import patch
import control_classical_evolution as control

class MultiCandidateControlTests(unittest.TestCase):
    def test_control_changes_only_candidate_count_in_existing_studio(self):
        with patch.object(control,'ORIGINAL_STUDIO',return_value={'status':'fixture'}) as studio:
            result=control.three_candidates('题',candidate_count=1,independent_editor=True,
                total_budget_seconds=900,total_max_calls=45,preference='同一典源')
        self.assertEqual(result,{'status':'fixture'})
        self.assertEqual(studio.call_args.args,('题',))
        self.assertEqual(studio.call_args.kwargs,{'candidate_count':3,'independent_editor':True,
            'total_budget_seconds':900,'total_max_calls':45,'preference':'同一典源'})

if __name__=='__main__':unittest.main()
