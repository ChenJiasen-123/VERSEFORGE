# REReport：RPE-GA 中文诗歌逆向提示词工程的实施过程

本文件记录本次工作的**实施过程、验证方式、发现的问题和未完成事项**。它不是实验结果的替代品：仓库中没有任何真实 DeepSeek 付费调用结果，也没有把 Mock 数据当成研究结论。

---

## 1. 任务理解

目标不是写一篇“海子诗歌风格分析”，而是在 VERSEFORGE 项目内建立一个可独立运行、可追溯的实验系统：

1. 读取真实诗人参考作品；
2. 用 LLM 生成初始 Style Prompt 种群；
3. 在区别于参考作品的创作题目上实际生成诗；
4. 用确定性指标 + 匿名 LLM Judge 评价风格、题意、原创性和文学质量；
5. 用差异分析指导 Prompt 变异；
6. 用父代 + 子代的 (μ+λ) 选择迭代；
7. 用留出集和新题目做 A/B/C 对照；
8. 保存全部 Prompt、作品、评分、证据、变异、父子关系、调用与 token；
9. 在没有预算授权时只做代码、Mock 测试和 dry-run。

核心边界：不训练/微调、不访问权重/梯度/logits/隐藏层、不引入 Embedding/RAG、不声称恢复诗人真实 Prompt。

---

## 2. 阅读与勘察

### 2.1 论文

阅读了：

- `https://aclanthology.org/2025.emnlp-main.1333.pdf`
- 重点：Section 3.2 Five Answers Inference、Section 3.3 Iterative Method、Figure 5 RPE-GA workflow、Figure 6 candidate generation
- 参考实现：`https://github.com/hanklee97121/RPE_Reverse_Prompt_Engineering`

确认的论文骨架：

```text
给出 n 条答案 A
→ LLM 反推 m 个候选 Prompt P
→ 每个候选生成答案并计算 ROUGE-1
→ 差异分析
→ LLM 修改 Prompt 得到子代
→ 父代 + 子代共 2m 个，按分数取前 m
→ 迭代 k 次，输出最高分 Prompt
```

论文中 `s_i = (mean(S_i) + max(S_i)) / 2`，没有交叉操作。

### 2.2 现有项目

检查了：

- `poetry_agent/client.py`：DeepSeek API 客户端、`.env` 加载、HTTPS 主机校验、无重定向、无自动 HTTP 重试、强制 JSON 输出
- `poetry_agent/core.py`：`Task`、`Poem`、`check` 等现有诗歌任务/格式检查
- `poetry_agent/style/corpus.py`：语料读取、去重提示、split、provenance
- `poetry_agent/style/features.py`：汉字判断、逐篇特征
- `main.py`、`README.md`、`tests/`：项目运行方式、Mock 客户端、测试风格
- `var/haizi/corpus.jsonl`：136 条海子诗歌记录，122 train / 14 held_out；含 `poem_id`、`title`、`text`、`source`、`metadata`、`split`

采用的做法：

- 复用 `DeepSeekClient`、`load_env`、`poetry_agent.style.corpus.load_corpus`、`digest`、`write`、`poetry_agent.core.Task/Poem/check`、`style.features.is_han`
- 不修改原有创作工作流；新代码全部放在 `experiments/reverse_prompt_engineering/`
- 对 `DeepSeekClient` 只做了向后兼容的小扩展：可选 `model` 构造参数和可选 `temperature` 请求参数

---

## 3. 设计决策

### 3.1 为什么不是 ROUGE-1 主评价

论文目标是把生成文本与参考答案对齐；本项目目标是风格相似，而不是复现原文。直接优化 ROUGE-1 会奖励“抄原句”，也会惩罚合理的题材变化。因此：

- 主风格分 = 0.35 × 确定性特征相似度 + 0.65 × LLM Judge 六个风格维度均分
- 文学质量占 0.15，作为监控项
- 题意、格式、原创性、复制检测作为必要约束/惩罚
- ROUGE-1 只保留为对照和重合诊断

### 3.2 为什么把题目/参考集分开

- 优化题目：3 个，与参考作品内容不同
- 独立测试题目：5 个，从未参与优化
- 参考集：`split=train` 中按 `tier/core_rank` 确定性选 5 首
- 留出集：`split=held_out` 中选 5 首，只在最终 A/B/C 对照中使用

最终对照不调用分析/变异，因此不会“看了测试结果再改 Prompt”。

### 3.3 姓名与原文隔离

实施中发现：`split=train` 的第 5 首核心作品（`haizi-03-119`，标题含“海子”）正文直接出现诗人姓名。若直接送入 LLM，可能触发姓名模仿或身份泄露。

处理：

- 自动选诗时默认排除正文包含诗人姓名/别名的作品（`corpus.exclude_target_name_in_auto_selection: true`）
- 发送给初始化、分析、Judge 的参考块只有 `label + text`，不含作者、来源、poem_id、split、标题
- 候选 Prompt 规则禁止诗人姓名、参考原句/长片段、依赖“上面/这些诗/参考作品”等说法
- 生成调用只接收候选 Prompt、题目、体裁/行数/要求，不接收参考作品

显式指定含姓名的作品会直接报错，避免“以为匿名、实际泄露”。

### 3.4 评价器匿名

Judge 只看到：

- 匿名参考诗
- 匿名生成诗
- 题目/体裁/要求
- Rubric 与 JSON schema

不接收候选 Prompt、候选编号、世代、分组、生成策略。Judge 的 JSON 里也不写入这些字段。

### 3.5 随机性与断点续跑

- 生成阶段每个 candidate/topic/repetition 有独立 cache variant
- 变异阶段加入 `round_id`，保证同一父代在不同代可以得到新子代；同一代续跑复用缓存
- 最终 top-k 追加 confirmation repetitions
- `ledger.jsonl` 记录每次真实调用和缓存命中；续跑时从 ledger 恢复累计调用/token 预算，避免“每次重启预算重置”

---

## 4. 文件与职责

```text
experiments/reverse_prompt_engineering/
  config.yaml          参数与题目
  run.py               estimate / mock / live / resume 入口
  config.py            默认值、深合并、校验
  corpus.py            参考/留出选择、匿名块、姓名过滤
  metrics.py           确定性诗歌指标、ROUGE-1、复制诊断
  validation.py        Prompt 规则、JSON schema 校验
  llm.py               预算、缓存、ledger、JSON 重试、真实客户端封装
  mock.py              离线规则 Mock
  initializer.py       Phase 1
  generator.py         Phase 2
  evaluator.py         Phase 3
  analyzer.py          Phase 4
  mutator.py           Phase 5
  optimizer.py         Phase 6
  benchmark.py         Phase 7
  report.py            report.md / benchmark.md
  store.py             运行目录、state、事件
  tests/               20 个单元/Mock 测试
```

运行产物默认写入 `experiments/reverse_prompt_engineering/runs/<run_id>/`，该目录已加入 `.gitignore`，避免把 Mock 或付费数据误提交。

---

## 5. 实施顺序

1. 下载论文 PDF，用 `pdftotext` 阅读 3.2/3.3/Figure 5/6；克隆参考仓库，阅读 `RPE_ga.py` 的 `initial_prompt_generation`、`evaluation`、`cross_mutation`、`replacement`。
2. 检查 `var/haizi/corpus.jsonl` 的字段、split、tier、正文长度、是否含姓名。
3. 扩展 `DeepSeekClient`：可选 `model`、可选 `temperature`，默认行为不变。
4. 实现配置、语料、指标、规则、LLM 预算/缓存/ledger、Mock。
5. 实现 Phase 1—7 与优化器状态机。
6. 实现报告、独立 Prompt 输出、A/B/C 对照。
7. 编写单元/Mock 测试并运行（最终 20 个）。
8. 运行小规模 Mock、默认规模 Mock、预算中止 + 续跑、无授权 live 拒绝。
9. 增加 `tests/__init__.py` 解决本机 `site-packages/tests` 遮蔽，跑通原有 247 个测试。
10. 清理 Mock 运行产物，补文档与差异说明。

---

## 6. 验证记录

### 6.1 编译

```powershell
python -m py_compile experiments/reverse_prompt_engineering/*.py poetry_agent/client.py
```

结果：通过。

### 6.2 RPE-GA 测试

```powershell
python -m unittest discover -s experiments/reverse_prompt_engineering/tests -v
```

结果：

```text
Ran 21 tests
OK
```

覆盖：

- 参考/留出集数量、split、正文哈希不重叠
- 匿名块不含姓名/来源/poem_id
- 确定性指标、ROUGE-1、复制诊断
- Prompt 规则：姓名、套话、参考原句、依赖短语
- 缓存命中不消耗调用、预算中止、ledger 恢复
- Mock 全流程与产物完整性
- 生成隔离：生成请求无 `reference_poems`，非基线 A 的 Prompt 无姓名/参考原文
- Judge 匿名：无 candidate prompt / id / parent / generation
- 预算耗尽后续跑
- live 未授权时在联网前拒绝

### 6.3 默认规模 Mock

命令（输出目录在系统临时目录，已删除）：

```powershell
python experiments/reverse_prompt_engineering/run.py --mode mock --run-id default-check
```

结果：

```text
status: completed
generation: 3（patience=2 提前停止）
population: 5，Prompt 去重后 5/5
best: 75.6112（Mock 分数，不能作为研究结论）
API calls: 194（Mock 内部计数）
tokens: 533,568（Mock usage 估算）
benchmark groups: A/B/C 均完成
```

这次运行只验证流程，不代表真实风格效果。

### 6.4 预算中止与续跑

测试中把 `max_api_calls` 设为 2：

- 第一次运行在初始化阶段 `budget_exhausted`，保存 `state.json`
- 提高预算后续跑，从 ledger 恢复累计调用，完成剩余阶段
- 测试通过

### 6.5 现有工作流回归

`python main.py --topic "雨后的公交站" --max-lines 8 --mock` 通过，说明 `DeepSeekClient` 的向后兼容修改未破坏原有 Mock 创作入口。

### 6.6 项目级回归测试

当前机器 `site-packages` 中存在一个名为 `tests` 的包，会遮蔽仓库内无 `__init__.py` 的 `tests/` 目录。为让本地测试优先，并验证本次 `DeepSeekClient` 修改没有破坏原工作流，新增了空文件 `tests/__init__.py`。

```powershell
python -m unittest discover -s tests -q
```

结果：

```text
Ran 247 tests
OK
```

另外 RPE-GA 独立测试：

```text
Ran 21 tests
OK
```

`python main.py --topic "雨后的公交站" --max-lines 8 --mock` 也通过。

---

## 7. 过程中发现并修复的问题

| 问题 | 现象 | 处理 |
|---|---|---|
| 参考诗含诗人姓名 | 自动选中的一首正文出现“海子”，匿名块测试失败 | 自动选诗排除姓名作品；显式选择直接报错 |
| 复制诊断测试 | 构造的公共片段长度 11，小于阈值 12 | 测试文本补足到 12 字 |
| Benchmark 用量差值 | `estimated_cost` 为 null 时相减 TypeError | `_usage_delta` 支持 None |
| 续跑预算重置 | 每次进程启动从 0 计调用/token | 从 `ledger.jsonl` 恢复累计预算 |
| 种群重复 Prompt | 变异返回相同文本，选择保留克隆 | 选择时优先去重，再填满 m；记录 duplicate 原因 |
| 变异缓存跨代复用 | 同一父代跨代命中同一缓存，子代不变 | 变异 cache variant 加入 `generation` round |
| API/网络错误被吞 | 生成/评审把 RuntimeError 当普通失败继续烧预算 | 只把 LLMOutputError/ValueError/TypeError 当输出失败；API/网络错误向上传播 |
| 报告缺变异全量 | 被淘汰子代不在最终种群 | 增加 `all_children` 摘要；完整记录仍在 `population/gen_*.json` |
| 报告不完整 benchmark | 预算中止时 benchmark 无 groups | 报告区分“未完成/未执行”，不写伪结果 |

---

## 8. 已做与未做的事

1. **已发起真实 DeepSeek API 调用。** 用户随后提供密钥并授权开始；完成了 `live-haizi-02` 的原型试跑。密钥不应通过聊天传输，完成后应轮换。
2. **没有伪造实验数据。** Mock 产物带 `MOCK` 标记；真实运行结果来自 `ledger.jsonl`、`state.json`、`cache.jsonl` 和 `benchmark.json`。
3. **没有人类评审。** 报告和 README 都注明 Judge 主观性、自评偏差和小样本限制。
4. **没有验证参数最优性。** n=5/m=5/k=5 只是原型默认值。
5. **没有引入 Embedding/RAG/训练/交叉。** 符合任务约束。

---

## 9. 真实运行前的建议（已于 2026-11-25 执行）

1. 先运行 `--mode estimate`，确认调用/token 与预算。
2. 确认 `.env` 中 `DEEPSEEK_API_KEY` 和模型名；如需不同评审模型，设置 `DEEPSEEK_JUDGE_MODEL`。
3. 先用 `--population-size 3 --generations 2 --skip-benchmark` 做小规模 live 试跑，检查真实 JSON 解析、Prompt 规则修复率和单次成本。
4. 检查 `report.md`、`analyzer` 差异分析和 `mutator` 变更记录是否符合诗歌语境。
5. 再运行完整 5×5 + benchmark。
6. 报告真实结果时，必须同时报告：
   - 模型版本与参数
   - 参考/留出集来源与哈希
   - 每代适应度与淘汰原因
   - Judge 模型、rubric 版本、是否同模型
   - API 调用、token、费用
   - 样本量与局限
   - 人工抽查结论（如有）

---

## 10. Live 试跑结果（2026-11-25）

运行：`live-haizi-02`；模型 `deepseek-flash`；生成与评审同模型；所有非生成调用关闭 thinking；最终状态 `completed`。

### 10.1 演化过程

| 代 | 本代最优 | 本代均值 | 标准差 |
|---|---|---|---|
| 1 | 52.63 | 50.54 | 1.64 |
| 2 | 53.61 | 50.79 | 2.15 |
| 3 | 53.88 | 51.63 | 1.50 |
| 4 | 54.56 | 52.15 | 1.76 |
| 5 | 54.56 | 52.85 | 0.97 |

没有触发提前停止，跑满 5 代。最终按确认重评后的种群选择 `g02-m02-1fb0da75`，适应度 **53.6113**（3 次优化题目评估）。确认重评显示明显波动：

| 候选 | 重评前 | 重评后 |
|---|---|---|
| `g04-m00-8d3145a7` | 54.56 | 51.95 |
| `g03-m01-ced788f5` | 53.88 | 51.74 |

这说明单次随机生成会把候选排名抬高或压低；确认重评是必要的，但也意味着“最优”本身仍不稳定。最终选中的 `g02-m02-1fb0da75` 只经过 3 次优化题目评估（score_std=5.39），且未进入确认重评——确认重评只覆盖重评前的 top-2，它们下降后该候选才成为第一。因此这个“最优”适应度可能高估。

### 10.2 独立对照（留出集 + 未参与优化的测试题目）

| 组 | 风格相似度 | 文学质量 | 题意 | 原创性 | 格式通过率 | 复制率 | API 调用 | Token |
|---|---|---|---|---|---|---|---|---|
| A 直接模仿诗人 | **56.23** | 60.00 | 5.00 | 4.00 | 1.00 | 0.00 | 10 | 16,899 |
| B 一次性反推 Prompt | 55.76 | 52.00 | 4.80 | 3.40 | 1.00 | 0.00 | 11 | 23,235 |
| C RPE-GA Prompt | 51.43 | 60.00 | 5.00 | 4.00 | 1.00 | 0.00 | 10 | 19,068 |

按风格相似度：**A > B > C**。

- C − A = **−4.80** 风格分
- C − B = **−4.33** 风格分
- C 与 A 的文学质量、题意、原创性相同；C 的确定性风格分（42.95）低于 A（47.99）和 B（47.89）
- C 的 Judge 风格分（56.0）也低于 A（60.67）和 B（60.0）
- 三组格式全部通过、复制率均为 0

**本次试跑的结论是否定性的：RPE-GA 搜索出的 Prompt 在留出集上没有超过“直接点名模仿”的基线 A，也没有超过一次性反推的基线 B。** 不能把这次结果表述为 RPE-GA 有效。可能的解释包括：最终 Prompt 过长（11 条强约束）并对优化题目过拟合；同模型自评偏差；5 首参考/5 个测试题目样本太小；Judge 对“像”的判断与确定性特征不一致。这些解释仍需实验验证。

### 10.3 实际调用与 token

- ledger 累计：**428 次真实调用**，**1,145,267 token**（输入 834,940 / 输出 310,327），缓存命中 71 次。
- 最后一次完成进程：292 次调用、809,885 token、803 秒；缓存命中 56 次。
- 未配置单价，因此报告不计算费用；需按供应商账单核对。
- 累计值包含中止/修复重跑的调用：`live-haizi-01` 与 `live-haizi-02` 的早期尝试。它们没有进入最终结果，但产生了费用。

### 10.4 本次 live 暴露并修复的问题

1. 生成模型用空字符串表示分节，原校验将其判为无效 → 允许 `lines` 中的空行作为分节，并保留 `raw_lines`。
2. 优化题目要求“12—20 行”，但 `max_lines=18` 与要求冲突 → 统一为 20。
3. `analysis_max_tokens=2200` 触发 `finish_reason=length` → 提高到 4000，并加入截断降级处理。
4. Judge 偶尔输出重复/多余 JSON 对象 → 增加平衡括号提取修复，并在 Judge 提示中要求单对象、精简证据。
5. 续跑时 `_ensure_initial_population` 会把已演化种群重置为初始种群、把 generation 归零 → 修复为仅在新运行时安装初始种群；增加回归测试。
6. 早期一个旧进程未完全退出，与新的 resume 进程并发写 ledger/state，导致重复 gen1 和额外调用 → 最终结果保留为完成链，但必须在 REReport/报告中标注这次运行不是干净的一次性实验。

### 10.5 产物位置

```
experiments/reverse_prompt_engineering/runs/live-haizi-02/
  report.md
  final_prompt.txt
  final_prompt.json
  benchmark/benchmark.json
  benchmark/benchmark.md
  state.json
  ledger.jsonl
  cache.jsonl
  evaluations/
  analyses/
  mutations/
  population/
```

---

## 11. 扩展范围、progression 与长跑（进行中）

### 11.1 扩展范围运行

`live-haizi-expanded-01`：

- 参考诗 15 首、留出诗 13 首、优化题目 5 个、测试题目 10 个
- 运行在 3 代后因 `patience=2` 提前停止
- 独立对照：C 组风格分 **58.63**，A 组 **51.71**，C − A = **+6.92**；C 文学质量 66，A 60
- B 组缺失：一次性反推的 Prompt 复制了参考诗整句“道路前面还是道路”，旧规则把 B Prompt 置空。这是 benchmark 实现问题，已在新代码中改为“替换整句 + 记录干预”，不再整组丢弃
- 这次结果只是描述性单次运行，不能据此宣布 RPE-GA 普遍有效

### 11.2 新增 progression 维度

用户要求加入“有一种东西在推动整首诗发展”的指标，已实现：

- Judge 新增 `progression`：动作/空间/时间/情感/意象关系/视角是否推动全诗，后一节是否改变或加深前一节
- Judge 风格维度从 11 项增加到 12 项；`progression` 权重 **0.24**，其他维度合计 0.76
- 确定性风格分新增 `progression` 代理（转折/推进标记、行首新鲜度、分节变化），权重 **0.10**
- 适应度里 Judge 风格分从等权平均改为可配置加权平均

### 11.3 长跑

`live-haizi-expanded-progression-01` 从已有扩展运行续跑，配置为：

- 最多 30 代；`patience=0`（不因短期无提升自动停止）
- 每 **5 代**保存 `checkpoints/gen_XXX/`：`snapshot.json`、`best_prompt.txt`、`leaderboard.md`
- 逐代完整记录仍在 `population/gen_XXX.json`
- 预算上限：2500 次调用 / 12,000,000 token

截至本次记录：

- 长跑在 02:58 左右、第 22 代后停止：Judge 返回的 `uncertainty` 不是严格的 low/medium/high，旧校验在 3 次重试后抛出 `LLMOutputError`；而异常处理顺序又把 `LLMOutputError` 当成普通 `RuntimeError` 向上抛，导致整个进程退出。
- 已修复：先捕获 `LLMOutputError`，再做截断处理；同时把 `uncertainty` 归一化（medium-high→high、中→medium、低→low、缺失→high）。
- 09:55 已从第 22 代续跑成功，进程正在运行。
- 已有 checkpoint：`gen_005`、`gen_010`、`gen_015`、`gen_020`。
- 最后一次检查：约 1201 次调用、4,137,247 token；当前最优 58.2775，已连续 13 代未显著提升。
- 长跑会继续到第 30 代或预算上限；若再次停止，用同一 run-id 续跑。

### 11.4 八小时后检查位置

```text
experiments/reverse_prompt_engineering/runs/live-haizi-expanded-progression-01/
  checkpoints/gen_005/
  checkpoints/gen_010/
  checkpoints/gen_015/
  ...
  population/gen_XXX.json
  state.json
  ledger.jsonl
```

如果进程因预算或中断停止，使用同一 `run-id` 续跑：

```powershell
python experiments/reverse_prompt_engineering/run.py --mode live --authorize-spend --resume --run-id live-haizi-expanded-progression-01
```

---

## 12. 最终状态

- 代码：已完成，可运行；新增 `progression` 维度、加权 Judge 风格分、B 组污染清洗和每 5 代 checkpoint。
- RPE-GA Mock/单元测试：21 个通过。
- 原有项目回归测试：247 个通过（新增 `tests/__init__.py` 解决本机 `tests` 包遮蔽）。
- `live-haizi-02`：C 未超过 A/B，是明确的负结果。
- `live-haizi-expanded-01`：15 首参考下 C 超过 A（+6.92 风格分），但 B 因旧规则缺失，且只有一次运行，不能作为最终结论。
- `live-haizi-expanded-progression-01`：长跑进行中，最多 30 代，每 5 代 checkpoint；八小时后应检查 `checkpoints/` 与 `population/`。
- 研究结论：**目前没有“可靠且可复现”的最终 Style Prompt**。扩展运行给出了一个正向信号，但需要更干净的复跑、人工评审或跨模型评审来确认。
- 安全：API 密钥曾在聊天中传输，**应立即在供应商控制台轮换/吊销**。`.env` 已被 `.gitignore` 忽略，但密钥已经暴露。

一句话：**工程已能持续多代运行并保留快照；结论仍待长跑和独立评审确认。**
