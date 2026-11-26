# 原论文 RPE-GA 与本项目中文诗歌适配的差异说明

论文：Hanqing Li, Diego Klabjan. *Reverse Prompt Engineering: A Zero-Shot, Genetic Algorithm Approach to Language Model Inversion.* EMNLP 2025, pp. 26223—26245.

重点：Section 3.2（Five Answers Inference）、Section 3.3（Iterative Method）、Figure 5（RPE-GA workflow）、Figure 6（candidate generation）。

本文件只说明方法差异，不评价论文。项目实现位于 `experiments/reverse_prompt_engineering/`。

---

## 1. 问题设定差异

| 维度 | 原论文 | 本项目 |
|---|---|---|
| 输入 | 同一 latent prompt 产生的 n=5 条模型输出 A | 同一诗人的 n=5 首真实参考诗 A |
| 目标 | 恢复 latent prompt p | 寻找能产生相似风格新诗的 Style Prompt P |
| 真值 | 存在原始 prompt，可用 cosine similarity 对 p 评价 | 不存在可恢复的原始创作指令；只能通过生成实验评价风格效果 |
| 生成模型 | 论文使用 GPT-3.5 作为 RPE backbone，并在 Llama-2/GPT-3.5 输出上测试 | 只用 DeepSeek 文本 API；不访问权重、梯度、logits、隐藏层 |
| 数据条件 | 黑盒、zero-shot、limited data | 同样黑盒、zero-shot、5 首参考诗；无训练/微调/Embedding/RAG |
| 输出评价 | 恢复 prompt 与真值 prompt 的 cosine similarity | 风格相似度 + 题意 + 原创性 + 文学质量；ROUGE-1 仅作重合诊断 |

**关键结论：** 本项目从“prompt inversion”转为“style prompt search”。不能声称恢复诗人的真实创作指令。

---

## 2. Phase 1：Initialization

| 原论文 | 本项目 |
|---|---|
| 给 LLM 看 A 的多条答案，要求推测一个 latent prompt | 给 LLM 看多首匿名参考诗，要求归纳可迁移的写作规律 |
| `n` 次采样或多次调用生成 m 个候选 | 默认 m 次**独立调用**，每次一个观察角度（字词、句法、分行、意象、情感、篇章） |
| 主要靠采样温度产生多样性 | 角度 + 温度 + Prompt 规则共同保证多样性；不是同一指令的措辞改写 |
| 用 `<PRO>...</PRO>` 包裹 | 强制 JSON：`{"prompt", "design_notes", "covered_dimensions"}` |
| 未显式禁止作者名/原文复制 | 确定性规则拒绝诗人姓名、参考原句/长片段、依赖参考材料的说法、过多套话、不可执行指令 |
| 未显式分离题材与手法 | 系统指令要求把“可迁移写作手法”与“仅属于原题材的内容”分开 |

为避免姓名触发，自动选参考诗时排除正文直接出现诗人姓名的作品；发送给 LLM 的参考块只有匿名正文，不含标题/作者/来源/poem_id/split。

---

## 3. Phase 2：Generation

| 原论文 | 本项目 |
|---|---|
| 每个候选 prompt 直接送给 LLM 生成一条 response | 每个候选 Prompt + 相同的 3 个优化题目生成诗；每个题目可配置重复次数 |
| 评价对象是 response 与参考答案的 ROUGE | 评价对象是诗的风格特征与参考诗，而不是与参考诗的字面重合 |
| 无“生成隔离”要求 | 生成调用只接收候选 Prompt、题目、体裁/行数/要求；不接收参考作品、诗人姓名、候选编号、世代号、评价反馈 |
| 无体裁约束 | 复用 `poetry_agent.core.Task/check` 做现代诗行数与格律体裁的确定性格式检查 |

生成参数在同一实验内固定：模型、temperature、max_tokens、thinking。Judge 使用独立参数（默认 temperature=0）。

---

## 4. Phase 3：Evaluation

### 4.1 原论文

对每个候选 `p_i` 生成 `a_i`，计算 `a_i` 与每条参考答案 `a_j` 的 ROUGE-1：

```
S_i = {s_i1, ..., s_in}
s_i = (mean(S_i) + max(S_i)) / 2
```

选择 `s_i` 最高的候选。ROUGE-1 衡量的是**与原文的重合**。

### 4.2 本项目的适配

本项目的目标是“风格相似”，不是“复现原文”。直接使用 ROUGE-1 会把“抄得像”误判为“风格像”，也会惩罚合理的题材变化。因此：

**（a）确定性指标（Python，离线，可复现）**

- 字频、bigram、功能字/虚词分布
- 行长分布、分节数、行数、行尾字
- 标点节奏、问句/感叹句比例
- 重复率、独特字比例、代词使用
- 结构与节奏综合相似度
- `progression` 代理：转折/推进标记密度、行首新鲜度、分节变化

主分取生成诗与各参考诗相似度的**均值**；同时报告 `max`、`min`、`std` 和逐参考明细。原论文的 mean/max 思想保留在诊断字段中，但不再作为唯一适应度。

**（b）匿名 LLM Judge Rubric**

15 个维度，0—5 分：

1. 字词选择与语言习惯
2. 句法结构与表达方式
3. 分行、节奏及韵律
4. 意象组织与修辞手法
5. 情感表达方式
6. 语义组织与篇章结构
7. **推进感与发展动力（progression）**
8. 具象与抽象比例
9. 复沓、呼告与回环
10. 人称与呼告关系
11. 神话/历史/文化原型
12. 结尾方式
13. 文学质量
14. 题意符合程度
15. 原创性

原论文的第 8 项“原创性与题意符合程度”在本项目拆成两个维度，分别进入约束逻辑；1—12 为风格维度，13 为质量监控。`progression` 权重设为 0.24，用于奖励“有某种力量推动全诗发展”，而不是静态意象清单。

每个维度必须返回：`score`、`evidence`（文本短引文）、`rationale`、`uncertainty`。Judge 不接收候选 Prompt、候选编号、世代、分组或生成策略。

**（c）适应度组合**

```
style  = 0.35 × deterministic_style + 0.65 × weighted_mean(judge_style_1..12) × 20
base   = 0.85 × style + 0.15 × literary_quality
fitness = base - penalties
```

惩罚项：

- 格式不通过
- 题意低于阈值
- 原创性低于阈值
- 文学质量低于下限
- 检测到复制（长公共片段/整句重合/异常高 ROUGE-1）

`eligible` 是硬约束标记：格式通过、无复制、题意/原创性/质量均达下限。选择排序优先 `eligible`，再按 `fitness`。这比原论文更严格，因为“必要约束”在诗歌风格实验中不能只靠软惩罚。

**（d）ROUGE-1**

保留为对照与重合诊断：

- 每篇参考的字符级 ROUGE-1 precision/recall/F1
- 最长公共连续片段
- 整句重合
- 复制标记

报告明确说明：高 ROUGE-1 不等于风格模仿成功。

**（e）随机性处理**

- 每个题目可配置重复生成次数。
- 最终对 top-k 候选追加 `confirmation_repetitions` 次新样本后重新聚合，降低“一次偶然生成”决定优胜者的风险。
- 记录 `score_std`、样本数、每项证据与不确定性。

---

## 5. Phase 4：Difference Analysis

| 原论文 | 本项目 |
|---|---|
| 对候选回答与每条参考回答逐一问“有什么不同” | 一次结构化对照多首参考诗与多篇生成诗 |
| 将多条差异总结成一段建议 | 输出分字段分析：已复现、未复现、多余倾向、Prompt 问题、题材依赖 |
| 主要为后续变异提供文字建议 | 要求文本证据、`observation` vs `interpretation`、置信度、可操作建议 |
| 不专门检查 Prompt 指令本身 | 增加“无效/含糊/重复/冲突/过度具体”的指令审查 |

差异分析可以看到候选 Prompt（因为它要审查指令），但**评价器**看不到。两者职责分离。

---

## 6. Phase 5：Mutation

| 原论文 | 本项目 |
|---|---|
| 用差异总结让 LLM 修改 prompt | 用结构化差异分析 + 可操作建议修改 Prompt |
| 允许自由改写 | 明确允许的操作：add / delete / replace / split / merge / adjust / conflict_fix |
| 要求简洁 | 要求保留已证明有效的部分；每条变更记录 `op/target/reason` |
| 输出 `<PRO>...</PRO>` | 输出 JSON：`prompt`、`changes`、`preserved`、`summary` |
| 未显式禁止姓名/原文 | 子代继续通过 Prompt 规则：无姓名、无参考原句/长片段、无依赖参考材料的说法、长度/指令单元合规 |

每个父代只产生一个子代。优化对象始终是 Prompt，不直接修改生成的诗。

---

## 7. Phase 6：Selection

| 原论文 | 本项目 |
|---|---|
| 初始化 m 个候选并评价 | 同 |
| 每个候选产生一个子代（Figure 6） | 同；无交叉 |
| 合并父代 + 子代，共 2m | 同；无效子代也会记录但不评价 |
| 按分数取前 m | 排序键：可评估 → eligible → fitness → 文学质量 → 稳定性；按前 m 选 |
| 重复 k 次 | 同；支持最大轮数、API 预算、Token 预算、连续无提升提前停止 |
| 输出最高分 prompt | 同；最终追加确认重评 |

原论文的 mean/max 用于候选与多条参考答案的 ROUGE；本项目把 mean/max 保留为确定性风格的诊断字段，而主适应度是多维风格 + 约束。

## 7.1 检查点

长跑配置每 5 代保存一次 `checkpoints/gen_XXX/`，包含 `snapshot.json`（当前种群、排名、适应度、历史）、`best_prompt.txt` 和 `leaderboard.md`。逐代完整记录仍在 `population/gen_*.json`；checkpoint 是便于人工检查的稳定快照，不替代逐代记录。

默认不引入交叉操作，以保持与论文核心算法一致。

---

## 8. Phase 7：Final Validation

| 原论文 | 本项目 |
|---|---|
| 用 cosine similarity 与真值 prompt 比较 | 用留出集与独立测试题目做 A/B/C 生成实验 |
| 无“测试集不得反馈”的生成实验协议 | 明确：测试题目与留出集不参与优化；对照运行不调用分析/变异；报告标记 `prompts_mutated_after_test=false` |
| 主要评价恢复 prompt | 评价诗的风格相似度、文学质量、题意、原创性、格式、复制率、API 成本 |

三组：

- **A**：直接要求模仿目标诗人（按题目生成模仿指令）。
- **B**：LLM 阅读参考作品后，一次性反推一个 Prompt。
- **C**：RPE-GA 最优 Prompt。

三组共享测试题目、留出参考集、生成参数和 Judge rubric；Judge 不知道分组。样本量小，报告只给描述性比较，不做显著性声明。

---

## 9. 未引入的内容

按任务约束，本项目**没有**引入：

- Style Encoder / Style Decoder
- Embedding Model / 向量检索 / RAG
- 模型权重、梯度、logits、隐藏层访问
- 神经网络训练或微调
- 交叉操作
- 人类评审（仅预留人工抽查建议）
- 任何虚构的真实 API 结果

---

## 10. 风险与验证边界

1. **自评偏差**：默认生成与评审可能同模型。已做独立调用、匿名、JSON 约束；`DEEPSEEK_JUDGE_MODEL` 只能切换到另一个 DeepSeek 模型，仍属同家族，不能消除偏差。不同家族评审需要额外客户端，本项目未实现。
2. **代理指标**：确定性特征不能完整代表“风格”；权重（0.35/0.65、0.85/0.15、progression 0.24）是原型选择，未经人类相关性验证。
3. **小样本**：5 首参考、5 个测试题目、单模型、有限轮次；不能声称统计显著或普遍优越。
4. **Judge 稳定性**：同一文本重复评审可能波动；项目记录 `uncertainty` 和 `score_std`，但未做多次 Judge 一致性实验。
5. **费用**：默认不配置单价，只记录 token；真实费用以供应商账单为准。
6. **真实 API 未运行**：当前只完成代码、Mock 全流程、单元测试和 dry-run 估算。真实生成质量与成本收益仍待验证。

---

## 11. 一句话总结

> 保留 RPE-GA 的算法骨架（初始化、生成、评价、差异分析、LLM 变异、父子代选择），把“恢复原文”改成“搜索风格控制 Prompt”，把 ROUGE-1 主评价改成诗歌多维风格适应度，并用题意、原创性、文学质量、匿名 Judge 和留出集独立测试保证结论不被字面重合或自评偏差主导。
