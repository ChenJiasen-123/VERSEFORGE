import unittest
from prepare_revision_data import make_record


class RevisionDataTests(unittest.TestCase):
    def test_variants_share_partition_and_are_not_auto_labels(self):
        a = make_record('题', {'lines': ['甲']}, {'lines': ['乙']}, 'source', 'hash')
        b = make_record('题', {'lines': ['甲']}, {'lines': ['丙']}, 'source2', 'hash2')
        self.assertEqual(a['family_id'], b['family_id'])
        self.assertEqual(a['partition'], b['partition'])
        self.assertNotEqual(a['id'], b['id'])
        self.assertIsNone(a['preference'])
        self.assertFalse(a['approved_for_training'])
