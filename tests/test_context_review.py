import unittest
from poetry_agent.context_review import apply_review, body_hash


class ContextReviewTests(unittest.TestCase):
    def test_revision_cannot_inherit_previous_poem_reading_decisions(self):
        ledger = {'body_sha256': body_hash(['東' * 7] * 4), 'reviewer_kind': 'assistant', 'decisions': []}
        with self.assertRaises(ValueError):
            apply_review({'lines': ['同' * 7] * 4}, 'ping_rhyme', ledger)

    def test_matching_hash_does_not_allow_wrong_character(self):
        lines = ['東' * 7] * 4
        ledger = {'body_sha256': body_hash(lines), 'reviewer_kind': 'assistant',
                  'decisions': [{'line': 1, 'position': 1, 'character': '同'}]}
        with self.assertRaises(ValueError):
            apply_review({'lines': lines}, 'ping_rhyme', ledger)
