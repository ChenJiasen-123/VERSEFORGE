import unittest
from import_rhyme_snapshot import extract


class ImportTests(unittest.TestCase):
    def test_extension_character_does_not_drop_entire_body(self):
        text = 'L1: 上平聲一東\nL2: 東𠀀同\nL3: 上平聲二冬'
        self.assertEqual(extract(text)[0]['characters'], '東𠀀同')

    def test_unknown_body_annotation_requires_inspection(self):
        with self.assertRaises(ValueError):
            extract('L1: 上平聲一東\nL2: 東同(待核)\nL3: 上平聲二冬')

    def test_final_group_requires_recognized_document_boundary(self):
        text = 'L759: 入聲十七洽\nL760: \nL761: 洽狹\nL762: \nL763: 〖詞〗掐\nL764: \nL765: 此作品在全世界都属于公有领域'
        self.assertEqual(extract(text), [{'name': '入聲十七洽', 'tone': 'Z', 'characters': '洽狹'}])

    def test_gap_cannot_attach_next_groups_body_to_previous_heading(self):
        text = 'L1: 上聲四紙\nL2: \nL9: 語旅\nL10: 上聲七麌\nL11: 雨舞\nL12: 上聲八薺'
        self.assertEqual(extract(text), [{'name': '上聲七麌', 'tone': 'Z', 'characters': '雨舞'}])

    def test_excludes_appendix_and_incomplete_final_group(self):
        text = 'L1: 上平聲一東\nL2: 東同\nL3: 〖詞〗嗡\nL4: 上平聲二冬\nL5: 冬'
        self.assertEqual(extract(text), [{'name': '上平聲一東', 'tone': 'P', 'characters': '東同'}])
