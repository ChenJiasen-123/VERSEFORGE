"""Full 7-Phase Corpus-Reverse RPE-GA for Step-2 Poetic Expansion (Expand-v1).

Implements the exact 7-phase RPE-GA paradigm used for Step-3, while enforcing
a strict Orthogonal Interface Contract between Step-2 (What / World-Building &
Scale) and Step-3 (How / Lineation, Punctuation, Syntax & Rhetoric) so that
Expand-v1 remains cleanly composable with future Style-v5 / Style-v6 upgrades:

- Phase 1: Unbiased reverse initialization from the 15 anonymous reference poems
- Phase 2: Black-box expansion -> locked Style-v4 generation on general bare inputs
- Phase 3: Dual-ruler evaluation (v4 deterministic + deepseek-chat anonymous Judge
           + expansion overreach gate + symmetric AB+BA pairwise tie-breaking)
- Phase 4: Reference-grounded difference analysis (comparing 15 reference poems vs
           generated expansions + poems)
- Phase 5: 3-strategy targeted mutation + elite semantic crossover
- Phase 6: Similarity-niched (μ+λ) selection + progressive 2-rep confirmation
- Phase 7: Independent 3-group benchmark (A: Native Studio BRIEF_SYSTEM,
           B: One-shot reverse expansion prompt, C: RPE-GA Expand-v1 champion)
           on 13 unseen held-out poems and 8 unseen general bare inputs.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import statistics
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from poetry_agent.style import similarity as ngram_sim
from poetry_agent.style.corpus import digest, write as atomic_write
from experiments.reverse_prompt_engineering.config import load_config
from experiments.reverse_prompt_engineering.corpus import anonymous_references, load_selection
from experiments.reverse_prompt_engineering import evaluator, generator, metrics
from experiments.reverse_prompt_engineering.llm import (
    BudgetExhausted, LLMOutputError, is_output_truncation_error, make_live_llms, restore_budget_from_ledger,
)
from experiments.reverse_prompt_engineering.mock import make_mock_llm
from experiments.reverse_prompt_engineering.store import LIVE_END, LIVE_START
from experiments.reverse_prompt_engineering.validation import (
    STYLE_DIMENSIONS, validate_analysis, validate_crossover, validate_initializer,
    validate_mutation, validate_prompt,
)


# Strict Orthogonal Contract: Step-2 is forbidden from intruding into Step-3's
# lineation, punctuation, rhetorical figure, or line/stanza counting domain.
FORBIDDEN_STEP3_INTRUSIONS = (
    "标点", "逗号", "句号", "问号", "破折号",
    "分行", "断行", "跨行", "行内空格", "空格顿挫", "长短句", "短行", "长行",
    "明喻", "暗喻", "比喻禁令", "排比", "倒装", "押韵", "平仄",
    "每节", "总行数", "总节数", "几行", "几节",
)

EXPANSION_OPT_TOPICS = [
    {
        "id": "exp-opt-01",
        "topic": "写人在深夜突然意识到自己已经不再年轻",
        "genre": "modern",
        "max_lines": 20,
        "requirements": "12—20行，分2—4节；每节1—6行；使用现代汉语；不得出现任何诗人姓名。",
    },
    {
        "id": "exp-opt-02",
        "topic": "写一次没有说出口的告别",
        "genre": "modern",
        "max_lines": 20,
        "requirements": "12—20行，分2—4节；每节1—6行；使用现代汉语；不得出现任何诗人姓名。",
    },
    {
        "id": "exp-opt-03",
        "topic": "思考孤独与人群的关系",
        "genre": "modern",
        "max_lines": 20,
        "requirements": "12—20行，分2—4节；每节1—6行；使用现代汉语；不得出现任何诗人姓名。",
    },
    {
        "id": "exp-opt-04",
        "topic": "写一场迟到很久的春天，不要停留在写景",
        "genre": "modern",
        "max_lines": 20,
        "requirements": "12—20行，分2—4节；每节1—6行；使用现代汉语；不得出现任何诗人姓名。",
    },
    {
        "id": "exp-opt-05",
        "topic": "写回到久别的地方却发现自己已成外人",
        "genre": "modern",
        "max_lines": 20,
        "requirements": "12—20行，分2—4节；每节1—6行；使用现代汉语；不得出现任何诗人姓名。",
    },
    {
        "id": "exp-opt-06",
        "topic": "思考沉默与活下去的勇气",
        "genre": "modern",
        "max_lines": 20,
        "requirements": "12—20行，分2—4节；每节1—6行；使用现代汉语；不得出现任何诗人姓名。",
    },
]

EXPANSION_TEST_TOPICS = [
    {
        "id": "exp-test-01",
        "topic": "写给多年后重逢却擦肩而过的旧友",
        "genre": "modern",
        "max_lines": 20,
        "requirements": "12—20行，分2—4节；每节1—6行；使用现代汉语；不得出现任何诗人姓名。",
    },
    {
        "id": "exp-test-02",
        "topic": "思考富足生活里突然袭来的空旷与匮乏",
        "genre": "modern",
        "max_lines": 20,
        "requirements": "12—20行，分2—4节；每节1—6行；使用现代汉语；不得出现任何诗人姓名。",
    },
    {
        "id": "exp-test-03",
        "topic": "写大雪将至前夜对时间流逝的恐惧与平静",
        "genre": "modern",
        "max_lines": 20,
        "requirements": "12—20行，分2—4节；每节1—6行；使用现代汉语；不得出现任何诗人姓名。",
    },
    {
        "id": "exp-test-04",
        "topic": "思考失败之后重新站起来的瞬间，不要写励志口号",
        "genre": "modern",
        "max_lines": 20,
        "requirements": "12—20行，分2—4节；每节1—6行；使用现代汉语；不得出现任何诗人姓名。",
    },
    {
        "id": "exp-test-05",
        "topic": "写旅途中在陌生小站醒来的片刻恍惚",
        "genre": "modern",
        "max_lines": 20,
        "requirements": "12—20行，分2—4节；每节1—6行；使用现代汉语；不得出现任何诗人姓名。",
    },
    {
        "id": "exp-test-06",
        "topic": "思考爱与距离：写相隔两地却同看一片夜空",
        "genre": "modern",
        "max_lines": 20,
        "requirements": "12—20行，分2—4节；每节1—6行；使用现代汉语；不得出现任何诗人姓名。",
    },
    {
        "id": "exp-test-07",
        "topic": "写把一件旧事彻底原谅并放下的傍晚",
        "genre": "modern",
        "max_lines": 20,
        "requirements": "12—20行，分2—4节；每节1—6行；使用现代汉语；不得出现任何诗人姓名。",
    },
    {
        "id": "exp-test-08",
        "topic": "写给十年后的自己，包含一句直白寄语，不要在结尾解释情绪",
        "genre": "modern",
        "max_lines": 20,
        "requirements": "12—20行，分2—4节；每节1—6行；包含一句写给十年后自己的直白寄语，不要在结尾解释情绪；不得出现任何诗人姓名。",
    },
]

INIT_EXPANSION_FOCUSES = (
    "具身选物与起跳方式：观察这批参考诗如何把抽象主题落在一两件最质朴、有重量的基础实物或身体动作上起跳，而不编造职场/买卖/家务流水账。",
    "空间纵深与原初尺度打开：观察这批参考诗如何从眼前切口迅速打开大地、黑夜、季节、水火、远方或生死的巨大背景，形成悬殊尺度对峙。",
    "发话位置与主客关系：观察这批参考诗中说话者（我/你/他者/万物）如何确立赤诚直接的命名、对话或守望关系，而非旁观式写实叙述。",
    "时间跨度与处境转折：观察这批参考诗如何折叠过去、今夜与一生的时间跨度，并在中后段发生关系或视角的推进与沉降。",
    "反小说化留白与删减法则：观察这批参考诗省略了哪些日常前因后果与世俗情节解释，从而让扩写只提供高密度关系支点而不锁死逐句剧情。",
    "熟套母题的陌生化反写：观察这批参考诗面对离别、孤独、家园、幸福、死亡等常见母题时，如何避开温情套话并转化为身体承受的真实重量。",
)

EXPANSION_INIT_SYSTEM = """你是一位现代诗诗学世界建构与创作构思专家。你会看到若干来自同一诗人的匿名参考作品。
请注意职责边界：下游已经有一个专门负责“语言句法、断行呼吸与修辞控制”的写诗模块（Step 3）。
你的任务不是归纳语言句法，也不是猜作者，而是从这批参考诗中**逆向归纳这位诗人的“立意与构思扩写法（Step 2）”**——即：当面对任何一句简短、抽象或开放的用户输入时，应当如何为下游写诗模块选定起跳物象、拉开空间与时间尺度、确立说话人关系并避开世俗琐碎故事链，写成一份精炼可迁移的“扩写指导 Prompt”。

硬性要求（正交边界契约）：
1. 精炼高密度：输出 4—6 条编号原则（可含一句简短总纲），总字数控制在 220—440 字（不超过 520 字）。
2. **严禁越界管语言与版式**：Prompt 中绝对禁止出现“标点、逗号、句号、分行、断行、跨行、行内空格、长短句、明喻、暗喻、排比、倒装、押韵、每节几行、总行数、总节数”等属于下游语言模块的字眼！只谈“选什么物、立什么尺度、定什么人称关系、给什么推进方向、避什么叙事俗套”。
3. 严禁写入具体示范名物词表或参考诗专有道具（如禁止写“麦地、麦穗、麦子、粮仓、草原、德令哈、青海湖、敦煌、马、木桶”等具体词表，防止跨题串味）！一律用抽象类别（如基础实物、身体部位、天象水土、时间跨度）表述机制。
4. 严禁把扩写变成编造完整的写实短篇小说剧情链（如禁止要求编排日常买卖、通勤办公、收发快递等前因后果流水账），只要求提炼高张力的起跳支点与关系推进势能。
5. 禁止出现任何诗人姓名、参考原句、“参考上面/这些诗”等依赖语，以及“富有诗意/意境深远”等空话。
6. 只输出 JSON，不要 markdown：
{"prompt": "完整扩写指导 Prompt", "design_notes": "从参考诗世界建构中归纳的依据简述", "covered_dimensions": ["imagery", "mythic_register", "progression", "addressivity", "emotion"]}"""

EXPANSION_RUNTIME_WRAPPER = """
请严格按照上述扩写指导原则，将用户输入的创作题目扩写为一份极简、高张力的“诗学立意支点 JSON”（绝不直接写诗句，绝不规定行数、标点或修辞手法，绝不编造冗长的日常故事流水账；严格尊重原题中的明示硬条件）。
只输出一个合法 JSON 对象，不要 markdown：
{
  "entry_anchor": "起跳的一件素朴可触实物或具身动作（不超过22字）",
  "world_scale": "由此推开的空间/时间/自然/存在大尺度对峙关系（不超过38字）",
  "stance_and_relation": "发话者位置、呼告朝向与情感温度（不超过28字）",
  "arc_turn": "全诗向纵深推进、陡转或沉降的关系方向（不超过32字）",
  "avoid": "本题须避开的世俗琐事因果链或陈词口号（不超过26字）"
}
"""

EXPANSION_ANALYZER_SYSTEM = """你是现代诗世界建构与构思诊断专家。你会看到：
1. 一组匿名参考诗（代表目标诗人的真实世界观、选物方式、尺度跨度与推进结构）；
2. 当前候选“前置扩写 Prompt（Step 2）”；
3. 按该扩写 Prompt 在多道通用短输入上产出的“扩写 JSON（anchor）”以及下游固定写诗器生成的诗作；
4. 匿名评审与离线指标给出的定量瓶颈摘要（最低分维度、反套路告警等）。

你的任务是诊断：**为什么当前 Step 2 扩写 Prompt 产出的立意支点还不够接近参考诗的世界建构方式，或者哪里束缚/带偏了下游成诗**。不要猜测作者身份。

重点审查：
1. 扩写出的起跳切口是否过于琐碎世俗（落入市民小品/职场家务因果链），还是过于空泛概念？
2. 扩写是否真正打开了参考诗特有的天地/时间/生命原初尺度（`mythic_register`）与身体承重感（`concreteness` / `emotion`）？
3. 扩写给出的 `arc_turn` 是否真正帮助下游实现了节间纵向推进（`progression`），还是导致原地踏步或规定过死？
4. Step 2 Prompt 本身有哪些无效、含糊、冲突或规定过死的条款？
5. 给出 3—4 条可直接用于修改 Step 2 Prompt 的建议（注意正交契约：**严禁建议加入标点、分行、空格、修辞禁令或行数节数等下游语言规则**，只改进选物、尺度、关系与推进立意机制）。

只输出 JSON，不要 markdown：
{
  "reproduced": [{"feature": "...", "generated_evidence": "...", "reference_evidence": "...", "claim_type": "observation|interpretation", "confidence": "low|medium|high"}],
  "missing": [{"feature": "...", "generated_evidence": "...", "reference_evidence": "...", "claim_type": "...", "confidence": "..."}],
  "extraneous": [{"feature": "...", "generated_evidence": "...", "claim_type": "...", "confidence": "..."}],
  "prompt_issues": [{"quote": "...", "issue_type": "ineffective|vague|redundant|conflicting|over_specific|template_inducing", "explanation": "...", "claim_type": "...", "confidence": "..."}],
  "topic_overreliance": {"assessment": "...", "evidence": "...", "claim_type": "...", "confidence": "..."},
  "summary": "直击核心扩写瓶颈的总结",
  "actionable_suggestions": ["...", "..."]
}"""

EXPANSION_MUTATOR_SYSTEM = """你是“前置扩写 Prompt（Step 2）演化变异器”。你会收到父代扩写 Prompt、参考诗对比诊断与本轮变异策略方向。
你的任务是优化“指导如何将简短题目扩写为诗学立意支点的 Prompt”，绝不直接写诗，也绝不越界管语言分行。

硬性要求（正交边界契约）：
1. 必须产生实质改进（不得原样返回父代），保持 4—6 条编号原则，总字数控制在 220—440 字（上限 520 字）。
2. **严禁越界管下游句法与版式**：绝对禁止出现“标点、逗号、句号、分行、断行、跨行、行内空格、长短句、明喻、暗喻、排比、倒装、押韵、每节、总行数、总节数”等字眼！
3. 严禁写入具体示范名物词表（如麦地、麦穗、草原、德令哈、木桶、马等）或示范台词，防止跨题串味照搬。
4. 严禁要求编造日常买卖/通勤/琐事流水账剧本，聚焦“素朴具身切口 + 原初大尺度对峙 + 赤诚关系位置 + 纵向跃迁势能 + 留白不锁死剧情”。
5. 禁止诗人姓名、参考原句、依赖参考语及空泛套话。只输出 JSON，不要 markdown：
{"prompt": "完整子代扩写 Prompt", "changes": [{"op": "replace|delete|merge|adjust|add|conflict_fix", "target": "...", "reason": "..."}], "preserved": ["..."], "summary": "一句话说明核心改进"}"""

EXPANSION_CROSSOVER_SYSTEM = """你是“前置扩写 Prompt（Step 2）语义重组器”。你会收到两份互补的优秀扩写父代（Parent A 与 Parent B）及其维度表现摘要。
请将两者的核心优势真正融合为一份统一、无冲突、220—440 字（4—6 条原则）的子代扩写 Prompt：
1. **严守正交边界**：绝对禁止出现“标点、逗号、句号、分行、断行、跨行、行内空格、长短句、明喻、暗喻、排比、倒装、押韵、每节、总行数、总节数”等下游语言版式字眼；
2. 严禁具体示范名物词表、诗人姓名、参考原句、依赖语及写实故事流水账；
3. 只输出 JSON，不要 markdown：
{"prompt": "融合后的完整子代扩写 Prompt", "from_parent_a": ["..."], "from_parent_b": ["..."], "resolved_conflicts": ["..."], "summary": "一句话说明重组优势"}"""

EXPANSION_MUTATION_STRATEGIES = (
    ("scale_and_embodiment", "强化具身切口与原初大尺度正撞：针对原初尺度或情感张力偏弱的问题，让起跳实物/身体触感更直接地接入天地、时间与生命重量，彻底剥离市民生活琐事感。"),
    ("arc_and_restraint", "强化纵向转折势能与去剧本化减重：删去把情节规定过死的繁琐条款，让扩写给出清晰的中后段关系陡转方向，同时给下游留足呼吸空间。"),
    ("stance_and_defamiliarization", "强化赤诚发话位置与母题陌生化反写：针对常见抽象母题容易滑向普通抒情套话的问题，明确说话者与呼告对象的切近关系及反俗套切入角。"),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _short_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def validate_expansion_prompt(prompt: str, config: dict, selection: dict) -> dict:
    rules = {
        **config["prompt_rules"],
        "min_prompt_chars": 140,
        "max_prompt_chars": 520,
    }
    base = validate_prompt(
        prompt, rules=rules, references=selection["references"],
        target_name=selection["target_name"], target_aliases=selection.get("target_aliases"),
        min_chars=140, max_chars=520,
    )
    errors = list(base["errors"])
    intrusions = [term for term in FORBIDDEN_STEP3_INTRUSIONS if term in (prompt or "")]
    if intrusions:
        errors.append(
            "违反 Step-2/Step-3 正交职责契约，出现了下游语言/分行/修辞专有词：" + "、".join(intrusions) +
            "；请删去所有句法版式字眼，只描述选物、空间时间尺度、人物关系与推进立意"
        )
    return {**base, "ok": not errors, "errors": errors}


def validate_expansion_anchor(data) -> list[str]:
    issues = []
    if not isinstance(data, dict):
        return ["扩写输出必须是 JSON 对象"]
    required_caps = {
        "entry_anchor": 45,
        "world_scale": 70,
        "stance_and_relation": 55,
        "arc_turn": 65,
        "avoid": 55,
    }
    combined = []
    for key, cap in required_caps.items():
        val = data.get(key)
        if not isinstance(val, str) or not val.strip():
            issues.append(f"缺少非空字段 {key}")
        elif len(val.strip()) > cap:
            issues.append(f"{key} 过长（>{cap}字），不得写成完整故事大纲")
        else:
            combined.append(val.strip())
    joined = " ".join(combined)
    bad = [t for t in ("标点", "逗号", "句号", "分行", "断行", "行内空格", "总行数", "每节") if t in joined]
    if bad:
        issues.append("扩写内容越界规定了版式/标点：" + "、".join(bad))
    return issues


def expand_topic(llm, expansion_prompt: str, topic: dict, *, cache_variant: str) -> dict:
    payload = {
        "kind": "rpe_expand_topic",
        "topic": topic["topic"],
        "explicit_requirements": topic.get("requirements", ""),
    }
    data, meta = llm.call_json(
        purpose="rpe_expand_topic",
        system=expansion_prompt.strip() + "\n" + EXPANSION_RUNTIME_WRAPPER,
        user=json.dumps(payload, ensure_ascii=False),
        max_tokens=600,
        temperature=0.65,
        thinking="disabled",
        validator=validate_expansion_anchor,
        cache_variant=cache_variant,
    )
    return {"anchor": data, "meta": meta}


def build_expanded_topic(topic: dict, anchor: dict) -> dict:
    expansion_note = (
        "【诗学构思支点（用于确立切口、尺度与关系方向，不可覆盖原题硬要求，不要把支点说明文字照抄进诗句）】\n"
        f"- 起跳切口：{anchor['entry_anchor']}\n"
        f"- 尺度关系：{anchor['world_scale']}\n"
        f"- 发话姿态：{anchor['stance_and_relation']}\n"
        f"- 推进转折：{anchor['arc_turn']}\n"
        f"- 避开俗套：{anchor['avoid']}"
    )
    req = topic.get("requirements", "").strip()
    return {
        **topic,
        "requirements": f"{req}\n{expansion_note}".strip(),
    }


def make_expansion_prompt_candidate(
    llm, config, selection, *, focus: str, index: int, total: int, mode: str = "population", cache_tag: str = "exp-init-0"
) -> dict:
    attempts = []
    payload = {
        "kind": "rpe_init_expansion" if mode == "population" else "rpe_reverse_expansion_once",
        "mode": mode,
        "candidate_index": index,
        "candidate_total": total,
        "focus": focus,
        "reference_poems": anonymous_references(selection["references"]),
        "orthogonal_contract": {
            "chars_range": [160, 520],
            "ideal_chars": [220, 420],
            "forbidden_step3_terms": list(FORBIDDEN_STEP3_INTRUSIONS),
        },
    }
    data, meta = llm.call_json(
        purpose=payload["kind"],
        system=EXPANSION_INIT_SYSTEM,
        user=json.dumps(payload, ensure_ascii=False),
        max_tokens=1400,
        temperature=0.9 if mode == "population" else 0.65,
        thinking="disabled",
        validator=validate_initializer,
        cache_variant=cache_tag,
    )
    prompt = data.get("prompt", "").strip()
    validation = validate_expansion_prompt(prompt, config, selection)
    attempts.append({"attempt": 1, "validation": validation, "meta": meta})
    for repair in range(2):
        if validation["ok"]:
            break
        retry_payload = {
            **payload,
            "_previous_draft": prompt,
            "_validation_feedback": "上一版未通过正交/安全校验：" + "；".join(validation["errors"]) + "。请完整重写并严格删除所有违规词。",
        }
        data, meta = llm.call_json(
            purpose=payload["kind"],
            system=EXPANSION_INIT_SYSTEM,
            user=json.dumps(retry_payload, ensure_ascii=False),
            max_tokens=1400,
            temperature=0.75,
            thinking="disabled",
            validator=validate_initializer,
            cache_variant=f"{cache_tag}:repair{repair + 1}",
        )
        prompt = data.get("prompt", "").strip()
        validation = validate_expansion_prompt(prompt, config, selection)
        attempts.append({"attempt": repair + 2, "validation": validation, "meta": meta})
    return {
        "origin": "initializer" if mode == "population" else "one_shot_reverse",
        "focus": focus,
        "prompt": prompt,
        "design_notes": data.get("design_notes", ""),
        "covered_dimensions": data.get("covered_dimensions", []),
        "valid": validation["ok"],
        "validation": validation,
        "attempts": attempts,
    }


def evaluate_expansion_candidate(
    llm, judge_llm, config, selection, style_prompt: str, candidate: dict, topics: list[dict],
    *, repetitions: int = 1, repetition_offset: int = 0, kind: str = "references"
) -> dict:
    ref_texts = [p["text"] for p in selection[kind]]
    copy_texts = list(ref_texts) + ([p["text"] for p in selection["references"]] if kind == "held_out" else [])
    rubric_tag = config["evaluation"].get("rubric_version", "rpe-poetry-zh-v3")
    jobs = [(t, r) for t in topics for r in range(repetition_offset, repetition_offset + repetitions)]

    def _run_one(job):
        topic, rep = job
        cid = candidate["id"]
        try:
            exp = expand_topic(llm, candidate["prompt"], topic, cache_variant=f"exp:{cid}:{topic['id']}:rep{rep}:{kind}")
            expanded_topic = build_expanded_topic(topic, exp["anchor"])
            gen = generator.generate_poem(
                llm, config, style_prompt, expanded_topic,
                cache_variant=f"expgen:{cid}:{topic['id']}:rep{rep}:{kind}",
            )
            if not gen["ok"]:
                return {"topic_id": topic["id"], "topic": topic["topic"], "repetition": rep, "ok": False, "anchor": exp["anchor"], "generation": gen}
            det = metrics.style_similarity(gen["text"], ref_texts)
            copy = metrics.copy_diagnostics(gen["text"], copy_texts, lcs_chars=12, line_chars=8, rouge1_cap=0.80)
            rouge = [metrics.rouge1_char(gen["text"], ref) for ref in ref_texts]
            judge, jmeta = evaluator.judge_poem(
                judge_llm, config, selection, topic, gen, kind=kind,
                cache_variant=f"expjudge:{cid}:{topic['id']}:rep{rep}:{kind}:{rubric_tag}",
            )
            comp = evaluator._per_poem_fitness(config, det, judge, gen["form_ok"], copy)
            # Penalize overly verbose expansion anchors (>145 total chars) so Step-2 stays a crisp launchpad
            anchor_chars = sum(len(str(exp["anchor"].get(k, ""))) for k in ("entry_anchor", "world_scale", "stance_and_relation", "arc_turn", "avoid"))
            if anchor_chars > 145:
                over_pen = min(4.0, (anchor_chars - 145) * 0.08)
                comp["fitness"] = round(max(0.0, comp["fitness"] - over_pen), 4)
                comp["anchor_length_penalty"] = round(over_pen, 4)
            comp["anchor_chars"] = anchor_chars
            return {
                "topic_id": topic["id"],
                "topic": topic["topic"],
                "repetition": rep,
                "ok": True,
                "anchor": exp["anchor"],
                "generation": gen,
                "deterministic": det,
                "copy_diagnostics": copy,
                "rouge1_diagnostic": {"mean_f1": round(statistics.mean(x["f1"] for x in rouge), 6)},
                "judge": judge,
                "judge_meta": jmeta,
                "components": comp,
            }
        except BudgetExhausted:
            raise
        except Exception as exc:
            return {"topic_id": topic["id"], "topic": topic["topic"], "repetition": rep, "ok": False, "error": str(exc)}

    is_mock = bool(getattr(llm, "mock", True))
    if is_mock or len(jobs) <= 1:
        rows = [_run_one(j) for j in jobs]
    else:
        with ThreadPoolExecutor(max_workers=min(6, len(jobs))) as pool:
            rows = list(pool.map(_run_one, jobs))

    ev_cfg = {
        **config,
        "evaluation": {**config["evaluation"], "prompt_length_free": 440},
    }
    return evaluator.aggregate_evaluations(candidate, rows, ev_cfg)


def analyze_expansion_candidate(llm, config, candidate: dict, evaluation: dict, selection: dict) -> dict:
    ok_rows = [r for r in evaluation.get("evaluations", []) if r.get("ok")]
    if not ok_rows:
        return {
            "reproduced": [], "missing": [], "extraneous": [], "prompt_issues": [],
            "summary": "无可用样本，采用保守精炼建议。",
            "actionable_suggestions": ["强化素朴实物切口与原初尺度碰撞，删去繁琐限制。"],
            "fallback": True,
        }
    dim_means = {}
    weak_notes = {}
    for dim in STYLE_DIMENSIONS:
        vals = [r["judge"]["dimensions"][dim]["score"] for r in ok_rows if dim in r.get("judge", {}).get("dimensions", {})]
        if vals:
            dim_means[dim] = round(statistics.mean(vals), 2)
    ordered_weak = sorted(dim_means.items(), key=lambda kv: kv[1])
    for dim, _ in ordered_weak[:4]:
        rats = []
        for r in ok_rows:
            rt = r["judge"]["dimensions"].get(dim, {}).get("rationale")
            if rt and rt not in rats:
                rats.append(rt)
        weak_notes[dim] = rats[:2]

    samples = []
    for r in ok_rows[:5]:
        samples.append({
            "topic": r["topic"],
            "expansion_anchor": r.get("anchor"),
            "poem_title": r["generation"]["title"],
            "poem_text": r["generation"]["text"],
            "style_score": r["components"]["style_score"],
            "judge_overall": r["judge"].get("overall_notes", ""),
        })

    payload = {
        "kind": "rpe_analyze_expansion",
        "reference_poems": anonymous_references(selection["references"]),
        "candidate_expansion_prompt": candidate["prompt"],
        "evaluation_digest": {
            "eligible_rate": evaluation.get("eligible_rate"),
            "eligible_style": evaluation.get("eligible_style"),
            "literary_quality_score": evaluation.get("literary_quality_score"),
            "weakest_dimensions": ordered_weak[:5],
            "weakest_rationales": weak_notes,
        },
        "generated_samples": samples,
    }
    try:
        data, _ = llm.call_json(
            purpose="rpe_analyze_expansion",
            system=EXPANSION_ANALYZER_SYSTEM,
            user=json.dumps(payload, ensure_ascii=False),
            max_tokens=3200,
            temperature=0.2,
            thinking="disabled",
            validator=validate_analysis,
            cache_variant=f"{candidate['id']}:exp_analysis:v1",
        )
        data["fallback"] = False
        return data
    except BudgetExhausted:
        raise
    except Exception as exc:
        return {
            "reproduced": [], "missing": [], "extraneous": [], "prompt_issues": [],
            "summary": f"分析回退：{exc}",
            "actionable_suggestions": ["强化具身实物直撞天地时间大尺度，剥离日常琐事流水账，保持正交边界。"],
            "fallback": True,
        }


def mutate_expansion_candidate(llm, config, parent: dict, analysis: dict, selection: dict, *, gen_idx: int, slot: int) -> dict:
    strategy = EXPANSION_MUTATION_STRATEGIES[1] if len(parent["prompt"]) > 440 else EXPANSION_MUTATION_STRATEGIES[(gen_idx + slot) % len(EXPANSION_MUTATION_STRATEGIES)]
    payload = {
        "kind": "rpe_mutate_expansion",
        "strategy": {"name": strategy[0], "guidance": strategy[1]},
        "parent_prompt": parent["prompt"],
        "analysis": {k: analysis.get(k) for k in ("reproduced", "missing", "extraneous", "prompt_issues", "summary", "actionable_suggestions")},
        "orthogonal_contract": {"chars_range": [160, 520], "ideal_chars": [220, 420], "forbidden_step3_terms": list(FORBIDDEN_STEP3_INTRUSIONS)},
    }
    tag = f"{parent['id']}:expmut:g{gen_idx:02d}:{slot}:{strategy[0]}"
    data, meta = llm.call_json(
        purpose="rpe_mutate_expansion",
        system=EXPANSION_MUTATOR_SYSTEM,
        user=json.dumps(payload, ensure_ascii=False),
        max_tokens=1500,
        temperature=0.8,
        thinking="disabled",
        validator=validate_mutation,
        cache_variant=tag,
    )
    prompt = data.get("prompt", "").strip()
    val = validate_expansion_prompt(prompt, config, selection)
    if prompt == parent["prompt"].strip():
        val = {**val, "ok": False, "errors": list(val["errors"]) + ["与父代完全相同"]}
    for repair in range(2):
        if val["ok"]:
            break
        r_payload = {**payload, "_previous_draft": prompt, "_validation_feedback": "校验未通过：" + "；".join(val["errors"]) + "。请完整重写并严格剔除违规字眼。"}
        data, meta = llm.call_json(
            purpose="rpe_mutate_expansion",
            system=EXPANSION_MUTATOR_SYSTEM,
            user=json.dumps(r_payload, ensure_ascii=False),
            max_tokens=1500,
            temperature=0.75,
            thinking="disabled",
            validator=validate_mutation,
            cache_variant=f"{tag}:repair{repair + 1}",
        )
        prompt = data.get("prompt", "").strip()
        val = validate_expansion_prompt(prompt, config, selection)
        if prompt == parent["prompt"].strip():
            val = {**val, "ok": False, "errors": list(val["errors"]) + ["与父代完全相同"]}
    return {
        "prompt": prompt,
        "valid": val["ok"],
        "validation": val,
        "strategy": strategy[0],
        "changes": data.get("changes", []),
        "summary": data.get("summary", ""),
    }


def crossover_expansion_candidates(llm, config, pa: dict, pb: dict, selection: dict, *, gen_idx: int, pair_idx: int) -> dict:
    def _digest(c):
        ev = c.get("evaluation") or {}
        ok = [r for r in ev.get("evaluations", []) if r.get("ok")]
        dims = {d: round(statistics.mean(r["judge"]["dimensions"][d]["score"] for r in ok), 2) for d in STYLE_DIMENSIONS if ok}
        return {
            "id": c["id"],
            "eligible_rate": ev.get("eligible_rate"),
            "eligible_style": ev.get("eligible_style"),
            "strongest": sorted(dims.items(), key=lambda kv: kv[1], reverse=True)[:4],
            "weakest": sorted(dims.items(), key=lambda kv: kv[1])[:3],
            "prompt": c["prompt"],
        }

    payload = {
        "kind": "rpe_crossover_expansion",
        "parent_a": _digest(pa),
        "parent_b": _digest(pb),
        "orthogonal_contract": {"chars_range": [160, 520], "ideal_chars": [220, 420], "forbidden_step3_terms": list(FORBIDDEN_STEP3_INTRUSIONS)},
    }
    tag = f"{pa['id']}x{pb['id']}:expx:g{gen_idx:02d}:{pair_idx}"
    data, meta = llm.call_json(
        purpose="rpe_crossover_expansion",
        system=EXPANSION_CROSSOVER_SYSTEM,
        user=json.dumps(payload, ensure_ascii=False),
        max_tokens=1500,
        temperature=0.8,
        thinking="disabled",
        validator=validate_crossover,
        cache_variant=tag,
    )
    prompt = data.get("prompt", "").strip()
    val = validate_expansion_prompt(prompt, config, selection)
    if prompt in (pa["prompt"].strip(), pb["prompt"].strip()):
        val = {**val, "ok": False, "errors": list(val["errors"]) + ["与某一父代完全相同"]}
    for repair in range(2):
        if val["ok"]:
            break
        r_payload = {**payload, "_previous_draft": prompt, "_validation_feedback": "校验未通过：" + "；".join(val["errors"]) + "。请完整重写并剔除所有违规词。"}
        data, meta = llm.call_json(
            purpose="rpe_crossover_expansion",
            system=EXPANSION_CROSSOVER_SYSTEM,
            user=json.dumps(r_payload, ensure_ascii=False),
            max_tokens=1500,
            temperature=0.75,
            thinking="disabled",
            validator=validate_crossover,
            cache_variant=f"{tag}:repair{repair + 1}",
        )
        prompt = data.get("prompt", "").strip()
        val = validate_expansion_prompt(prompt, config, selection)
        if prompt in (pa["prompt"].strip(), pb["prompt"].strip()):
            val = {**val, "ok": False, "errors": list(val["errors"]) + ["与某一父代完全相同"]}
    return {
        "prompt": prompt,
        "valid": val["ok"],
        "validation": val,
        "summary": data.get("summary", ""),
    }


def _rank_key(cand: dict):
    ev = cand.get("evaluation") or {}
    return (
        1 if ev.get("fitness") is not None else 0,
        *evaluator.selection_objective(ev),
        float(ev.get("fitness") or 0.0),
        float(ev.get("literary_quality_score") or 0.0),
        -float(ev.get("score_std") or 0.0),
    )


def _sync_ea_report_live(run_dir: Path, state: dict, is_mock: bool) -> None:
    if is_mock:
        return
    try:
        from experiments.reverse_prompt_engineering.store import _write_run_progress

        ledger = run_dir / "ledger.jsonl"
        calls = tokens = hits = 0
        if ledger.exists():
            for line in ledger.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    if row.get("cache_hit"):
                        hits += 1
                    else:
                        calls += 1
                        tokens += int(row.get("total_tokens") or 0)
        lines = [
            LIVE_START,
            f"- **更新时间（UTC）**：`{utc_now()}`",
            f"- **当前活跃运行**：`{state['run_id']}`（Step-2 扩写引擎 RPE-GA · 锁定下游 `Style-v4`）",
            f"- **实时阶段**：`{state.get('stage', 'running')}`（已完成至第 `{state.get('generation', 0)}` 代）",
            f"- **本轮实时累计调用**：`{calls}` 次真实调用 / `{tokens:,}` tokens（缓存命中 `{hits}` 次）",
            "",
        ]
        if state.get("history"):
            lines.extend([
                "#### Step-2 扩写引擎实时演化轨迹",
                "",
                "| 代 | 领先候选 | 合格率 | 合格风格分 | 综合适应度 | 文学质量 |",
                "|---:|---|---:|---:|---:|---:|",
            ])
            for h in state["history"]:
                lines.append(
                    f"| {h['generation']} | `{h['leader']}` | {h['eligible_rate']:.2f} | "
                    f"{(h['eligible_style'] or 0):.2f} | {(h['fitness'] or 0):.2f} | {(h['quality'] or 0):.2f} |"
                )
            lines.append("")
        pop = state.get("population_summary") or []
        if pop:
            lines.extend([
                "#### 当前扩写种群排行榜",
                "",
                "| 排名 | 候选 ID | 来源 | 合格率 | 合格风格分 | 适应度 | 评估篇数 | 字数 |",
                "|---:|---|---|---:|---:|---:|---:|---:|",
            ])
            for idx, c in enumerate(pop[:6], 1):
                lines.append(
                    f"| {idx} | `{c['id']}` | `{c['origin']}` | {c['eligible_rate']:.2f} | "
                    f"{(c['eligible_style'] or 0):.2f} | {(c['fitness'] or 0):.2f} | {c['evals']} | {c['chars']} |"
                )
            lines.append("")
            if pop[0].get("prompt"):
                lines.extend([
                    f"#### 当前领先 Step-2 扩写 Prompt（`{pop[0]['id']}`，{pop[0]['chars']} 字）",
                    "",
                    "```text",
                    pop[0]["prompt"],
                    "```",
                    "",
                ])
        lines.append(LIVE_END)
        _write_run_progress(run_dir, "\n".join(lines))
    except OSError:
        pass


def run_expansion_experiment(
    *, run_id: str = "live-haizi-expand-v1-01", mode: str = "mock",
    pop_size: int = 6, generations: int = 4, crossover_count: int = 2,
    opt_topics: list[dict] | None = None, test_topics: list[dict] | None = None,
    bench_reps: int = 2, resume: bool = False,
) -> dict:
    cfg = load_config(PROJECT_ROOT / "experiments/reverse_prompt_engineering/config.yaml")
    cfg["budget"]["max_api_calls"] = max(int(cfg["budget"]["max_api_calls"]), 5000)
    cfg["budget"]["max_total_tokens"] = max(int(cfg["budget"]["max_total_tokens"]), 30_000_000)
    sel = load_selection(cfg, PROJECT_ROOT)
    style_prompt = (PROJECT_ROOT / "experiments/reverse_prompt_engineering/optimal_style_prompt_v4.txt").read_text(encoding="utf-8").strip()
    style_hash = hashlib.sha256(style_prompt.encode("utf-8")).hexdigest()
    if style_hash != "0af51f859e13cc77472f7fe28f507c3535bdbb18ecfc4120c4e7bfe5c73407fd":
        raise ValueError("扩写实验所需的 v4 写诗提示词与归档候选 g01-x01-0af51f85 不一致")
    opt_topics = opt_topics or EXPANSION_OPT_TOPICS
    test_topics = test_topics or EXPANSION_TEST_TOPICS

    run_dir = PROJECT_ROOT / "experiments/reverse_prompt_engineering/runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    is_mock = (mode == "mock")
    # Cache-only directories can seed a new experiment. Recompute all scores in it.
    manifest_path = run_dir / "run.json"
    manifest = {
        "mode": mode, "locked_step3_prompt_sha256": style_hash,
        "feature_schema": metrics.FEATURE_SCHEMA,
        "rubric_version": cfg["evaluation"]["rubric_version"],
        "evaluation": cfg["evaluation"], "generation": cfg["generation"],
        "selection_sha256": digest(sel), "optimization_topics": opt_topics, "test_topics": test_topics,
        "pop_size": pop_size, "generations": generations, "crossover_count": crossover_count,
        "bench_reps": bench_reps,
    }
    if manifest_path.exists():
        if not resume or json.loads(manifest_path.read_text(encoding="utf-8")) != manifest:
            raise ValueError("运行目录已使用，请以相同配置续跑或使用新的 run-id")
        state_path = run_dir / "state.json"
        if resume and state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            if state.get("stage") == "completed":
                report_path = run_dir / "expand_report.json"
                if not report_path.exists():
                    raise RuntimeError("运行状态标记为 completed，但缺少 expand_report.json")
                return json.loads(report_path.read_text(encoding="utf-8"))
    elif any(p.name != "cache.jsonl" for p in run_dir.iterdir()):
        raise ValueError("旧运行缺少可核对的评分配置；请在新的 run-id 中复用缓存并重新评分")
    else:
        atomic_write(manifest_path, manifest)
    if is_mock:
        llm = make_mock_llm(cfg, run_dir)
        judge_llm = llm
    else:
        llm, judge_llm, _ = make_live_llms(cfg, run_dir, project_root=PROJECT_ROOT)
        if resume and (run_dir / "ledger.jsonl").exists():
            restore_budget_from_ledger(llm.budget, run_dir / "ledger.jsonl")

    state_path = run_dir / "state.json"

    def _save_progress(stage: str, gen: int, pop: list[dict], history: list[dict], extra: dict | None = None):
        ranked = sorted(pop, key=_rank_key, reverse=True)
        pop_sum = []
        for c in ranked:
            ev = c.get("evaluation") or {}
            pop_sum.append({
                "id": c["id"],
                "origin": c["origin"],
                "parent_id": c.get("parent_id"),
                "eligible_rate": ev.get("eligible_rate") or 0.0,
                "eligible_style": ev.get("eligible_style"),
                "fitness": ev.get("fitness"),
                "quality": ev.get("literary_quality_score"),
                "evals": ev.get("evaluation_count") or 0,
                "chars": len(c.get("prompt", "")),
                "prompt": c.get("prompt", ""),
            })
        payload = {
            "run_id": run_id,
            "mode": mode,
            "stage": stage,
            "generation": gen,
            "history": history,
            "population_summary": pop_sum,
            "updated_at": utc_now(),
        }
        if extra:
            payload.update(extra)
        atomic_write(state_path, payload)
        _sync_ea_report_live(run_dir, payload, is_mock)

    def _extend_reps(cand: dict, target_reps: int):
        old = (cand.get("evaluation") or {}).get("evaluations", [])
        cur_reps = len(old) // max(1, len(opt_topics))
        needed = target_reps - cur_reps
        if needed <= 0:
            return
        max_rep = max((r.get("repetition", -1) for r in old), default=-1)
        extra = evaluate_expansion_candidate(
            llm, judge_llm, cfg, sel, style_prompt, cand, opt_topics,
            repetitions=needed, repetition_offset=max_rep + 1, kind="references",
        )
        merged = old + extra.get("evaluations", [])
        ev_cfg = {**cfg, "evaluation": {**cfg["evaluation"], "prompt_length_free": 440}}
        cand["evaluation"] = evaluator.aggregate_evaluations(cand, merged, ev_cfg)
        atomic_write(run_dir / f"eval_{cand['id']}.json", cand["evaluation"])

    # Phase 1: Unbiased Reverse Initialization from 15 Reference Poems
    population = []
    history = []
    for idx in range(pop_size):
        focus = INIT_EXPANSION_FOCUSES[idx % len(INIT_EXPANSION_FOCUSES)]
        rec = make_expansion_prompt_candidate(
            llm, cfg, sel, focus=focus, index=idx, total=pop_size,
            mode="population", cache_tag=f"exp-init-v1-{idx}",
        )
        cid = f"eg00-i{idx:02d}-{_short_hash(rec['prompt'])}"
        cand = {
            "id": cid,
            "prompt": rec["prompt"],
            "origin": "initializer",
            "parent_id": None,
            "generation": 0,
            "valid": rec["valid"],
            "validation": rec["validation"],
            "design_notes": rec["design_notes"],
        }
        if cand["valid"]:
            cand["evaluation"] = evaluate_expansion_candidate(
                llm, judge_llm, cfg, sel, style_prompt, cand, opt_topics, repetitions=1, kind="references",
            )
            atomic_write(run_dir / f"eval_{cid}.json", cand["evaluation"])
            population.append(cand)
            _save_progress(f"Phase 1 逆向初始化 ({idx + 1}/{pop_size})", 0, population, history)

    if not population:
        raise RuntimeError("Step-2 逆向初始化未产生有效候选 Prompt")

    population.sort(key=_rank_key, reverse=True)
    for top_c in population[:2]:
        _extend_reps(top_c, target_reps=2)
    population.sort(key=_rank_key, reverse=True)
    history.append({
        "generation": 0,
        "leader": population[0]["id"],
        "eligible_rate": population[0]["evaluation"]["eligible_rate"],
        "eligible_style": population[0]["evaluation"]["eligible_style"],
        "fitness": population[0]["evaluation"]["fitness"],
        "quality": population[0]["evaluation"]["literary_quality_score"],
    })
    _save_progress("Phase 1 完成（进入多代演化）", 0, population, history)

    # Phases 4-6: Evolution Loop
    best_obj = evaluator.selection_objective(population[0]["evaluation"])
    stale = 0
    for g in range(1, generations + 1):
        children = []
        for slot, parent in enumerate(population):
            analysis = analyze_expansion_candidate(llm, cfg, parent, parent["evaluation"], sel)
            atomic_write(run_dir / f"analysis_{parent['id']}_g{g:02d}.json", analysis)
            try:
                mut = mutate_expansion_candidate(llm, cfg, parent, analysis, sel, gen_idx=g, slot=slot)
                cid = f"eg{g:02d}-m{slot:02d}-{_short_hash(mut['prompt'])}"
                child = {
                    "id": cid, "prompt": mut["prompt"], "origin": "mutation",
                    "parent_id": parent["id"], "generation": g,
                    "valid": mut["valid"], "validation": mut["validation"],
                    "summary": mut["summary"],
                }
                if child["valid"]:
                    child["evaluation"] = evaluate_expansion_candidate(
                        llm, judge_llm, cfg, sel, style_prompt, child, opt_topics, repetitions=1, kind="references",
                    )
                    atomic_write(run_dir / f"eval_{cid}.json", child["evaluation"])
                children.append(child)
            except (LLMOutputError, RuntimeError) as exc:
                if isinstance(exc, RuntimeError) and not is_output_truncation_error(exc):
                    raise
            _save_progress(f"第 {g} 代变异演化中 ({slot + 1}/{len(population)})", g - 1, population + [c for c in children if c.get("evaluation")], history)

        # Semantic Crossover on distinct top parents
        ranked_parents = sorted(population, key=_rank_key, reverse=True)
        pairs = []
        for i in range(len(ranked_parents)):
            for j in range(i + 1, len(ranked_parents)):
                if metrics.prompt_similarity(ranked_parents[i]["prompt"], ranked_parents[j]["prompt"]) < 0.92:
                    pairs.append((ranked_parents[i], ranked_parents[j]))
                if len(pairs) >= crossover_count:
                    break
            if len(pairs) >= crossover_count:
                break
        for p_idx, (pa, pb) in enumerate(pairs):
            try:
                xrec = crossover_expansion_candidates(llm, cfg, pa, pb, sel, gen_idx=g, pair_idx=p_idx)
                cid = f"eg{g:02d}-x{p_idx:02d}-{_short_hash(xrec['prompt'])}"
                xchild = {
                    "id": cid, "prompt": xrec["prompt"], "origin": "crossover",
                    "parent_id": f"{pa['id']}+{pb['id']}", "generation": g,
                    "valid": xrec["valid"], "validation": xrec["validation"],
                    "summary": xrec["summary"],
                }
                if xchild["valid"]:
                    xchild["evaluation"] = evaluate_expansion_candidate(
                        llm, judge_llm, cfg, sel, style_prompt, xchild, opt_topics, repetitions=1, kind="references",
                    )
                    atomic_write(run_dir / f"eval_{cid}.json", xchild["evaluation"])
                children.append(xchild)
            except (LLMOutputError, RuntimeError) as exc:
                if isinstance(exc, RuntimeError) and not is_output_truncation_error(exc):
                    raise

        # Similarity-niched (μ+λ) survivor selection (< 0.88)
        pool = [c for c in population + children if c.get("valid") and c.get("evaluation")]
        pool.sort(key=_rank_key, reverse=True)
        survivors, seen = [], set()
        for c in pool:
            txt = c["prompt"]
            if txt in seen:
                continue
            if survivors and any(metrics.prompt_similarity(txt, s["prompt"]) >= 0.88 for s in survivors):
                continue
            seen.add(txt)
            survivors.append(c)
            if len(survivors) >= pop_size:
                break
        if len(survivors) < pop_size:
            for c in pool:
                if c not in survivors:
                    survivors.append(c)
                if len(survivors) >= pop_size:
                    break

        # Confirm top-2 survivors to 2 repetitions + symmetric AB+BA pairwise tiebreak
        for top_c in survivors[:2]:
            _extend_reps(top_c, target_reps=2)
        for c in survivors:
            c["evaluation"]["pairwise_tiebreak_bonus"] = 0.0
        survivors.sort(key=_rank_key, reverse=True)
        if len(survivors) >= 2 and survivors[0]["evaluation"]["eligible_rate"] == survivors[1]["evaluation"]["eligible_rate"]:
            s0 = survivors[0]["evaluation"].get("eligible_style") or 0.0
            s1 = survivors[1]["evaluation"].get("eligible_style") or 0.0
            if abs(s0 - s1) <= 2.5:
                pw = evaluator.pairwise_compare_candidates(judge_llm, cfg, survivors[0], survivors[1], sel, kind="references")
                survivors[0]["evaluation"]["pairwise_tiebreak_bonus"] = pw["bonus_a"]
                survivors[1]["evaluation"]["pairwise_tiebreak_bonus"] = round(-pw["bonus_a"], 4)
                survivors.sort(key=_rank_key, reverse=True)

        population = survivors
        cur_obj = evaluator.selection_objective(population[0]["evaluation"])
        if cur_obj[0] > best_obj[0] or (cur_obj[0] == best_obj[0] and cur_obj[1] > best_obj[1] + 0.20):
            best_obj = cur_obj
            stale = 0
        else:
            stale += 1

        history.append({
            "generation": g,
            "leader": population[0]["id"],
            "eligible_rate": population[0]["evaluation"]["eligible_rate"],
            "eligible_style": population[0]["evaluation"]["eligible_style"],
            "fitness": population[0]["evaluation"]["fitness"],
            "quality": population[0]["evaluation"]["literary_quality_score"],
            "stale": stale,
        })
        _save_progress(f"已完成第 {g} 代演化", g, population, history)
        if stale >= 2 and g >= 3:
            break

    # Final confirmation of all survivors to 2 repetitions
    for c in population:
        _extend_reps(c, target_reps=2)
    for c in population:
        c["evaluation"]["pairwise_tiebreak_bonus"] = 0.0
    population.sort(key=_rank_key, reverse=True)
    final_pw = None
    if len(population) >= 2 and population[0]["evaluation"]["eligible_rate"] == population[1]["evaluation"]["eligible_rate"]:
        s0 = population[0]["evaluation"].get("eligible_style") or 0.0
        s1 = population[1]["evaluation"].get("eligible_style") or 0.0
        if abs(s0 - s1) <= 2.5:
            final_pw = evaluator.pairwise_compare_candidates(judge_llm, cfg, population[0], population[1], sel, kind="references")
            population[0]["evaluation"]["pairwise_tiebreak_bonus"] = final_pw["bonus_a"]
            population[1]["evaluation"]["pairwise_tiebreak_bonus"] = round(-final_pw["bonus_a"], 4)
            population.sort(key=_rank_key, reverse=True)

    champion = population[0]
    atomic_write(run_dir / "final_population.json", {"best_id": champion["id"], "candidates": population})
    (run_dir / "optimal_expansion_prompt.txt").write_text(champion["prompt"] + "\n", encoding="utf-8")
    _save_progress("Phase 7 留出集 A/B/C 盲测进行中", history[-1]["generation"], population, history)

    # Phase 7: Independent Held-Out A/B/C Benchmark (13 held-out poems × 8 unseen bare inputs × bench_reps)
    # Group A: Native Studio BRIEF_SYSTEM + Style-v4
    # Group B: One-Shot Reverse Expansion Prompt (from 15 train refs) + Style-v4
    # Group C: RPE-GA Expand-v1 Champion + Style-v4
    held_texts = [p["text"] for p in sel["held_out"]]
    all_copy_texts = held_texts + [p["text"] for p in sel["references"]]
    rubric_tag = cfg["evaluation"].get("rubric_version", "rpe-poetry-zh-v3")

    from poetry_agent.studio import BRIEF_SYSTEM

    def _run_native_a(job):
        topic, rep = job
        if is_mock:
            chosen = f"{topic['topic']}的日常情境"
        else:
            brief_resp, _ = llm.call_json(
                purpose="rpe_native_brief_a",
                system=BRIEF_SYSTEM,
                user=json.dumps({"prompt": topic["topic"], "genre_hint": "modern", "preference": "", "previous_poem": None}, ensure_ascii=False),
                max_tokens=1200, temperature=0.7, thinking="disabled",
                cache_variant=f"expbench-A-brief:{topic['id']}:rep{rep}",
            )
            dirs = brief_resp.get("directions") or []
            idx = brief_resp.get("selected_direction", 0)
            chosen = dirs[idx] if isinstance(dirs, list) and dirs and isinstance(idx, int) and 0 <= idx < len(dirs) else ""
        t_a = {**topic, "requirements": f"{topic['requirements']}\n本次构思方向：{chosen}"}
        gen = generator.generate_poem(llm, cfg, style_prompt, t_a, cache_variant=f"expbench-A-gen:{topic['id']}:rep{rep}")
        if not gen["ok"]:
            return {"topic_id": topic["id"], "topic": topic["topic"], "repetition": rep, "ok": False, "native_direction": chosen}
        det = metrics.style_similarity(gen["text"], held_texts)
        copy = metrics.copy_diagnostics(gen["text"], all_copy_texts, lcs_chars=12, line_chars=8, rouge1_cap=0.80)
        rouge = [metrics.rouge1_char(gen["text"], ref) for ref in held_texts]
        judge, _ = evaluator.judge_poem(
            judge_llm, cfg, sel, topic, gen, kind="held_out",
            cache_variant=f"expbench-A-judge:{topic['id']}:rep{rep}:{rubric_tag}",
        )
        comp = evaluator._per_poem_fitness(cfg, det, judge, gen["form_ok"], copy)
        return {
            "topic_id": topic["id"], "topic": topic["topic"], "repetition": rep, "ok": True,
            "native_direction": chosen, "generation": gen, "deterministic": det,
            "copy_diagnostics": copy, "rouge1_diagnostic": {"mean_f1": round(statistics.mean(x["f1"] for x in rouge), 6)},
            "judge": judge, "components": comp,
        }

    bench_jobs = [(t, r) for t in test_topics for r in range(bench_reps)]
    if is_mock or len(bench_jobs) <= 1:
        a_rows = [_run_native_a(j) for j in bench_jobs]
    else:
        with ThreadPoolExecutor(max_workers=min(6, len(bench_jobs))) as pool:
            a_rows = list(pool.map(_run_native_a, bench_jobs))
    ev_cfg = {**cfg, "evaluation": {**cfg["evaluation"], "prompt_length_free": 440}}
    a_agg = evaluator.aggregate_evaluations({"id": "bench-A-native-studio", "prompt": ""}, a_rows, ev_cfg)

    b_reverse = make_expansion_prompt_candidate(
        llm, cfg, sel,
        focus="整体归纳参考诗如何从简短母题出发选定实物切口、拉开原初尺度、确立说话位置并推进全篇关系。",
        index=0, total=1, mode="one_shot_reverse", cache_tag="expbench-B-oneshot-v1",
    )
    b_cand = {"id": "bench-B-oneshot-reverse", "prompt": b_reverse["prompt"]}
    b_agg = evaluate_expansion_candidate(
        llm, judge_llm, cfg, sel, style_prompt, b_cand, test_topics, repetitions=bench_reps, kind="held_out",
    )

    c_cand = {"id": "bench-C-expand-v1", "prompt": champion["prompt"]}
    c_agg = evaluate_expansion_candidate(
        llm, judge_llm, cfg, sel, style_prompt, c_cand, test_topics, repetitions=bench_reps, kind="held_out",
    )

    # Symmetric AB+BA blind pairwise on all held-out test pairs: C vs A and C vs B
    cfg_pw = {**cfg, "evaluation": {**cfg["evaluation"], "pairwise_max_pairs": len(bench_jobs)}}
    def _all_elig(rows):
        return [{**r, "components": {**r["components"], "eligible": True}} for r in rows if r.get("ok")]
    pw_c_vs_a = evaluator.pairwise_compare_candidates(
        judge_llm, cfg_pw,
        {"id": "C_expand_v1", "evaluation": {"evaluations": _all_elig(c_agg["evaluations"])}},
        {"id": "A_native_brief", "evaluation": {"evaluations": _all_elig(a_agg["evaluations"])}},
        sel, kind="held_out",
    )
    pw_c_vs_b = evaluator.pairwise_compare_candidates(
        judge_llm, cfg_pw,
        {"id": "C_expand_v1", "evaluation": {"evaluations": _all_elig(c_agg["evaluations"])}},
        {"id": "B_oneshot_reverse", "evaluation": {"evaluations": _all_elig(b_agg["evaluations"])}},
        sel, kind="held_out",
    )

    # External 3-poet TF-IDF attribution check
    corpora_texts, corpora_labels = [], []
    for label, rel in (("haizi", "var/haizi/corpus.jsonl"), ("beidao", "var/beidao/corpus.jsonl"), ("shuting", "var/shuting/corpus.jsonl")):
        p = PROJECT_ROOT / rel
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    obj = json.loads(line)
                    if obj.get("text") and not any(obj.get(f) for f in ("is_fragment", "is_duplicate", "misattributed", "is_translation")):
                        corpora_texts.append(obj["text"])
                        corpora_labels.append(label)
    attr_index = ngram_sim.Index(corpora_texts, labels=corpora_labels, ns=(1, 2), sublinear=True, han=True) if len(set(corpora_labels)) >= 2 else None

    def _summarize_group(agg, extra_prompt=""):
        ok = [r for r in agg.get("evaluations", []) if r.get("ok")]
        dims = {}
        for d in evaluator.JUDGE_DIMENSIONS:
            if ok:
                dims[d] = round(statistics.mean(r["judge"]["dimensions"][d]["score"] for r in ok), 3)
        haizi_wins = 0
        shares = []
        if attr_index and ok:
            for r in ok:
                cls = attr_index.classify(r["generation"]["text"], k=7)
                if cls.get("label") == "haizi":
                    haizi_wins += 1
                shares.append((cls.get("votes") or {}).get("haizi", 0.0))
        return {
            "prompt_chars": len(extra_prompt),
            "eligible_count": agg.get("eligible_count"),
            "evaluation_count": agg.get("evaluation_count"),
            "eligible_rate": agg.get("eligible_rate"),
            "eligible_style": agg.get("eligible_style"),
            "style_score": agg.get("style_score"),
            "deterministic_style_score": agg.get("deterministic_style_score"),
            "judge_style_score": agg.get("judge_style_score"),
            "literary_quality_score": agg.get("literary_quality_score"),
            "topic_adherence": agg.get("topic_adherence"),
            "originality": agg.get("originality"),
            "score_std": agg.get("score_std"),
            "fitness": agg.get("fitness"),
            "dimension_means": dims,
            "external_tfidf_haizi_rate": round(haizi_wins / len(ok), 4) if ok and attr_index else None,
            "external_tfidf_vote_share": round(statistics.mean(shares), 4) if shares else None,
        }

    report = {
        "schema_version": "rpe-expand-v1",
        "run_id": run_id,
        "mode": mode,
        "created_at": utc_now(),
        "orthogonal_contract_enforced": True,
        "locked_step3_prompt_id": "g01-x01-0af51f85",
        "locked_step3_prompt_sha256": style_hash,
        "feature_schema": metrics.FEATURE_SCHEMA,
        "rubric_version": cfg["evaluation"]["rubric_version"],
        "champion": {
            "id": champion["id"],
            "origin": champion["origin"],
            "parent_id": champion.get("parent_id"),
            "generation": champion["generation"],
            "prompt": champion["prompt"],
            "validation": champion["validation"],
            "opt_summary": _summarize_group(champion["evaluation"], champion["prompt"]),
        },
        "baseline_b_prompt": b_reverse["prompt"],
        "history": history,
        "final_pairwise_tiebreak": final_pw,
        "benchmark": {
            "A_native_studio_brief": _summarize_group(a_agg),
            "B_oneshot_reverse_expansion": _summarize_group(b_agg, b_reverse["prompt"]),
            "C_rpe_ga_expand_v1": _summarize_group(c_agg, champion["prompt"]),
            "pairwise_C_vs_A_all": {k: pw_c_vs_a[k] for k in ("pairs_compared", "consistent_wins_a", "consistent_wins_b", "order_flips", "net_rate_a")},
            "pairwise_C_vs_B_all": {k: pw_c_vs_b[k] for k in ("pairs_compared", "consistent_wins_a", "consistent_wins_b", "order_flips", "net_rate_a")},
        },
        "usage": llm.budget.summary(),
    }
    atomic_write(run_dir / "expand_report.json", report)
    atomic_write(run_dir / "benchmark" / "benchmark.json", {
        "summary": report["benchmark"],
        "A": a_agg, "B": b_agg, "C": c_agg,
        "pw_c_vs_a": pw_c_vs_a, "pw_c_vs_b": pw_c_vs_b,
    })
    if not is_mock:
        (PROJECT_ROOT / "experiments/reverse_prompt_engineering/optimal_expansion_prompt.txt").write_text(
            champion["prompt"] + "\n", encoding="utf-8"
        )
    _save_progress("completed", history[-1]["generation"], population, history, extra={"benchmark_summary": report["benchmark"]})
    return report


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="RPE-GA Step-2 通用扩写引擎 7 阶段训练与盲测")
    parser.add_argument("--mode", choices=["mock", "live"], default="mock")
    parser.add_argument("--run-id", default="live-haizi-expand-v1-01")
    parser.add_argument("--pop-size", type=int, default=6)
    parser.add_argument("--generations", type=int, default=4)
    parser.add_argument("--bench-reps", type=int, default=2)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    res = run_expansion_experiment(
        run_id=args.run_id, mode=args.mode, pop_size=args.pop_size,
        generations=args.generations, bench_reps=args.bench_reps, resume=args.resume,
    )
    print(json.dumps({
        "run_id": res["run_id"],
        "champion_id": res["champion"]["id"],
        "champion_prompt": res["champion"]["prompt"],
        "benchmark": {
            k: {m: v[m] for m in ("eligible_rate", "eligible_style", "style_score", "literary_quality_score", "fitness", "external_tfidf_haizi_rate")}
            for k, v in res["benchmark"].items() if isinstance(v, dict) and "style_score" in v
        },
        "pairwise_C_vs_A": res["benchmark"]["pairwise_C_vs_A_all"],
        "pairwise_C_vs_B": res["benchmark"]["pairwise_C_vs_B_all"],
        "usage": res["usage"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
