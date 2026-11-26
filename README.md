# 诗词创作 Agent

Python 3.11+，标准库运行，调用 DeepSeek API。当前聚焦文本审美、创作、改稿与格律；按用户最新选择，不推进参数训练或朗读开发。

直接看：[六篇真实 API 作品](WORKS.md)。研究依据：[审美基础](research/aesthetic-foundation.md)、[逐篇目录](research/reading-catalog.md)。候选不等于比赛定稿，也没有已验证的整体质量提升结论。

## 开始运行

**网页入口：**双击本目录的 `启动创作台.cmd`，打开 **http://127.0.0.1:8765**。可粘贴完整样题、生成、换个构思再写、复制和下载作品，历史保存在本机。已经配置的 `.env` 直接由服务端读取，不在网页填写密钥。详见[本地创作台](WEB_STUDIO.md)。

在本目录打开终端，先离线检查入口：

```powershell
python main.py --task examples/modern.json --mock
```

mock 固定输出，不使用密钥、不调用 API，不能评价创作质量。词类暂无专用 mock 作品，固定示例可能无法通过其分句要求。

真实运行读取本目录 `.env` 或同名环境变量，环境变量优先。配置项见 `.env.example`；已有 `.env` 时直接编辑，不覆盖。密钥不要写进任务或聊天。默认模型 deepseek-flash；仅允许官方 HTTPS 主机，禁止重定向，不自动重试 HTTP 请求。

```powershell
python main.py --topic 雨后的公交站 --max-lines 10 --aesthetic
python main.py --topic 雨后的公交站 --max-lines 10 --aesthetic --candidates 2
python main.py --topic 雨后春江 --genre qijue --qijue-pattern ping_rhyme --aesthetic
python main.py --topic 雨后巷中候人 --genre wujue --wujue-pattern ze_no_rhyme --aesthetic
python main.py --topic 雨后小城 --genre ci --ci-profile baixiang_yijiangnan_liyu
```

真实调用会产生供应商费用。`--max-revisions 0`只生成一次；多候选时每个候选仍可各生成一次并参与比较。`--task 文件.json`读取完整任务，任务相关命令行字段不覆盖文件；预算、候选数等工作流参数仍生效。

## 当前检查范围

| 体裁 | 已实现 | 未完成 |
|---|---|---|
| modern | 正文行数上限、必用词／禁用词；可选文学审读 | 没有确定性的文学或音韵美评分 |
| qijue | 四句七字；可指定四种基本谱；与网页平水主表核对、定位明确不符 | 完整语境辨音、全部异体覆盖、所有变格与完整合律认证 |
| wujue | 四句五字；须指定四种律绝基本谱之一；平仄与韵脚核对、结构化修订反馈；支持逐稿绑定的离线核音记录 | 古绝、所有变格、完整自动语境辨音；核音判断仍需有字书依据 |
| ci | 指定白香词谱李煜例作忆江南；五句3／5／7／7／5字、指定平仄；按词林十九部网页主字表核韵脚并反馈明确冲突 | 其他词牌、原书校勘、完整语境辨音；缺字、多读及多归部仍待核 |

七绝起式：ping_rhyme、ping_no_rhyme、ze_rhyme、ze_no_rhyme。不指定起式时不强加基本谱。词必须指定 ci_profile；不把同名词牌所有变体视为同一模板。

谱中的 X 为可平可仄，记作 not_required，不表示该字读音已经确定。平仄与韵部独立，多音字不自动挑能过关的一音，未知不升级为合律。韵书网页主表已有106个分组与快照校验值，但未完成原书逐字校勘。

平水与词林字表现接入固定版本OpenCC单字候选，不修改原稿。每个派生归部记录字形来源及全部候选；一对多候选声调不同时保留unknown，任一候选缺证也不以已知子集判通过。所有候选声调一致时可核这一声调要求，但不表示义项已选择，韵部仍独立判断。具体规则、许可证与历史诗稿重检见[字形候选说明](research/glyph-candidates-01.md)。

任务支持 topic、genre、max_lines、required_words、forbidden_words、extra_requirements、qijue_pattern、wujue_pattern、ci_profile。关键词只查正文，不查标题；附加要求由模型理解，程序并未确定性验证全部自然语言条件。

## 审读、修订与选稿

`--aesthetic`按体裁增加文学审读，先保护有效表达，再提出一项关键问题和修改代价；保留决定也必须回应合理质疑。程序核对引文与结构，不保证模型的解释正确。单字变化也可能影响意义，不按改字数量判断价值。

`--revision-scope local`默认不增加基准稿行数，改动行数至多为基准行数的三分之一向下取整（至少一行）；字符数可增加原稿的10%向上取整，增量至少2、至多12字符。按整行对齐计算替换、删除与插入，累计相对于第一份审美修订基准检查，不因多轮重置额度；标题不计入。这是工程范围限制，不保证语义或美感得到保留，换行调整也计入改动。`rewrite`允许在题目上限内重写。硬条件修复在建立审美修订基准前不受这一范围限制。具体证据见[局部修订说明](research/local-revision-scope-01.md)。

指定基本谱的连续修订现记录`metrical_transition`：原错误修好、原错误变未知、新增错误、已通过检查退步等分别列出；下一次修订会收到该对照。错误数量减少不自动算修好，变化记录也不作为文学分数或新的硬门槛。见[格律变化核对](research/meter-transition-01.md)。

另有独立的[句级候选修复实验](research/line-repairs-01.md)：`repair_lines.py`从已有运行稿出发，每个问题句最多提议两种替代，程序组合重查，并将规则通过与待语境复核的稿子分开保留。不会自动替换原稿，尚未接入默认创作流程。

同等硬条件候选以带双方短引文的正反序模型比较选择；两次映射回原稿别一致才采用偏好，分歧或未完成则保留已有稿，并记录弃权原因（不等于两稿等优）。`--candidates 2`可独立生成两稿（最多3稿），先比较硬条件，再比较同等候选，不保证比单稿好。

现代诗有默认关闭的正面示例实验：`--aesthetic --aesthetic-examples`读取三处用户认可的项目原句、用户点评摘录和单独标明的助手分析。只发给生成／修订，不把这些例子和用户喜好送入审读或选稿。示例及来源均核对字节校验值，不是参数微调，也未证明提高质量。

可加`--generation-thinking disabled`或`enabled`显式选择生成思考模式；省略时沿用服务默认。该参数不改变审读与比较各自的非思考设置。对照实验应保持两组模式一致，截断输出仍按失败记录，不自动续写。示例实验与两轮实测见[记录](research/aesthetic-example-memory-01.md)。

比较记录注明independent（不同创作候选）或revision（较早稿与后续修订）。前者分别评价整体关系，后者另核修改所得与损失，不把所有B稿默认视为改稿。

默认单候选最多3次生成、2次审读、4次比较调用（最多两对，每对正反序各一次）；多候选还增加跨候选的双向比较。`--budget`为共享时间预算（1—600秒），不是硬实时截止；预算、失败或提前保留会减少调用。无完成审读不等于认可原稿，失败类型写入记录。

请求使用[官方 JSON 输出](https://api-docs.deepseek.com/guides/json_mode/)；审读和比较明确关闭思考模式，生成保留服务默认设置，输出上限4096。结束截断、空正文、无效引文均不自动当成功。实际请求设置在新运行记录中保存，旧记录不回写。

## 结果与证据

逐字语境复核可离线执行：`python review_meter.py --run 运行记录.json --ledger 读音复核表.json --output 新报告.json`。复核表须绑定正文校验值、字位、义项、声韵、出处与理由；诗稿改动会拒绝旧表。输出记录输入文件校验值，不覆盖已有文件，不调用API。支持指定基本谱五绝、七绝及当前指定词谱；五绝与词的核音表须显式声明genre。词韵另填ci_rhyme_part与ci_rhyme_source，不由平水韵名自动推部。复核人提供的字书判断不是程序独立认证。

每次创作保存 `runs/<run_id>.json`，包括原题、候选、审读、比较、用量和耗时，不含请求头或 API 密钥。多稿另有 candidate_runs／candidate_selection。

constraints_passed 只表示已实现条件未发现失败，不认证文学质量、原创性或全部格律。needs_review 表示仍有已记录问题。退出码0／2／1分别为当前条件通过／待复核／运行错误。

五绝、七绝的 prosody 与词的 ci_evidence 分别保留有限检查结果；外层格律状态仍待核。具名语境复核另存文件，不能把原稿的复核结论直接转给修订稿。作品集中的忆江南已有[限定读法的复核记录](runs/ci-rain-town-context-report.json)，不将它代替原始自动报告。

`.env`及`runs/`在忽略列表内。历史独立朗读工具与训练准备脚本保留，但不属于当前阶段工作，也未完成参数训练。旧 `--speak` 仅打印模拟文本，不连接机器人。

## 验证与研究工具

风格相似度与语料归属可离线执行：`python style_similarity.py --corpus 海子=var/haizi/corpus.jsonl --corpus 北岛=var/beidao/corpus.jsonl --text "……"`。字符 1—2gram TF-IDF 余弦，纯标准库，与 scikit-learn 口径核对的最大偏差为 9.2e-15；输出近邻投票、各语料平均相似度与最近邻清单，不产生质量分。`--parity` 仅在开发环境装有 sklearn 时做口径校验。结论与限制见[基线对照](research/style-similarity-baseline-01.md)：真实语料上 1-NN 约 0.81—0.84，监督分类器可达 0.88—0.92，每位作者至少 8 首、16 首以上才稳定；公开的 560M 风格嵌入在同一语料上与 n-gram 持平，且对“同体裁不同作者”只有 0.015 的薄差，不引入。

```powershell
python -m unittest discover -s tests
python evaluate.py --mock --count 4
python diagnose_reviews.py
python export_works.py
```

测试不发起付费 API 调用。evaluate.py 去掉 mock 可做真实成对流程对照；审稿只看 blind.json，raw.json 与 mapping.json由组织者另存。不同流程调用成本不相同，单次探索不能证明稳定收益。

diagnose_reviews.py 加 --live 才调用真实接口；诊断问题不发送给模型，结果不自动转为训练标签。export_works.py 从既有记录导出作品，不调用 API。

现有真实试验说明工作流能出稿、审读、修订和比较，也保留了失败与未采纳改稿。它们尚未证明公认的审美提升。比赛可接受平台、题材、人工改稿及提交形式仍以主办方规则为准；命令行项目不等于已完成组委会访问交付。

双向选稿的协议、真实分歧记录和局限见[研究说明](research/bidirectional-selection-01.md)。一致判断不等于审美正确；所有候选和两次理由保留供复核。

八句律诗等已有谱体的整稿提议可用 `repair_poem.py`。它保留原稿、仅调用一次、重新检查并记录前后字位变化，不自动覆盖或把未知当出律；用法和真实失败提议见[整稿修订记录](research/whole-repair-01.md)。
