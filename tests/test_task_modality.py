import unittest
from poetry_agent.task_modality import preserve_optional_clauses

class ModalityTests(unittest.TestCase):
    def test_actual_convenience_store_failure(self):
        p='写重逢。不必解释过去的关系；允许温暖，不要求反转。'
        self.assertEqual(preserve_optional_clauses(p,['不解释过去的关系']),['不必解释过去的关系'])

    def test_explicit_prohibition_is_retained(self):
        self.assertEqual(preserve_optional_clauses('不得解释过去的关系。',['不得解释过去的关系']),['不得解释过去的关系'])

    def test_optional_and_explicit_prohibition_conflict_not_silently_resolved(self):
        p='不必解释过去的关系；不得解释过去的关系。'
        self.assertEqual(preserve_optional_clauses(p,['不得解释过去的关系']),['不得解释过去的关系'])

    def test_unrelated_negative_and_paraphrase_are_untouched(self):
        self.assertEqual(preserve_optional_clauses('不必解释过去的关系。',['不超过20行','不得透露身份']),['不超过20行','不得透露身份'])

    def test_no_need_does_not_become_ban(self):
        self.assertEqual(preserve_optional_clauses('无需押韵。',['禁止押韵']),['无需押韵'])
