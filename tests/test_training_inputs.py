import unittest
from train_adapter import encode_row


class Tokenizer:
    def apply_chat_template(self, messages, tokenize, add_generation_prompt=False):
        return [1, 2, 3] if add_generation_prompt else [1, 2, 3, 4, 5]


class TrainingInputTests(unittest.TestCase):
    def test_prompt_is_masked_and_answer_is_not(self):
        row = {'topic': '题', 'original': {}, 'revision': {}}
        result = encode_row(row, Tokenizer(), 10)
        self.assertEqual(result['labels'], [-100, -100, -100, 4, 5])

    def test_oversize_examples_are_not_silently_truncated(self):
        with self.assertRaises(ValueError):
            encode_row({'topic': '题', 'original': {}, 'revision': {}}, Tokenizer(), 4)
