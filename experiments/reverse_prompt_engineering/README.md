# RPE-GA 中文诗歌逆向提示词工程实验

这是一个**独立**的实验模块，位于 `experiments/reverse_prompt_engineering/`，不改变 VERSEFORGE 原有的诗歌创作工作流。

目标：给定一组真实诗人的参考作品，通过实际生成实验搜索一份可复用的自然语言 **Style Prompt**，使 DeepSeek 在**新的创作题目**下写出在语言组织、句法、分行节奏、意象修辞、情感表达和篇章结构上接近参考作品的诗。

> 这不是恢复诗人的真实创作指令，也不训练/微调任何模型。它寻找的是“具有相似风格控制效果的 Prompt”。

参考论文：*Reverse Prompt Engineering: A Zero-Shot, Genetic Algorithm Approach to Language Model Inversion*（EMNLP 2025）第 3.2、3.3 节及 Figure 5/6。

实施过程、验证记录与未完成事项见仓库根目录 [`REReport.md`](../../REReport.md)。

---

## 1. 当前状态（重要）

| 状态 | 内容 |
|---|---|
| 已实现 | 参考语料选择、初始种群、生成、确定性指标、匿名 LLM 评审、差异分析、LLM 变异、父子代选择、确认重评、断点续跑、缓存、预算上限、A/B/C 对照、报告、独立 Prompt 输出 |
| 已用 Mock 验证 | 全流程、断点续跑、预算中止、缓存、生成隔离、评审匿名、对照分组、报告生成 |
| 已试跑 | 两次真实 DeepSeek 原型试跑：`live-haizi-02`（5 首参考，C 未超过 A/B）与 `live-haizi-expanded-01`（15 首参考，C 超过 A；B 因反推 Prompt 复制原句被旧规则拦截） |
| 长跑完成 | `live-haizi-expanded-progression-01`：15 首参考、13 首留出、5 优化题、10 测试题、`progression` 高权重；第 27 代 `patience=5` 提前停止；最终 `g15-m03`，benchmark C > B > A，但 C 格式通过率 0.8。`final-prompt-validation-01` 强制题目约束后 C 风格 54.94、格式 1.0，高于 A 但低于 B |
| **v3 收敛与盲测通过** | `live-haizi-v3-optimal-01`（详见 [`../../EAReport.md`](../../EAReport.md)）：升级 `rpe-poetry-style-v3` 语料分位带指标、`deepseek-chat` 独立评审与精英语义重组算子后，搜索出 531 字精炼 Prompt（[`optimal_style_prompt.txt`](optimal_style_prompt.txt)）；在 13 首留出诗 × 10 测试题 × 2 次重复（60 首盲测）中 **C（合格率 0.85，合格风格 64.01）> B（0.70，57.26）> A（0.70，55.02）**，同题双合格 C vs B 8 胜 0 负（10 题置换检验 $p=0.0098$） |
| 尚未验证 | 真实人类读者盲评、跨供应商异构家族 Judge（如非 DeepSeek 模型） |
| 未启用 | Style Encoder/Decoder、神经网络 Embedding、RAG、权重/梯度/Logits 访问、参数微调、人类评审 |

**Mock 运行产生的诗歌、评分、分析、适应度和对照结果都是规则模拟数据，不能作为研究结论引用。** 仓库中的 `live-haizi-02` 是真实调用结果；其 C 组没有超过 A/B 基线，不能据此声称 RPE-GA 有效。

---

## 2. 依赖与配置

- Python 3.11+（当前项目在 Python 3.14 下测试）
- 标准库 + 项目已有代码
- `PyYAML`（读取 `config.yaml`）
- 真实调用需要项目根目录 `.env`：

```dotenv
DEEPSEEK_API_KEY=sk-...
DEEPSEEK_MODEL=deepseek-flash
DEEPSEEK_BASE_URL=https://api.deepseek.com
# 可选：用另一个 DeepSeek 模型做评审；仍属同家族，不能消除自评偏差。
# 不同模型家族需要额外客户端，本项目未实现。
DEEPSEEK_JUDGE_MODEL=
```

API 客户端复用 `poetry_agent.client.DeepSeekClient`：只允许官方 HTTPS 主机、不跟随重定向、不自动重试 HTTP 请求。实验层新增了调用/Token 预算、缓存、ledger、JSON 解析重试。

默认参考语料：

```
var/haizi/corpus.jsonl
```

该文件在 `.gitignore` 的 `var/` 下，不随仓库分发；需要本地存在。语料记录保留原始分行、分节、标点和来源。自动选诗会排除正文直接出现诗人姓名的作品，避免姓名触发或身份泄露；原始文本仍完整保存在运行记录的 `run.json` / `corpus` 清单中。

---

## 3. 快速开始

在仓库根目录运行：

```powershell
# 1) 只估算调用次数与 token，不联网
python experiments/reverse_prompt_engineering/run.py --mode estimate

# 2) 完整 Mock 试跑：不调用 API，不产生费用，输出明确标记为 MOCK
python experiments/reverse_prompt_engineering/run.py --mode mock --run-id mock-01

# 3) 真实付费运行：必须先看估算，并显式授权
python experiments/reverse_prompt_engineering/run.py --mode live --authorize-spend --run-id live-01

# 4) 断点续跑（同 run-id，可提高预算）
python experiments/reverse_prompt_engineering/run.py --mode live --authorize-spend --resume --run-id live-01 --max-api-calls 500

# 5) 跳过对照实验（只做 GA）
python experiments/reverse_prompt_engineering/run.py --mode live --authorize-spend --skip-benchmark

# 6) 小规模调试
python experiments/reverse_prompt_engineering/run.py --mode mock --population-size 3 --generations 2 --run-id debug-01
```

`--mode estimate` 是默认值；`--mode live` 没有 `--authorize-spend` 时会拒绝执行并返回 2，不会发起真实请求。

### 预算估算示例（当前默认配置）

```text
population.size=5, generations=5, optimization_topics=3,
generation.repetitions=1, test_topics=5, benchmark.repetitions=1
预计 API 调用：1896 次（30 代长跑；重试上界 5844 次）
预计输入 token：约 7.78M
预计输出 token：约 2.44M—4.88M
预计总 token：约 10.2M—12.7M
配置上限（长跑）：2500 次 / 12,000,000 token
```

这是**估算**，不是承诺；真实值以 `ledger.jsonl` 和供应商账单为准。默认未配置单价，因此不推算费用。

---

## 4. 实验流程

### Phase 1：Initialization

- 从 `corpus.reference_split` 中按 `tier/core_rank/poem_id` 确定性地选 `reference_count` 首参考诗。
- 每首保留原始分行、分节和标点；发送给 LLM 时只保留匿名正文，不含作者、来源、poem_id、split。
- 独立生成 `m` 个候选 Prompt（默认 5 次独立调用），每次给一个不同的“观察角度”（字词、句法、分行、意象、情感、篇章等）。
- 确定性规则拒绝：诗人姓名、参考原句/长片段、依赖“上面/这些诗”等说法、过多套话、过短/过长、可执行指令单元不足。
- 违反规则时最多重写 `max_prompt_repair_attempts` 次。

### Phase 2：Generation

每个候选 Prompt 与**相同的优化题目**组合，通过 DeepSeek 生成诗。生成调用只接收：

- 当前候选 Prompt
- 创作题目
- 体裁、行数、题目要求

不接收参考作品、诗人姓名、候选编号、世代号、评价反馈。生成参数（模型、temperature、max_tokens、thinking）在同一实验内一致。

### Phase 3：Evaluation

**确定性指标（Python，离线）**：

- 字词/字频与 bigram 分布
- 虚词/功能字分布
- 行长分布、分节数、行数、行尾字
- 标点节奏、问句/感叹句比例
- 重复率、独特字比例、代词使用
- 结构与节奏综合相似度
- 字符级 ROUGE-1（仅对照/重合诊断）
- 最长公共连续片段、整句重合检测

**匿名 LLM Judge（Rubric）**：15 个维度，0—5 分，每项必须给短引文证据、理由和不确定性。风格维度 12 项，外加文学质量、题意、原创性：

1. 字词选择与语言习惯
2. 句法结构与表达方式
3. 分行、节奏及韵律
4. 意象组织与修辞手法
5. 情感表达方式
6. 语义组织与篇章结构
7. 推进感与发展动力（progression，单列诊断）
8. 具象与抽象比例
9. 复沓、呼告与回环
10. 人称与呼告关系
11. 神话/历史/文化原型
12. 结尾方式
13. 文学质量
14. 题意符合程度
15. 原创性

Judge 不接收候选 Prompt、候选编号、世代、实验分组或生成策略。

**适应度**：

```text
style = 0.35 × 确定性风格分 + 0.65 × Judge 12 个风格维度加权平均
base  = 0.85 × style + 0.15 × 文学质量
fitness = base - 格式/题意/原创性/质量/复制惩罚
eligible = 格式通过 且 无复制 且 题意≥阈值 且 原创性≥阈值 且 质量≥下限
```

v2 默认将推进感强度和确定性表面代理单列为诊断，两者在作者风格分中权重均为 0。结构维度仍评价与参考诗的组织方式是否接近。合格率以所有评估尝试为分母，合格风格分仅在通过全部约束的诗中取均值，无合格诗时留空。

风格是主要项；题意、体裁、原创性和文学质量作为必要约束。`ROUGE-1` 不参与风格主分，避免把“抄得像”误判为“风格像”。

### Phase 4：Difference Analysis

对每个候选，LLM 对照参考诗和生成诗，输出：

- 已复现/未复现的风格特征
- 生成作品多出、参考作品没有的倾向
- Prompt 中无效、含糊、重复或冲突的指令
- 是否过度依赖特定题材/意象
- 文本证据、`observation` vs `interpretation`、置信度
- 可操作的修改建议

### Phase 5：Mutation

每个父代产生**一个**子代。LLM 根据差异分析修改 Prompt，允许：增加、删除、替换、拆分、合并、调整具体程度、修复冲突。必须保留已证明有效的部分，并记录每条变更的 `op/target/reason`。优化对象始终是 Prompt，不直接修改生成的诗。

### Phase 6：Selection

1. 当前种群 `m` 个父代。
2. 每个父代产生 1 个子代。
3. 子代实际生成并评价。
4. 合并父代 + 子代，先按合格率、再按合格作品风格均分排序，同分时参考适应度、文学质量和稳定性，取前 `m`。
5. 重复到最大轮数、预算耗尽或提前停止（连续 `patience` 代无显著提升）。
6. 默认无交叉，保持与论文核心算法一致。
7. 对最终高分候选追加 `confirmation_repetitions` 次新生成样本再重排，降低单次随机波动。

### Phase 7：Final Validation

用**从未参与优化**的测试题目和**留出集**真实诗歌做独立测试：

- **Baseline A**：直接要求模仿目标诗人（按题目生成模仿指令）。
- **Baseline B**：LLM 阅读参考作品后，一次性反推一个 Prompt。
- **Experimental C**：RPE-GA 最优 Prompt。

三组使用相同测试题目、留出参考集、生成参数和评审 rubric；Judge 不知道分组。对照报告使用相同的两项排序指标，另列 C 与基线在相同题目和重复编号、双方都合格时的风格分差，按题等权。最终查重覆盖已选训练参考与留出作品，风格评审只使用留出作品。v1 断点包含旧评分，v2 新运行使用独立 run-id。

---

## 5. 配置说明

配置文件：`experiments/reverse_prompt_engineering/config.yaml`

| 配置 | 说明 |
|---|---|
| `corpus.reference_count` | 参考诗数量（当前 15） |
| `corpus.reference_poem_ids` | 显式指定参考诗；留空自动选择 |
| `corpus.held_out_count` | 留出诗数量（当前 13） |
| `corpus.exclude_target_name_in_auto_selection` | 自动排除正文含诗人姓名的作品（默认 true） |
| `topics.optimization` | 优化题目列表（当前 5） |
| `topics.test` | 独立测试题目列表（当前 10） |
| `population.size` | 种群规模 m（当前 5） |
| `population.generations` | 最大演化轮数 k（长跑配置 30；小规模调试用 CLI 覆盖） |
| `population.patience` | 连续无提升提前停止；0 表示关闭（长跑配置为 0） |
| `population.checkpoint_every` | 每 N 代保存 `checkpoints/gen_XXX/` 快照；0 关闭 |
| `population.max_prompt_repair_attempts` | Prompt 规则修复次数 |
| `population.checkpoint_every` | 每 N 代保存一次快照 |
| `generation.repetitions` | 每个题目重复生成次数 |
| `generation.temperature` / `max_tokens` / `thinking` | 生成参数 |
| `evaluation.judge_model` | 另一个 DeepSeek 评审模型；null 表示同生成模型。仍是同家族 |
| `evaluation.*_weight` | 风格/质量权重 |
| `evaluation.*_threshold` | 题意、原创性、质量约束 |
| `evaluation.confirmation_top_k` | 最终追加重评的高分候选数 |
| `evaluation.confirmation_repetitions` | 追加重评次数 |
| `budget.max_api_calls` | 硬调用上限 |
| `budget.max_total_tokens` | 硬 Token 上限（按实际 usage 累计） |
| `budget.price_per_million_*` | 可选单价；留空只统计 token |
| `benchmark.enabled` | 是否运行 A/B/C |
| `benchmark.baseline_a_prompt` | 基线 A 模板，必须含 `{topic}` |

所有参数在 `config.py` 中有校验；非法组合会在调用 API 前报错。CLI 可覆盖 `--max-api-calls`、`--max-tokens`、`--generations`、`--population-size`、`--seed`、`--output-root`。

---

## 6. 运行目录与数据管理

默认输出到：

```
experiments/reverse_prompt_engineering/runs/<run_id>/
```

典型文件：

```
run.json                    运行元数据、完整配置、语料选择、题目、模式、警告
state.json                  当前状态、种群、全部评估摘要、最终 Prompt
events.jsonl                追加式事件流
ledger.jsonl                每次 API 调用/缓存命中的调用与 token 记录（不含密钥）
cache.jsonl                 请求与响应缓存，用于审计和断点续跑
initial_population.json     初始种群
population/gen_###.json     每代父代、子代、幸存者、淘汰原因、排名
checkpoints/gen_###/        每 5 代快照：snapshot.json、best_prompt.txt、leaderboard.md
evaluations/<candidate>.json 每个候选的生成作品、确定性指标、Judge 评分与证据
analyses/<candidate>.json   差异分析
mutations/<child>.json      子代 Prompt、父子关系、变更记录
benchmark/benchmark.json    A/B/C 完整结果
benchmark/benchmark.md      对照实验报告
final_prompt.json           最优 Prompt 及指标
final_prompt.txt            可直接使用的纯文本 Style Prompt
final_population.json       最终种群完整记录
report.md                   总报告（含适应度轨迹、初始 vs 最终 diff）
```

- 断点续跑会复用 `cache.jsonl`，并把 `ledger.jsonl` 的历史调用恢复到累计预算中。
- **不要对同一个 `run-id` 并发启动多个进程**：预算恢复和状态写入按单进程设计；并发进程会造成重复代、额外调用和 ledger/state 竞争。若进程被强杀，先确认没有残留进程再 resume。
- 缓存键包含模型、system/user、max_tokens、thinking、temperature 和实验内的 variant；生成阶段用 candidate/topic/repetition 作为 variant，保证重复生成是新样本，而续跑能命中已完成样本。
- 报告中的 `estimated_cost` 只有在配置了单价时才计算；否则为 null。

---

## 7. 测试

```powershell
python -m unittest discover -s experiments/reverse_prompt_engineering/tests -v
```

当前覆盖：

- 语料选择、参考/留出集不重叠、匿名块不含姓名/来源/poem_id
- 确定性指标、ROUGE-1、复制诊断、Prompt 规则
- 缓存命中不消耗 API、预算中止、ledger 恢复
- Mock 全流程、产物完整性、生成隔离、Judge 匿名
- 预算耗尽后断点续跑
- live 模式未授权时在联网前拒绝

Mock 测试不访问网络、不使用密钥、不产生费用。测试中的作品与分数均为模拟数据。

---

## 8. 已知局限

1. **不是 Prompt 恢复**：真实诗人没有可恢复的原始 Prompt；本实验只寻找相似风格控制效果。
2. **确定性指标是代理**：字频、行长、标点等不能完整代表诗歌风格；权重未经人类相关性验证。
3. **LLM Judge 有主观性**：默认可能与生成模型同家族，存在自评偏差；即使通过 `DEEPSEEK_JUDGE_MODEL` 切换模型，仍是 DeepSeek 家族。已做独立调用、匿名和 JSON 约束，但仍需人工抽查。
4. **样本仍有限**：15 首参考诗、10 个测试题目、单模型；长跑可增加代数和快照，但仍不能自动获得统计显著性。
5. **题目/题材泄漏风险**：优化题目与测试题目人为区分，但无法完全排除模型世界知识对风格判断的影响。
6. **费用与价格**：实际单价变化；只有配置单价时才计算费用。
7. **评审模型家族边界**：真实运行已采用 `deepseek-flash` 生成 + `deepseek-chat` 独立匿名评审，并结合纯离线字符 TF-IDF 归属核验；但两者仍属同一供应商家族，审美结论建议辅以人工盲读。

---

## 9. 与论文方法的差异

详见 `METHOD_ADAPTATION.md`。一句话概括：

> 保留 RPE-GA 的“初始化 → 生成 → 评价 → 差异分析 → LLM 变异 → (μ+λ) 选择”骨架和 mean/max 思想；把 ROUGE-1 原文相似度替换为诗歌多维风格适应度，并加入题意、原创性、文学质量约束、匿名 Judge、留出集独立测试、缓存/预算/断点续跑。没有引入交叉、训练、Embedding 或 RAG。

---

## 10. 文件结构

```
experiments/reverse_prompt_engineering/
  config.yaml          实验参数
  run.py               入口：estimate / mock / live / resume
  config.py            配置合并与校验
  corpus.py            参考语料选择、匿名化、留出集
  metrics.py           确定性诗歌风格指标、ROUGE-1、复制诊断
  validation.py        Prompt 规则与 JSON schema
  llm.py               预算、缓存、ledger、JSON 重试、真实客户端封装
  mock.py              离线的规则 Mock（不调用 API）
  initializer.py       Phase 1
  generator.py         Phase 2
  evaluator.py         Phase 3
  analyzer.py          Phase 4
  mutator.py           Phase 5
  optimizer.py         Phase 6
  benchmark.py         Phase 7
  report.py            Markdown 报告
  store.py             运行目录、状态、事件
  tests/               Mock 与单元测试
```
