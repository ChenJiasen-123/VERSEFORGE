import unittest
from poetry_agent.text_structure import inspect_structure, compare_lineation, literal_repetitions


class StructureTests(unittest.TestCase):
    def test_repetition_count_survives_same_line_and_split_phrase(self):
        for lines in (['再数一次', '她说', '再数一次'], ['再数一次她说再数一次'],
                      ['再数', '一次她说再', '数一次']):
            item = next(x for x in literal_repetitions(lines)['items'] if x['fragment'] == '再数一次')
            self.assertEqual(item['occurrence_count'], 2)
            for occurrence in item['occurrences']:
                start, end = occurrence['start_line'] - 1, occurrence['end_line'] - 1
                raw = lines[start: end + 1]
                if start == end:
                    text = raw[0][occurrence['start_character']-1:occurrence['end_character']]
                else:
                    raw[0] = raw[0][occurrence['start_character']-1:]
                    raw[-1] = raw[-1][:occurrence['end_character']]
                    text = ''.join(raw)
                self.assertEqual(text, '再数一次')

    def test_overlaps_and_punctuation_are_preserved(self):
        item = next(x for x in literal_repetitions(['哈哈哈'])['items'] if x['fragment'] == '哈哈')
        self.assertEqual(item['occurrence_count'], 2)
        self.assertEqual([x['start_character'] for x in item['occurrences']], [1, 2])
        self.assertFalse(any(x['fragment'] == '我等待' for x in literal_repetitions(['我，等待', '我等待'])['items']))

    def test_empty_text_has_no_occurrences(self):
        self.assertEqual(literal_repetitions(['', ''])['items'], [])

    def test_position_limit_does_not_change_total_count(self):
        report = literal_repetitions(['再来，' * 40])
        item = next(x for x in report['items'] if x['fragment'] == '再来')
        self.assertEqual(item['occurrence_count'], 40)
        self.assertEqual(len(item['occurrences']), 32)
        self.assertTrue(item['occurrence_positions_truncated'])

    def test_lineation_difference_preserves_punctuation_and_locates_boundaries(self):
        result = compare_lineation(['一句不好意思停在半空，', '被屏幕收走。'],
                                  ['一句不好意思', '停在半空，被屏幕收走。'])
        self.assertTrue(result['applicable'])
        self.assertEqual([x['character_offset'] for x in result['changed_boundaries']], [6, 11])
        self.assertFalse(result['changed_boundaries'][0]['break_in_a'])
        self.assertTrue(result['changed_boundaries'][0]['break_in_b'])

    def test_lineation_does_not_confuse_changed_punctuation_with_only_line_breaks(self):
        self.assertFalse(compare_lineation(['雨停，', '人走。'], ['雨停', '人走。'])['applicable'])

    def test_unchanged_lineation_has_no_boundary_difference(self):
        self.assertEqual(compare_lineation(['雨停', '人走'], ['雨停', '人走'])['changed_boundaries'], [])

    def test_exact_repetition_is_reported_without_rhyme_claim(self):
        r = inspect_structure(['我没有听见。', '你也没有听见。'])
        self.assertIn({'fragment': '没有听见', 'lines': [1, 2]}, r['cross_line_literal_repetitions'])
        self.assertEqual(r['line_end_characters'][0]['last_character'], '见')
        self.assertNotIn('rhyme_passed', r)

    def test_repeated_action_does_not_invent_literal_repeat(self):
        r = inspect_structure(['把伞收了又撑开。', '雨珠落在鞋面。'])
        self.assertEqual(r['cross_line_literal_repetitions'], [])

    def test_punctuation_does_not_join_into_nonexistent_phrase(self):
        r = inspect_structure(['我，等待。', '我等待。'])
        self.assertNotIn({'fragment': '我等待', 'lines': [1, 2]}, r['cross_line_literal_repetitions'])
