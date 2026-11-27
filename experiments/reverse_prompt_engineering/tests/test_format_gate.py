"""题目硬约束的格式门：总行数下限、分节数、每节行数。

此前只有 ``poetry_agent.core.check`` 的总行数上限会被执行，
违反“至少12行/分2—4节/每节1—6行”的诗仍被记为 form_ok。
"""
import unittest

from experiments.reverse_prompt_engineering.generator import requirement_issues, stanza_shape

REQUIREMENTS = "12—20行，分2—4节；每节1—6行；不得出现任何诗人姓名。"


def poem(shapes):
    """用每节行数拼出 raw_lines，空字符串分节。"""
    lines = []
    for index, size in enumerate(shapes):
        if index:
            lines.append("")
        lines.extend(["一行诗"] * size)
    return lines


class RequirementIssuesTest(unittest.TestCase):
    def test_stanza_shape_uses_blank_lines(self):
        self.assertEqual(stanza_shape(poem([4, 5, 3])), [4, 5, 3])
        self.assertEqual(stanza_shape([]), [])

    def test_valid_poem_has_no_issue(self):
        self.assertEqual(requirement_issues(poem([4, 4, 4]), {"requirements": REQUIREMENTS}), [])

    def test_too_few_lines(self):
        issues = requirement_issues(poem([3, 5, 2]), {"requirements": REQUIREMENTS})
        self.assertTrue(any("少于12行" in issue for issue in issues), issues)

    def test_too_many_stanzas(self):
        issues = requirement_issues(poem([2, 3, 3, 3, 2, 1]), {"requirements": REQUIREMENTS})
        self.assertTrue(any("6节" in issue for issue in issues), issues)

    def test_stanza_over_line_limit(self):
        issues = requirement_issues(poem([4, 7, 6]), {"requirements": REQUIREMENTS})
        self.assertTrue(any("第2节" in issue for issue in issues), issues)

    def test_requirements_without_counts_are_ignored(self):
        self.assertEqual(requirement_issues(poem([2]), {"requirements": "写深夜与机器"}), [])


if __name__ == "__main__":
    unittest.main()
