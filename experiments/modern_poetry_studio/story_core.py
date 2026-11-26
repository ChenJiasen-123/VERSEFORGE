"""Generate story cores for an arbitrary object or prompt.

A poem written directly from an object tends to become an object description.
A poem written from a story core has a chance to carry inner experience, a
structural era conflict, and a life question.  This module is deliberately
separate from ``write_poem.py``.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from poetry_agent.client import DeepSeekClient, load_env

ROOT = Path(__file__).resolve().parents[2]

SYSTEM = """你是中文诗的故事核编辑。给定一个物件或题目，提出 3 个差异明显的故事核。
故事核不是诗歌，不是物件说明，也不是社会调查报告。

每个故事核必须满足：

1. 具体的人：年龄、职业、来处、当下处境。他/她不是孤立的个体，而是某一类人、一个地方、一代人的入口。
2. 世界相撞：这个物件必须是两种世界相撞的地方——乡土/城市、土地/系统、身体/商品、记忆/数据、手工/平台、死亡/回收。不要只写“这个人很惨”。
3. 结构性冲突：不是“他倒霉”，而是“他所生活的世界正在被另一种世界取代”。个人的损失背后要有一个时代性的失去。
4. 集体尺度：这个人背后是谁？一个村、一代打工者、一批被拆迁的人、一种消失的手艺、一群不能回家的人。写清楚“谁和他一起失去”。
5. 生命问题：必须是存在性的——死亡、爱、记忆、身体、时间、孤独、自由、亏欠；不是政策评价或道德判断。
6. 可进入：读者不需要专门历史知识。时代只用 1—2 个普通读者能懂的具体标记：手机、租房、葬礼、医院、外卖、房贷、异地工作、拆迁、物流园。
7. 一个能贯穿全诗的具体物象/动作：袖子、纽扣、存折、传送带、坟头草、铁箱的翻板。

不要写诗，不要抒情，不要出现任何诗人姓名。只输出 JSON 对象：
{"cores": [{
  "title": "一句短标题",
  "person": "具体的人",
  "collective": "他背后是谁，谁和他一起失去",
  "world_collision": "哪两种世界在这个物件上相撞",
  "structural_conflict": "什么结构性的东西正在被取代",
  "debt": "他/她欠谁什么，或谁欠他/她什么",
  "turning_day": "哪一天这个物件不再是日常",
  "life_question": "存在性的生命问题",
  "image": "贯穿全诗的具体物象/动作",
  "avoid": "这首诗不要写成什么"
}]}"""

FIELDS = (
    "title",
    "person",
    "collective",
    "world_collision",
    "structural_conflict",
    "debt",
    "turning_day",
    "life_question",
    "image",
    "avoid",
)


def _clean(value) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("故事核字段必须是非空字符串")
    return value.strip()


def parse_cores(content: str) -> list[dict]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        data = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise ValueError("故事核不是有效 JSON") from exc
    if isinstance(data, dict):
        cores = data.get("cores")
    elif isinstance(data, list):
        cores = data
    else:
        cores = None
    if not isinstance(cores, list) or not cores:
        raise ValueError("缺少 cores 数组")
    result = []
    for index, core in enumerate(cores, 1):
        if not isinstance(core, dict):
            raise ValueError(f"第 {index} 个故事核不是对象")
        result.append({field: _clean(core.get(field)) for field in FIELDS})
    return result


def build_user(object_text: str) -> str:
    return json.dumps(
        {
            "object": object_text,
            "task": "提出 3 个差异明显的故事核；每个都要有具体的人、集体尺度、世界相撞、结构性冲突、欠债、转折日和存在性生命问题。",
            "output_schema": {"cores": [{field: "string" for field in FIELDS}]},
        },
        ensure_ascii=False,
    )


def _call_json(client, system: str, user: str, *, max_tokens: int, temperature: float, attempts: int = 2) -> str:
    last_error = None
    for _ in range(attempts):
        response = client.complete(
            system, user, timeout=90, max_tokens=max_tokens,
            thinking="disabled", temperature=temperature,
        )
        content = response.get("content", "")
        try:
            parse_cores(content)
            return content
        except ValueError as exc:
            last_error = str(exc)
    raise ValueError(f"故事核解析失败：{last_error}")


def generate_cores(client, object_text: str, *, max_tokens: int = 3200, temperature: float = 0.9) -> dict:
    content = _call_json(
        client, SYSTEM, build_user(object_text),
        max_tokens=max_tokens, temperature=temperature,
    )
    return {
        "object": object_text,
        "cores": parse_cores(content),
        "raw": content,
    }


class MockStoryClient:
    mock = True
    model = "mock-story-core"

    def complete(self, system, user, timeout, max_tokens=3200, thinking=None, temperature=None):
        object_text = json.loads(user).get("object", "物件")
        template = {
            "title": f"{object_text}·一",
            "person": "五十八岁的社区保洁员，住在城中村，儿子在外地。",
            "collective": "和他一起失去的是整条老街的邻居，他们都不再认识彼此的门。",
            "world_collision": "老街的熟人社会与新城的人脸识别系统在这个物件上相撞。",
            "structural_conflict": "靠脸和招呼维持的信任，正在被靠数据和验证码维持的通行取代。",
            "debt": "他欠母亲一次扫墓，母亲欠他一个不用证明自己是谁的午后。",
            "turning_day": "系统升级那天，他的脸在机器里变成了“无法识别”。",
            "life_question": "当你的脸不再被系统认出来，你还是你吗？",
            "image": "屏幕上红色的“验证失败”，照着他手背上的老年斑。",
            "avoid": "不要写成科技批判或老人可怜。",
        }
        cores = [template, {**template, "title": f"{object_text}·二"}, {**template, "title": f"{object_text}·三"}]
        return {"content": json.dumps({"cores": cores}, ensure_ascii=False), "usage": {}, "request_settings": {"mock": True}}


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="为任意物件生成故事核")
    parser.add_argument("--input", required=True, help="物件或题目")
    parser.add_argument("--output", type=Path, default=Path("var/modern_poetry_studio/story-cores.json"))
    parser.add_argument("--mode", choices=("mock", "live"), default="mock")
    parser.add_argument("--authorize-spend", action="store_true")
    parser.add_argument("--temperature", type=float, default=0.9)
    args = parser.parse_args()
    if args.mode == "live" and not args.authorize_spend:
        raise SystemExit("live 模式需要 --authorize-spend")
    if args.mode == "mock":
        client = MockStoryClient()
    else:
        load_env(ROOT / ".env")
        client = DeepSeekClient()
    result = generate_cores(client, args.input, temperature=args.temperature)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    for index, core in enumerate(result["cores"], 1):
        print(f"\n[{index}] {core['title']}")
        for field in FIELDS[1:]:
            print(f"  {field}: {core[field]}")
    print(f"\n保存：{args.output}")


if __name__ == "__main__":
    main()
