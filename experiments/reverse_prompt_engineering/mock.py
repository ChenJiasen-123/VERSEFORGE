"""Deterministic offline mock for dry-runs and tests.

Mock outputs are synthetic.  They are clearly marked in the run state and may
not be reported as real model behaviour, scores, or research findings.
"""
from __future__ import annotations

import hashlib
import json
import math
import re


def _h(*parts) -> int:
    body = "\x1f".join(str(p) for p in parts)
    return int(hashlib.sha256(body.encode("utf-8")).hexdigest(), 16)


def _pick(seq, seed, offset=0):
    return seq[(seed + offset) % len(seq)]


PROMPT_ANGLES = [
    "优先使用质朴而有重量的具体名词与动词，让抽象感叹落在具体物象上。",
    "少用行末标点，用断行、行内留白与长短句陡峭落差承担呼吸节奏。",
    "让现场日常器物与黑夜、雨水、大地、身体等原初元素发生碰撞。",
    "通过直接命名句与呼告建立说话姿态，核心词跨节回返时改变语境位置。",
    "结尾自然承接前文建立的意象关系并保留余响，不用空洞格言收束。",
]

POEM_LINES = [
    "夜里有人把灯留在走廊尽头",
    "机器的低鸣越过潮湿的地面",
    "我握住硬币 也握住回家的路",
    "玻璃上映出两张疲倦的脸",
    "风从门缝吹来铁与泥土的气味",
    "有人把外套搭在冰冷的椅背",
    "远处的水面在黑暗中合拢",
    "楼上的脚步停下又再次响起",
    "灯管闪了一下",
    "一只空瓶滚向墙角",
    "我们把沉默分着咽下",
    "黎明以前谁也没有离开",
    "窗外的树影比人更早醒来",
    "水鸟落在生锈的栏杆",
    "它望向河心又转身飞走",
    "桌上的铁杯还留着掌心余温",
    "有人低声叫出一个北方的地名",
    "声音很快沉入夜色",
    "我摸到口袋里一枚旧扣子",
    "雨水在台阶上写下又擦去",
    "夜班渡船从桥影下驶过",
    "灯光把人的影子拉向江面",
    "墙上的钟走过凌晨四点",
    "风把铁皮门吹响",
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
        if kind in ("rpe_initialize", "rpe_reverse_once"):
            data = self._prompt_payload(payload, seed)
        elif kind == "rpe_generate_poem":
            data = self._poem_payload(payload, seed)
        elif kind == "rpe_judge_poem":
            data = self._judge_payload(payload, seed)
        elif kind == "rpe_analyze_candidate":
            data = self._analysis_payload(payload, seed)
        elif kind == "rpe_mutate_prompt":
            data = self._mutation_payload(payload, seed)
        elif kind == "rpe_crossover_prompt":
            data = self._crossover_payload(payload, seed)
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
        index = int(payload.get("candidate_index") or 0)
        variants = [
            "每一节围绕一个核心物象展开动作与尺度变化，不做象征说教。",
            "长句与三五字短行交替出现，多数行尾不加标点，用断行形成呼吸。",
            "中段切换一次观看距离，把眼前器物推向黑夜、江水或土地的纵深。",
            "让一个关键词在不同节回返并改变句法位置，避免原样照抄整行。",
            "收尾停在具体动作或带有余温的物象上，不追加格言总结。",
        ]
        chosen = variants[(seed + index) % len(variants)]
        prompt = (
            "现代自由诗风格指令（篇幅与分节服从具体题目要求）：\n"
            f"1. {angle}\n"
            "2. 行尾少用标点，多在名词或动词处自然断行，让长句铺展与短行停顿形成明显张力。\n"
            "3. 具体日常物象须与大地、夜色、水、风或身体感知发生关系，不堆砌琐碎零件清单。\n"
            "4. 情感融入直接命名、呼告与具体动作之中，少用因为、所以、然而等解释性连词。\n"
            f"5. {chosen}\n"
            "6. 不复述既有作品的人物、地名或成句，只迁移语言呼吸与意象组织方式。\n"
        )
        return {
            "prompt": prompt,
            "design_notes": "Mock 候选：由固定规则拼装，仅用于流程测试，不代表真实模型分析。",
            "covered_dimensions": ["lexical", "syntax", "lineation", "imagery", "emotion", "structure"],
            "mock": True,
        }

    def _poem_payload(self, payload, seed):
        topic = str(payload.get("topic") or "无题")
        max_lines = int(payload.get("max_lines") or 16)
        line_count = min(max_lines, 12 + seed % 4)
        chosen = []
        for i in range(line_count):
            if i == 0:
                chosen.append(f"{topic}的灯还亮着")
            else:
                line = _pick(POEM_LINES, seed, i * 5)
                if line in chosen:
                    line = _pick(POEM_LINES, seed, i * 5 + 2)
                chosen.append(line)
        # Split into 3 stanzas of 4-6 lines separated by "" so requirement_issues passes
        s1 = 4
        s2 = 4
        stanzas = [chosen[:s1], chosen[s1:s1 + s2], chosen[s1 + s2:]]
        lines = []
        for idx, stanza in enumerate(stanzas):
            if not stanza:
                continue
            if idx > 0:
                lines.append("")
            lines.extend(stanza)
        title = f"{topic}（模拟稿）"
        return {"title": title, "lines": lines, "mock": True}

    def _judge_payload(self, payload, seed):
        poem = payload.get("generated_poem") or {}
        lines = [line for line in (poem.get("lines") or []) if line.strip()]
        evidence = lines[:2] or ["（无正文）"]
        dims = {}
        names = [
            "lexical", "syntax", "lineation", "imagery", "emotion", "structure", "progression",
            "concreteness", "repetition", "addressivity", "mythic_register", "closure",
            "literary_quality", "topic_adherence", "originality",
        ]
        base = 3.2 + (seed % 12) / 10.0
        for i, name in enumerate(names):
            offset = ((seed >> (i * 3)) % 7) / 10.0 - 0.3
            score = max(3.0 if name in ("topic_adherence", "originality", "literary_quality") else 1.5,
                        min(5.0, round(base + offset, 1)))
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
            lines = [x for x in (generated[0].get("lines") or generated[0].get("text", "").splitlines()) if x.strip()]
            gen_line = lines[0] if lines else ""
        ref_line = (refs[0].get("text") or "").splitlines()[0] if refs else ""
        return {
            "reproduced": [{
                "feature": "无标点断行与具体物象并置",
                "generated_evidence": gen_line,
                "reference_evidence": ref_line,
                "claim_type": "observation",
                "confidence": "medium",
            }],
            "missing": [{
                "feature": "原初元素尺度与变奏回返仍可加强",
                "generated_evidence": gen_line,
                "reference_evidence": ref_line,
                "claim_type": "interpretation",
                "confidence": "low",
            }],
            "extraneous": [{
                "feature": "局部叙述略平",
                "generated_evidence": gen_line,
                "claim_type": "observation",
                "confidence": "medium",
            }],
            "prompt_issues": [{
                "quote": "情感融入直接命名",
                "issue_type": "vague",
                "explanation": "Mock 分析：可进一步说明呼告与回返如何改变位置。",
                "claim_type": "interpretation",
            }],
            "topic_overreliance": {
                "assessment": "Mock 分析无法判断真实题材依赖。",
                "evidence": gen_line,
                "claim_type": "interpretation",
            },
            "summary": "Mock 差异分析：仅验证字段与流程，不是对真实诗歌的判断。",
            "actionable_suggestions": [
                "将模糊表述替换为可观察的长短行落差与变奏回返指引。",
                "保留无标点自然断行与物象碰撞原则。",
            ],
            "mock": True,
        }

    def _mutation_payload(self, payload, seed):
        parent = str(payload.get("parent_prompt") or "").strip()
        replacements = [
            "5. 让核心词在后节回返时改变句法位置或尺度，收尾停在仍带余温的动作或物象上。",
            "5. 在中段引入一次由近景器物向夜色、江水或大地尺度的推远，结尾不做格言总结。",
            "5. 允许一处对具体物或地点的短促呼告，呼告后紧接无标点短行形成呼吸顿挫。",
            "5. 明喻保持克制，优先用直接命名句连接具体身体感知与自然元素。",
        ]
        chosen = replacements[seed % len(replacements)]
        if re.search(r"^5\..*$", parent, flags=re.MULTILINE):
            prompt = re.sub(r"^5\..*$", chosen, parent, count=1, flags=re.MULTILINE)
            if prompt == parent:
                prompt = parent + "\n7. 保持每节内部呼吸紧凑，避免散文化解释句。"
        else:
            prompt = parent + "\n" + chosen
        return {
            "prompt": prompt,
            "changes": [{
                "op": "replace",
                "target": "第5条结构与回返原则",
                "reason": "Mock 变异依据差异分析优化变奏与收束规则。",
            }],
            "preserved": ["保留无标点断行与原初元素碰撞要求"],
            "summary": "Mock 变异：替换第5条规则以验证演化流程。",
            "mock": True,
        }

    def _crossover_payload(self, payload, seed):
        prompt = (
            "现代自由诗融合风格指令（篇幅与分节服从题目要求）：\n"
            "1. 词域取质朴而有重量的基础名词与单双音节动词，少用解释性连词。\n"
            "2. 行末少用标点，依靠自然断行、行内空格停顿以及长句与三五字短行的陡峭对比建立节奏。\n"
            "3. 把题目现场的具体器物与黑夜、大地、水火、身体等深层生命尺度并置碰撞。\n"
            "4. 允许直接命名与克制呼告，核心意象跨节回返时须改变语境或句法位置。\n"
            f"5. 结尾承接前文物象关系并停在余响处（变体 {seed % 7 + 1}），不写总结格言。\n"
        )
        return {
            "prompt": prompt,
            "from_parent_a": ["质朴词域与元素尺度并置"],
            "from_parent_b": ["无标点断行与长短句呼吸对比"],
            "resolved_conflicts": ["合并了重复的收尾要求"],
            "summary": "Mock 重组：融合双亲词域与分行优势。",
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
