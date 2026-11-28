import unittest
from classical_diction import validate_diction, passes_diction

class DictionTests(unittest.TestCase):
    def make(self,status='clear',importance=None):
        return {'status':status,'reading':[{'passage_id':'p1','meaning':'句意'}],
            'issues':[{'passage_id':'p1','importance':importance,'problem':'缺口'}] if importance else [],'reason':'依据'}

    def test_local_doubt_does_not_erase_readable_poem_but_central_gap_blocks_even_optimistic_status(self):
        self.assertTrue(passes_diction(validate_diction(self.make('uncertain','local'),{'p1':'诗句'})))
        self.assertFalse(passes_diction(validate_diction(self.make('clear','central'),{'p1':'诗句'})))
        self.assertFalse(passes_diction(validate_diction(self.make('broken'),{'p1':'诗句'})))

    def test_reading_must_cover_actual_body_and_cannot_cite_title_or_unknown_line(self):
        for invalid in ([],self.make()):
            with self.assertRaises(ValueError):validate_diction(invalid,{'p1':'诗句','p2':'第二句'})
        row=self.make();row['issues']=[{'passage_id':'p0','importance':'central','problem':'标题'}]
        with self.assertRaises(ValueError):validate_diction(row,{'p1':'诗句'})

if __name__=='__main__':unittest.main()
