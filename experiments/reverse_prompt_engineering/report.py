"""Markdown reports.  Reports label mock runs explicitly and never invent results."""
from __future__ import annotations

import difflib
import statistics
from datetime import datetime, timezone

from .validation import JUDGE_DIMENSIONS


DIMENSION_LABELS = {
    "lexical": "字词选择与语言习惯",
    "syntax": "句法结构与表达方式",
    "lineation": "分行、节奏及韵律",
    "imagery": "意象组织与修辞手法",
    "emotion": "情感表达方式",
    "structure": "语义组织与篇章结构",
    "progression": "推进感与发展动力",
    "concreteness": "具象与抽象比例",
    "repetition": "复沓、呼告与回环",
    "addressivity": "人称与呼告关系",
    "mythic_register": "神话/历史/文化原型",
    "closure": "结尾方式",
    "literary_quality": "文学质量",
    "topic_adherence": "题意符合程度",
    "originality": "原创性",
}


def _fmt(value, digits=2):
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(cell).replace("\n", " ") for cell in row) + " |")
    return "\n".join(lines)


def _initial_best(state):
    candidates = state.get("initialization", {}).get("candidates", [])
    evaluated = [c for c in candidates if c.get("fitness") is not None]
    return max(evaluated, key=lambda c: c["fitness"]) if evaluated else (candidates[0] if candidates else None)


def _best_candidate(state):
    best_id = state.get("best_candidate_id")
    for candidate in state.get("population", []):
        if candidate.get("id") == best_id:
            return candidate
    return None


def _dimension_means(candidate):
    if not candidate or not candidate.get("evaluation"):
        return {}
    rows = [e for e in candidate["evaluation"].get("evaluations", []) if e.get("ok")]
    result = {}
    for key in JUDGE_DIMENSIONS:
        values = [e["judge"]["dimensions"][key]["score"] for e in rows]
        evidence = []
        for e in rows:
            evidence.extend(e["judge"]["dimensions"][key].get("evidence", []))
        uncertainty = [e["judge"]["dimensions"][key].get("uncertainty") for e in rows]
        result[key] = {
            "mean": round(statistics.mean(values), 3) if values else None,
            "evidence": evidence[:3],
            "uncertainty_counts": {u: uncertainty.count(u) for u in set(uncertainty)},
        }
    return result


def render_markdown(state, config, selection, benchmark=None):
    now = datetime.now(timezone.utc).isoformat()
    mock = state.get("is_mock")
    lines = []
    lines.append("# RPE-GA 中文诗歌逆向提示词实验报告")
    lines.append("")
    lines.append(f"- 运行 ID：`{state.get('run_id')}`")
    lines.append(f"- 模式：`{state.get('mode')}`")
    lines.append(f"- 状态：`{state.get('status')}`")
    lines.append(f"- 生成时间：{now}")
    lines.append(f"- 实验名称：{config['experiment']['name']}")
    lines.append("")
    if mock:
        lines.append("> **MOCK / DRY-RUN 警告：** 本报告中的诗歌、评分、差异分析、适应度和对照结果均由固定规则模拟生成。"
                     "它们只用于验证代码流程，**不是真实模型输出，不能作为研究数据或结论引用**。")
        lines.append("")
    lines.append("## 1. 运行设置")
    lines.append("")
    lines.append(_table(
        ["项目", "值"],
        [
            ["参考诗数量", len(selection["references"])],
            ["留出诗数量", len(selection["held_out"])],
            ["种群规模 m", config["population"]["size"]],
            ["最大演化轮数 k", config["population"]["generations"]],
            ["每代子代", "每个父代 1 个；无交叉"],
            ["优化题目数", len(config["topics"]["optimization"])],
            ["独立测试题目数", len(config["topics"]["test"])],
            ["每题重复生成次数", config["generation"]["repetitions"]],
            ["评审 rubric", config["evaluation"]["rubric_version"]],
            ["生成模型", state.get("generation_model") or "见 ledger"],
            ["评审模型", state.get("judge_model") or "见 ledger"],
            ["API 调用上限", config["budget"]["max_api_calls"]],
            ["Token 上限", config["budget"]["max_total_tokens"]],
        ],
    ))
    lines.append("")
    lines.append("## 2. 参考语料与留出语料")
    lines.append("")
    lines.append(f"语料文件：`{selection['source_path']}`；SHA-256：`{selection['corpus_sha256']}`")
    lines.append("")
    rows = [[p["poem_id"], p.get("title") or "", p["han_length"], p.get("period") or "", p["text_sha256"][:12]]
            for p in selection["references"]]
    lines.append("### 参考集（仅用于搜索 Prompt）")
    lines.append("")
    lines.append(_table(["poem_id", "标题", "汉字数", "时期", "文本哈希"], rows))
    lines.append("")
    rows = [[p["poem_id"], p.get("title") or "", p["han_length"], p.get("period") or "", p["text_sha256"][:12]]
            for p in selection["held_out"]]
    lines.append("### 留出集（仅用于最终独立测试）")
    lines.append("")
    lines.append(_table(["poem_id", "标题", "汉字数", "时期", "文本哈希"], rows))
    lines.append("")
    lines.append(f"参考集内部平均风格相似度（确定性指标，仅作诊断）：{_fmt(selection['reference_diversity'].get('mean_style_similarity'))}")
    lines.append("")
    lines.append("## 3. 题目")
    lines.append("")
    lines.append("### 优化题目")
    lines.append("")
    lines.append(_table(["id", "题目", "体裁", "行数上限", "要求"],
                        [[t["id"], t["topic"], t.get("genre", "modern"), t.get("max_lines", ""), t.get("requirements", "")]
                         for t in config["topics"]["optimization"]]))
    lines.append("")
    lines.append("### 独立测试题目")
    lines.append("")
    lines.append(_table(["id", "题目", "体裁", "行数上限", "要求"],
                        [[t["id"], t["topic"], t.get("genre", "modern"), t.get("max_lines", ""), t.get("requirements", "")]
                         for t in config["topics"]["test"]]))
    lines.append("")
    lines.append("## 4. 每代适应度变化")
    lines.append("")
    history = state.get("fitness_history", [])
    if history:
        lines.append(_table(
            ["代", "本代最优", "本代均值", "标准差", "历史最优", "连续未提升"],
            [[h["generation"], _fmt(h["best"]), _fmt(h["mean"]), _fmt(h["std"]),
              _fmt(h["best_so_far"]), h["stale_generations"]] for h in history],
        ))
    else:
        lines.append("尚未产生完整的演化代记录。")
    lines.append("")
    if state.get("early_stopped"):
        lines.append(f"提前停止：{state['early_stopped']}")
        lines.append("")
    lines.append("## 5. 最终种群与淘汰记录")
    lines.append("")
    generations = state.get("generations", [])
    if generations:
        last = generations[-1]
        rows = []
        for row in last.get("ranking", []):
            rows.append([
                row["rank"], row["candidate_id"], row.get("parent_id") or "—", row.get("origin"),
                _fmt(row.get("fitness")), row.get("eligible"), _fmt(row.get("style_score")),
                _fmt(row.get("literary_quality_score")), "是" if row.get("selected") else "否", row["reason"],
            ])
        lines.append(_table(
            ["排名", "候选", "父代", "来源", "适应度", "满足约束", "风格", "文学质量", "入选", "淘汰/入选原因"],
            rows,
        ))
    else:
        lines.append("尚未产生世代选择记录。")
    lines.append("")
    best = _best_candidate(state)
    if best:
        lines.append("## 6. 最优 Style Prompt")
        lines.append("")
        lines.append("```text")
        lines.append(best["prompt"])
        lines.append("```")
        lines.append("")
        lines.append(_table(
            ["指标", "值"],
            [
                ["候选 ID", best["id"]],
                ["适应度", _fmt(best.get("fitness"))],
                ["满足全部约束", best.get("eligible")],
                ["风格相似度", _fmt(best.get("style_score"))],
                ["其中确定性指标", _fmt(best.get("deterministic_style_score"))],
                ["其中 LLM 评审", _fmt(best.get("judge_style_score"))],
                ["文学质量", _fmt(best.get("literary_quality_score"))],
                ["题意符合", _fmt(best.get("topic_adherence"))],
                ["原创性", _fmt(best.get("originality"))],
                ["评价样本数", best.get("evaluation_count")],
                ["重复间标准差", _fmt(best.get("score_std"))],
                ["来源", best.get("origin")],
                ["代", best.get("generation")],
                ["父代", best.get("parent_id") or "—"],
            ],
        ))
        lines.append("")
        initial = _initial_best(state)
        if initial:
            lines.append("### 初始最优 Prompt 与最终 Prompt 的差异")
            lines.append("")
            diff = list(difflib.unified_diff(
                initial["prompt"].splitlines(), best["prompt"].splitlines(),
                fromfile=f"initial:{initial['id']}", tofile=f"final:{best['id']}", lineterm="",
            ))
            if diff:
                lines.append("```diff")
                lines.extend(diff)
                lines.append("```")
            else:
                lines.append("初始最优与最终最优文本相同。")
            lines.append("")
            lines.append(f"初始最优候选：`{initial['id']}`，适应度 {_fmt(initial.get('fitness'))}；"
                         f"最终候选：`{best['id']}`，适应度 {_fmt(best.get('fitness'))}。")
            lines.append("")
        dims = _dimension_means(best)
        if dims:
            lines.append("### 最优候选的评审维度")
            lines.append("")
            rows = []
            for key in JUDGE_DIMENSIONS:
                item = dims.get(key, {})
                rows.append([
                    DIMENSION_LABELS.get(key, key),
                    f"{_fmt(item.get('mean'))}/5",
                    str(item.get("uncertainty_counts", {})),
                    "；".join(str(x) for x in item.get("evidence", [])[:2]) or "—",
                ])
            lines.append(_table(["维度", "均分", "不确定性计数", "证据摘录"], rows))
            lines.append("")
    lines.append("## 7. 变异记录（父子代关系）")
    lines.append("")
    mutation_rows = []
    for child in state.get("all_children", []):
        changes = child.get("changes", [])
        mutation_rows.append([
            child.get("generation"), child.get("id"), child.get("parent_id"),
            "、".join(sorted({c.get("op", "?") for c in changes})) or "—",
            _fmt(child.get("fitness")),
            child.get("summary", ""),
        ])
    if mutation_rows:
        lines.append(_table(["代", "子代", "父代", "操作", "适应度", "摘要"], mutation_rows))
    else:
        lines.append("尚无变异记录。")
    lines.append("")
    lines.append("> 注意：被淘汰的子代不在最终 `state.population` 中；完整父子代与变更记录见 `population/gen_*.json`、`mutations/*.json`。")
    lines.append("")
    lines.append("## 8. 对照实验")
    lines.append("")
    if benchmark and benchmark.get("groups"):
        rows = []
        for key in ("A", "B", "C"):
            group = benchmark["groups"].get(key, {})
            agg = group.get("aggregate", {})
            rows.append([
                key, group.get("label", ""), _fmt(agg.get("style_score")),
                _fmt(agg.get("literary_quality_score")), _fmt(agg.get("topic_adherence")),
                _fmt(agg.get("originality")), _fmt(agg.get("form_ok_rate")),
                _fmt(agg.get("copy_rate")), group.get("usage", {}).get("calls"),
                group.get("usage", {}).get("total_tokens"),
            ])
        lines.append(_table(
            ["组", "说明", "风格相似度", "文学质量", "题意", "原创性", "格式通过率", "复制率", "API 调用", "Token"],
            rows,
        ))
        lines.append("")
        lines.append(f"按风格相似度排序：{', '.join(benchmark.get('ranking_by_style_score', []))}")
        lines.append("")
        lines.append("C 组相对基线差值：")
        lines.append("")
        lines.append("```json")
        import json
        lines.append(json.dumps(benchmark.get("comparison", {}), ensure_ascii=False, indent=2))
        lines.append("```")
        lines.append("")
        lines.append("公平性记录：")
        lines.append("")
        for key, value in benchmark.get("fairness", {}).items():
            lines.append(f"- {key}: {value}")
        lines.append("")
        lines.append("局限：")
        lines.append("")
        for item in benchmark.get("limitations", []):
            lines.append(f"- {item}")
    elif benchmark:
        lines.append(f"对照实验未完成：{benchmark}")
    else:
        lines.append("本次运行未执行对照实验（`benchmark.enabled=false` 或因为预算/错误中止）。")
    lines.append("")
    lines.append("## 9. API 使用与成本")
    lines.append("")
    usage = state.get("llm_summary") or {}
    if usage:
        lines.append(_table(
            ["项目", "值"],
            [[k, _fmt(v)] for k, v in usage.items()],
        ))
    else:
        lines.append("没有可用的调用汇总。")
    lines.append("")
    lines.append("## 10. 事实边界、已实现与待验证")
    lines.append("")
    lines.append("**已经实现：** 参考语料选择、初始种群、生成、确定性指标、匿名 LLM 评审、差异分析、LLM 变异、"
                 "父代+子代选择、断点续跑、缓存、预算上限、A/B/C 对照、报告与 Prompt 独立输出。")
    lines.append("")
    lines.append("**已经验证：** 代码在 Mock 客户端下可完成全流程；单元测试覆盖选择、指标、提示词规则、缓存/预算、"
                 "生成隔离、评审匿名和对照分组。真实 API 的生成质量与风格效果未在本仓库中验证。")
    lines.append("")
    lines.append("**仍待验证：** 适应度权重是否合理；确定性指标与人类风格判断的相关性；LLM 评审的稳定性与自评偏差；"
                 "不同模型家族评审的一致性；参数（n、m、k、题目数）对结果的影响；真实付费运行的成本与收益。")
    lines.append("")
    lines.append("本实验寻找的是“具有相似风格控制效果的 Prompt”，**不是**恢复诗人的真实创作指令。"
                 "高 ROUGE-1 只说明文本重合，不等于风格模仿成功；报告不据此下结论。")
    lines.append("")
    if state.get("limitations"):
        lines.append("### 本次运行特定限制")
        lines.append("")
        for item in state["limitations"]:
            lines.append(f"- {item}")
        lines.append("")
    lines.append("## 11. 与论文方法的差异")
    lines.append("")
    lines.append("详见 `METHOD_ADAPTATION.md`。核心差异：ROUGE-1 改为诗歌领域多维适应度；增加题意、原创性、"
                 "文学质量约束；评审器匿名且不接收候选 Prompt；生成器不接收参考作品；保留 mean/max 思想但以"
                 "多题均值为主；无交叉；加入缓存、预算、断点续跑和人工可审计记录。")
    lines.append("")
    return "\n".join(lines) + "\n"


def write_reports(state, config, selection, store, benchmark=None):
    report = render_markdown(state, config, selection, benchmark)
    store.write_text("report.md", report)
    if benchmark:
        store.write_json("benchmark/benchmark.json", benchmark)
        store.write_text("benchmark/benchmark.md", render_benchmark_markdown(benchmark))
    return report


def render_benchmark_markdown(benchmark):
    lines = ["# 对照实验报告", ""]
    if benchmark.get("is_mock"):
        lines.append("> **MOCK 警告：** 以下数字为固定规则模拟，不是真实 API 结果。")
        lines.append("")
    rows = []
    for key in ("A", "B", "C"):
        group = benchmark["groups"].get(key, {})
        agg = group.get("aggregate", {})
        rows.append([
            key, group.get("label", ""), _fmt(agg.get("style_score")),
            _fmt(agg.get("literary_quality_score")), _fmt(agg.get("topic_adherence")),
            _fmt(agg.get("originality")), _fmt(agg.get("form_ok_rate")),
            _fmt(agg.get("copy_rate")), group.get("usage", {}).get("calls"),
            group.get("usage", {}).get("total_tokens"),
        ])
    lines.append(_table(
        ["组", "说明", "风格相似度", "文学质量", "题意", "原创性", "格式通过率", "复制率", "API 调用", "Token"],
        rows,
    ))
    lines.append("")
    lines.append("按风格相似度排序：" + ", ".join(benchmark.get("ranking_by_style_score", [])))
    lines.append("")
    lines.append("## 组间差值")
    lines.append("")
    import json
    lines.append("```json")
    lines.append(json.dumps(benchmark.get("comparison", {}), ensure_ascii=False, indent=2))
    lines.append("```")
    lines.append("")
    lines.append("## 公平性与独立测试")
    lines.append("")
    for key, value in benchmark.get("fairness", {}).items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## 局限")
    lines.append("")
    for item in benchmark.get("limitations", []):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## 测试题目")
    lines.append("")
    lines.append(_table(["id", "题目", "体裁", "要求"],
                        [[t["id"], t["topic"], t.get("genre"), t.get("requirements", "")]
                         for t in benchmark.get("test_topics", [])]))
    lines.append("")
    return "\n".join(lines) + "\n"
