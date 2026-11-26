"""Deterministic offline mock for dry-runs and tests.

Mock outputs are synthetic.  They are clearly marked in the run state and may
not be reported as real model behaviour, scores, or research findings.
"""
from __future__ import annotations

import hashlib
import json
import math


def _h(*parts) -> int:
    body = "\x1f".join(str(p) for p in parts)
    return int(hashlib.sha256(body.encode("utf-8")).hexdigest(), 16)


def _pick(seq, seed, offset=0):
    return seq[(seed + offset) % len(seq)]


PROMPT_ANGLES = [
    "字词与语气：优先具体的名词和动词，少用抽象形容词。",
    "句法与分行：让短句、跨行停顿和重复结构承担节奏。",
    "意象与修辞：让日常物件与自然物并置，避免解释性比喻。",
    "情感与抒情位置：先写动作和场景，再让情感从缝隙里出现。",
    "篇章推进：用空间或时间移动组织全诗，结尾落在具体物象上。",
]

POEM_LINES = [
    "夜里有人把灯留在走廊尽头",
    "机器的低鸣像一场没有结束的雨",
    "我数着硬币，也数着回家的路",
    "玻璃上映出两张疲倦的脸",
    "风从门缝里带来铁锈的气味",
    "有人把外套搭在椅背上",
    "远处的水面慢慢合上",
    "我听见楼上的脚步停了又响",
    "灯管闪了一下，像在犹豫",
    "一只空瓶滚到墙角",
    "我们把沉默分着吃完",
    "天亮以前，谁也没有离开",
    "窗外的树影比人更早醒来",
    "一只鸟落在生锈的栏杆上",
    "它看了我一眼，又飞走",
    "桌上的水杯还留着温度",
    "有人低声念出一个地名",
    "那声音很快被机器吞掉",
    "我把手插进口袋，摸到一枚扣子",
    "雨水在台阶上写下又擦去",
    "一辆车从桥下经过",
    "灯光把我们的影子拉得很长",
    "墙上的钟停在两点十七分",
    "我忽然想起一件很小的事",
    "后来我们都笑了",
    "笑声落在地上，没有人捡",
    "风把门吹开，又轻轻关上",
    "天边露出一点灰白",
]


class MockRPELLM:
    """A tiny rule-based stand-in for the DeepSeek client."""

    mock = True
    model = "rpe-mock-not-a-language-model"

    def __init__(self, seed=0):
        self.seed = int(seed)
        self.calls = 0
        self.requests = []

    def complete(self, system, user, timeout=90, max_tokens=1200, thinking=None, temperature=None):
        self.calls += 1
        try:
            payload = json.loads(user)
        except (TypeError, ValueError):
            payload = {"kind": "unknown", "raw": user}
        self.requests.append({"kind": payload.get("kind"), "system": system, "user": user, "payload": payload})
        kind = payload.get("kind")
        seed = _h(self.seed, kind, user)
        if kind == "rpe_initialize":
            data = self._prompt_payload(payload, seed)
        elif kind == "rpe_reverse_once":
            data = self._prompt_payload(payload, seed)
        elif kind == "rpe_generate_poem":
            data = self._poem_payload(payload, seed)
        elif kind == "rpe_judge_poem":
            data = self._judge_payload(payload, seed)
        elif kind == "rpe_analyze_candidate":
            data = self._analysis_payload(payload, seed)
        elif kind == "rpe_mutate_prompt":
            data = self._mutation_payload(payload, seed)
        else:
            data = {"error": f"mock 未支持 kind={kind}"}
        content = json.dumps(data, ensure_ascii=False)
        usage = {
            "prompt_tokens": max(1, math.ceil(len(system + user) / 1.2)),
            "completion_tokens": max(1, math.ceil(len(content) / 1.2)),
        }
        usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
        return {
            "content": content,
            "usage": usage,
            "request_settings": {
                "max_tokens": max_tokens, "response_format": "json_object",
                "thinking": thinking or "service_default",
                "temperature": temperature if temperature is not None else "service_default",
                "mock": True,
            },
        }

    def _prompt_payload(self, payload, seed):
        angle = payload.get("focus") or _pick(PROMPT_ANGLES, seed)
        index = payload.get("candidate_index", 0)
        variants = [
            "让每一节有一个可看见的中心物象，但不要解释它的象征意义。",
            "把长句拆成两到三个短句，允许一行只有一个动作。",
            "在第三节改变人称或视角，让前两节积累的情绪被重新照亮。",
            "重复一个短句或短语两次，第二次改变它的语气。",
            "结尾不要总结，留下一个仍在运动中的物件。",
        ]
        chosen = variants[(seed + int(index or 0)) % len(variants)]
        prompt = (
            "写现代汉语自由诗。遵守以下可迁移的写作指令：\n"
            f"1. {angle}\n"
            "2. 每节控制在2—5行，行尾优先落在具体名词、动作或短句上；不要连续三行使用相同长度的句子。\n"
            "3. 全诗至少出现一次重复呼告或重复短语，但同一意象不要反复超过三次。\n"
            "4. 先写动作、空间和声音，再让情感从场景的缝隙里出现；每节最多一次直接抒情。\n"
            "5. 句法允许短句、破折号和跨行停顿，不使用成语堆叠，不把抽象名词当作行尾支点。\n"
            f"6. {chosen}\n"
            "7. 不要复述任何既有作品的场景、人物、地名或成句；只迁移语言组织、节奏、意象关系和篇章推进方式。\n"
            "8. 题目可以完全不同；不要要求新诗继续写旧题材，也不要在诗中解释这些指令。\n"
        )
        return {
            "prompt": prompt,
            "design_notes": "Mock 候选：由固定规则拼装，仅用于流程测试，不代表真实模型分析。",
            "covered_dimensions": ["lexical", "syntax", "lineation", "imagery", "emotion", "structure"],
            "mock": True,
        }

    def _poem_payload(self, payload, seed):
        topic = str(payload.get("topic") or "无题")
        max_lines = int(payload.get("max_lines") or 14)
        line_count = min(max_lines, 12 + seed % 5)
        chosen = []
        for i in range(line_count):
            if i == 0:
                chosen.append(f"{topic}，灯还亮着")
            else:
                line = _pick(POEM_LINES, seed, i * 7)
                if line in chosen:
                    line = _pick(POEM_LINES, seed, i * 7 + 3)
                chosen.append(line)
        # 3—4 stanzas with 3—5 lines each
        stanzas = []
        cursor = 0
        widths = [4, 4, 4, max(0, line_count - 12)]
        for width in widths:
            if cursor >= line_count:
                break
            width = max(1, min(width, line_count - cursor))
            stanzas.append(chosen[cursor:cursor + width])
            cursor += width
        if cursor < line_count:
            stanzas[-1].extend(chosen[cursor:])
        lines = []
        for stanza in stanzas:
            lines.extend(stanza)
        title = f"{topic}（模拟稿）"
        return {"title": title, "lines": lines, "mock": True}

    def _judge_payload(self, payload, seed):
        poem = payload.get("generated_poem") or {}
        lines = poem.get("lines") or []
        text = "\n".join(lines)
        evidence = [line for line in lines[:2] if line] or ["（无正文）"]
        dims = {}
        names = [
            "lexical", "syntax", "lineation", "imagery", "emotion", "structure", "progression",
            "concreteness", "repetition", "addressivity", "mythic_register", "closure",
            "literary_quality", "topic_adherence", "originality",
        ]
        base = 2.6 + (seed % 18) / 10.0
        for i, name in enumerate(names):
            offset = ((seed >> (i * 3)) % 9) / 10.0 - 0.4
            score = max(0.0, min(5.0, round(base + offset, 1)))
            dims[name] = {
                "score": score,
                "evidence": evidence[:1] + ([_pick(lines, seed, i + 3)] if lines else []),
                "rationale": f"Mock 评审：依据给定文本对 {name} 做固定规则打分，不能作为真实评价。",
                "uncertainty": "high",
            }
        return {
            "dimensions": dims,
            "overall_notes": "Mock 评审输出，仅用于验证评价、选择和报告流程；不是研究数据。",
            "confidence": "high_uncertainty_mock",
            "mock": True,
        }

    def _analysis_payload(self, payload, seed):
        refs = payload.get("reference_poems") or []
        generated = payload.get("generated_poems") or []
        gen_line = ""
        if generated:
            lines = generated[0].get("lines") or generated[0].get("text", "").splitlines()
            gen_line = lines[0] if lines else ""
        ref_line = ""
        if refs:
            ref_line = (refs[0].get("text") or "").splitlines()[0]
        return {
            "reproduced": [{
                "feature": "短行与具体动作并置",
                "generated_evidence": gen_line,
                "reference_evidence": ref_line,
                "claim_type": "observation",
                "confidence": "medium",
            }],
            "missing": [{
                "feature": "重复呼告的强度可能不足",
                "generated_evidence": gen_line,
                "reference_evidence": ref_line,
                "claim_type": "interpretation",
                "confidence": "low",
            }],
            "extraneous": [{
                "feature": "解释性句子偏多",
                "generated_evidence": gen_line,
                "claim_type": "observation",
                "confidence": "medium",
            }],
            "prompt_issues": [{
                "quote": "每节最多一次直接抒情",
                "issue_type": "vague",
                "explanation": "Mock 分析：该条可执行性尚可，但需要说明抒情如何落地。",
                "claim_type": "interpretation",
            }],
            "topic_overreliance": {
                "assessment": "Mock 分析无法判断真实题材依赖。",
                "evidence": gen_line,
                "claim_type": "interpretation",
            },
            "summary": "Mock 差异分析：仅验证字段与流程，不是对真实诗歌的判断。",
            "actionable_suggestions": [
                "把抽象评价改成可观察的句法或分行规则。",
                "保留已经有效的短行和动作先行写法。",
                "增加一条限制重复意象使用次数的指令。",
            ],
            "mock": True,
        }

    def _mutation_payload(self, payload, seed):
        parent = str(payload.get("parent_prompt") or "").strip()
        additions = [
            "让每一节的最后一个词落在可看见的物件或正在发生的动作上，避免用抽象判断收束。",
            "在第二或第三节加入一次短促的呼告，呼告对象只能是物、地点或时间，不得是人名。",
            "把连续两个解释性句子删掉，改成一个动作加一个声音。",
            "全诗至少有一次跨行停顿，让一句话在两行之间断开。",
        ]
        chosen = additions[seed % len(additions)]
        prompt = parent + ("\n" if parent else "") + f"9. {chosen}"
        return {
            "prompt": prompt,
            "changes": [{
                "op": "add",
                "target": "新增一条可执行的分行或意象指令",
                "reason": "Mock 变异依据差异分析中的可执行性建议；真实运行时会由模型给出理由。",
            }],
            "preserved": ["保留父代中已有的短行与具体动作要求"],
            "summary": "Mock 变异：追加一条指令，用于流程测试。",
            "mock": True,
        }


def make_mock_llm(config, run_dir, seed=None):
    from .llm import Budget, LLMCache, JsonlLedger, LLM

    seed = config["experiment"]["seed"] if seed is None else seed
    client = MockRPELLM(seed)
    budget = Budget(
        config["budget"]["max_api_calls"],
        config["budget"]["max_total_tokens"],
        config["budget"].get("price_per_million_input"),
        config["budget"].get("price_per_million_output"),
    )
    cache = LLMCache(run_dir / "cache.jsonl")
    ledger = JsonlLedger(run_dir / "ledger.jsonl")
    llm = LLM(client, budget, cache, ledger,
              max_parse_retries=config["budget"]["max_parse_retries"],
              request_timeout=config["budget"]["request_timeout"])
    llm.same_model_as_generator = True
    return llm
