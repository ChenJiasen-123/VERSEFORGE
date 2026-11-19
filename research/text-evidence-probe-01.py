"""Run from project root with PYTHONPATH=.; two bounded API reviews."""
import json
from pathlib import Path
from poetry_agent.client import DeepSeekClient, load_env
from poetry_agent.aesthetics import review, TEXT_EVIDENCE, failure_code

poem = {"title": "留门", "lines": [
    "如果父亲今晚回来，", "我就把门口那双鞋翻过来，", "让鞋底积下的雨", "先替他走进屋。",
    "可我没有开门。", "隔壁的钥匙响了一下，", "我把电视调轻，", "仿佛这样，就能听清一个没有发生的脚步。"]}
task = {"genre": "modern", "topic": "等待", "max_lines": 10}

class WithoutEvidence:
    def __init__(self, client): self.client = client
    def complete(self, system, user, **kwargs):
        return self.client.complete(system.replace(TEXT_EVIDENCE, ""), user, **kwargs)

if __name__ == "__main__":
    output = Path("runs/text-evidence-probe-01.json")
    if output.exists(): raise SystemExit("output exists; not overwritten")
    load_env(".env")
    client = DeepSeekClient()
    rows = []
    for arm, endpoint in [("previous_prompt", WithoutEvidence(client)), ("evidence_prompt", client)]:
        try:
            result = review(poem, task, endpoint, 60)
            result["review_protocol_version"] = "text-review-0.8" if arm == "previous_prompt" else "text-review-0.9"
            rows.append({"arm": arm, "result": result})
        except Exception as error:
            rows.append({"arm": arm, "failure": failure_code(error)})
    output.parent.mkdir(exist_ok=True)
    with output.open("x", encoding="utf-8") as f:
        json.dump({"poem": poem, "task": task, "model": client.model,
                   "order": "fixed_previous_then_evidence", "human_preference": None,
                   "quality_verified": False, "results": rows}, f, ensure_ascii=False, indent=2)
    print("Saved diagnostic; " + str(sum("result" in row for row in rows)) + "/2 reviews completed.")
