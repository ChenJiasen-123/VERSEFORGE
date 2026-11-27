from pathlib import Path
import tempfile
import unittest

from experiments.reverse_prompt_engineering.store import _write_run_progress


class LiveProgressReportsTest(unittest.TestCase):
    def test_each_run_gets_its_own_progress_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "runs" / "run-a"
            second = Path(tmp) / "runs" / "run-b"
            first.mkdir(parents=True)
            second.mkdir(parents=True)

            _write_run_progress(first, "report-a")
            _write_run_progress(second, "report-b")

            self.assertTrue((first / "live_progress.md").read_text(encoding="utf-8").endswith("report-a\n"))
            self.assertTrue((second / "live_progress.md").read_text(encoding="utf-8").endswith("report-b\n"))
            self.assertIn("run-a", (first / "live_progress.md").read_text(encoding="utf-8"))
            self.assertIn("run-b", (second / "live_progress.md").read_text(encoding="utf-8"))


    def test_root_report_links_both_runs_and_labels_old_snapshot(self):
        root = Path(__file__).resolve().parents[3]
        report = (root / "EAReport.md").read_text(encoding="utf-8")
        self.assertIn("runs/live-haizi-v5-emotion-01/live_progress.md", report)
        self.assertIn("runs/live-haizi-expand-v1-v5score-01/live_progress.md", report)
        self.assertIn("旧目录 `live-haizi-expand-v1-01`", report)
        self.assertIn("历史监控快照（非实时", report)


if __name__ == "__main__":
    unittest.main()
