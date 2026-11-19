import unittest
from poetry_agent.sound_basis import validate_basis
from poetry_agent.aesthetics import failure_code


class SoundBasisTests(unittest.TestCase):
    def test_repeat_count_includes_one_line_and_cross_line_spans(self):
        for lines in (['再数一次她说再数一次'], ['再数', '一次她说再数一次']):
            r = validate_basis(lines, '再数一次', {'kind':'literal_repeat','fragment':'再数一次','occurrence_count':2})
            self.assertEqual(r['status'], 'literal_fact_verified')
            self.assertEqual(r['character_offsets_zero_based'], [0,6])
        overlap = validate_basis(['哈哈哈'], '哈哈',
            {'kind':'literal_repeat','fragment':'哈哈','occurrence_count':2})
        self.assertEqual(overlap['character_offsets_zero_based'], [0,1])

    def test_wrong_count_and_boolean_count_are_rejected(self):
        for count in (3, True):
            with self.assertRaises(ValueError) as exc:
                validate_basis(['再数一次她说再数一次'], '再数一次',
                    {'kind':'literal_repeat','fragment':'再数一次','occurrence_count':count})
            self.assertEqual(failure_code(exc.exception), 'invalid_sound_basis')

    def test_separated_line_is_not_accepted_as_next_line(self):
        basis = {'kind':'line_pair','first_line':1,'second_line':3,'is_next_line':True,'length_relation':'first_longer'}
        with self.assertRaises(ValueError): validate_basis(['推过去，推过去。','钟响了','像猫'], '推过去', basis)
        basis['is_next_line'] = False
        r = validate_basis(['推过去，推过去。','钟响了','像猫'], '推过去', basis)
        self.assertEqual(r['nonspace_nonpunctuation_lengths'], [6,2])

    def test_wrong_length_or_unrelated_quote_is_rejected(self):
        basis = {'kind':'line_pair','first_line':1,'second_line':2,'is_next_line':True,'length_relation':'equal'}
        with self.assertRaises(ValueError): validate_basis(['我，等。','雨下着。','灯'], '我', basis)
        basis['length_relation']='first_shorter'
        with self.assertRaises(ValueError): validate_basis(['我，等。','雨下着。','灯'], '灯', basis)

    def test_interpretation_never_gets_a_literal_verified_label(self):
        r = validate_basis(['灯'], '灯', {'kind':'interpretation','why_unverified':'读法未实际验证'})
        self.assertEqual(r['status'], 'not_program_verified')
        with self.assertRaises(ValueError): validate_basis(['灯'],'灯',None)
