# VERSEFORGE · 诗词创作 Agent

Python 3.11+，标准库运行，调用 DeepSeek API。当前聚焦文本审美、创作、改稿与格律；按用户最新选择，不推进参数训练或朗读开发。

直接看：[六篇真实 API 作品](WORKS.md)。研究依据：[审美基础](research/aesthetic-foundation.md)、[逐篇目录](research/reading-catalog.md)。候选不等于比赛定稿，也没有已验证的整体质量提升结论。

## 开始运行

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
python main.py --topic 雨后小城 --genre ci --ci-profile baixiang_yijiangnan_liyu
```

真实调用会产生供应商费用。`--max-revisions 0`只生成一次；多候选时每个候选仍可各生成一次并参与比较。`--task 文件.json`读取完整任务，任务相关命令行字段不覆盖文件；预算、候选数等工作流参数仍生效。

## 当前检查范围

| 体裁 | 已实现 | 未完成 |
|---|---|---|
| modern | 正文行数上限、必用词／禁用词；可选文学审读 | 没有确定性的文学或音韵美评分 |
| qijue | 四句七字；可指定四种基本谱；与网页平水主表核对、定位明确不符 | 完整语境辨音、简繁异体、所有变格与完整合律认证 |
| ci | 指定白香词谱李煜例作忆江南；五句3／5／7／7／5字及所选谱体平仄 | 其他词牌、完整词韵及语境辨音 |

七绝起式：ping_rhyme、ping_no_rhyme、ze_rhyme、ze_no_rhyme。不指定起式时不强加基本谱。词必须指定 ci_profile；不把同名词牌所有变体视为同一模板。

谱中的 X 为可平可仄，记作 not_required，不表示该字读音已经确定。平仄与韵部独立，多音字不自动挑能过关的一音，未知不升级为合律。韵书网页主表已有106个分组与快照校验值，但未完成原书逐字校勘。

任务支持 topic、genre、max_lines、required_words、forbidden_words、extra_requirements、qijue_pattern、ci_profile。关键词只查正文，不查标题；附加要求由模型理解，程序并未确定性验证全部自然语言条件。

## 审读、修订与选稿

`--aesthetic`按体裁增加文学审读，先保护有效表达，再提出一项关键问题和修改代价；保留决定也必须回应合理质疑。程序核对引文与结构，不保证模型的解释正确。单字变化也可能影响意义，不按改字数量判断价值。

`--revision-scope local`默认限制审美修订不增加基准稿行数及总字符数，仅控制篇幅，不保证只改几个字。`rewrite`允许在题目上限内重写。硬条件修复在建立审美修订基准前不受这一篇幅限制。

同等硬条件候选以带双方短引文的模型比较选择；平局或失败保留已有稿。`--candidates 2`可独立生成两稿（最多3稿），先比较硬条件，再比较同等候选，不保证比单稿好。

默认单候选最多3次生成、2次审读、2次比较；多候选还增加跨候选比较。`--budget`为共享时间预算（1—600秒），不是硬实时截止；预算、失败或提前保留会减少调用。无完成审读不等于认可原稿，失败类型写入记录。

请求使用[官方 JSON 输出](https://api-docs.deepseek.com/guides/json_mode/)；审读和比较明确关闭思考模式，生成保留服务默认设置，输出上限4096。结束截断、空正文、无效引文均不自动当成功。实际请求设置在新运行记录中保存，旧记录不回写。

## 结果与证据

逐字语境复核可离线执行：`python review_meter.py --run 运行记录.json --ledger 读音复核表.json --output 新报告.json`。复核表须绑定正文校验值、字位、义项、声韵、出处与理由；诗稿改动会拒绝旧表。输出记录输入文件校验值，不覆盖已有文件，不调用API。仅支持指定基本谱七绝；复核人提供的字书判断不是程序独立认证。

每次创作保存 `runs/<run_id>.json`，包括原题、候选、审读、比较、用量和耗时，不含请求头或 API 密钥。多稿另有 candidate_runs／candidate_selection。

constraints_passed 只表示已实现条件未发现失败，不认证文学质量、原创性或全部格律。needs_review 表示仍有已记录问题。退出码0／2／1分别为当前条件通过／待复核／运行错误。

七绝的 prosody、词的 ci_evidence 分别保留有限检查结果；外层格律状态仍待核。人工语境复核另存文件，不能把原稿的复核结论直接转给修订稿。

`.env`及`runs/`在忽略列表内。历史独立朗读工具与训练准备脚本保留，但不属于当前阶段工作，也未完成参数训练。旧 `--speak` 仅打印模拟文本，不连接机器人。

## 验证与研究工具

```powershell
python -m unittest discover -s tests
python evaluate.py --mock --count 4
python diagnose_reviews.py
python export_works.py
```

测试不发起付费 API 调用。evaluate.py 去掉 mock 可做真实成对流程对照；审稿只看 blind.json，raw.json 与 mapping.json由组织者另存。不同流程调用成本不相同，单次探索不能证明稳定收益。

diagnose_reviews.py 加 --live 才调用真实接口；诊断问题不发送给模型，结果不自动转为训练标签。export_works.py 从既有记录导出作品，不调用 API。

现有真实试验说明工作流能出稿、审读、修订和比较，也保留了失败与未采纳改稿。它们尚未证明公认的审美提升。比赛可接受平台、题材、人工改稿及提交形式仍以主办方规则为准；命令行项目不等于已完成组委会访问交付。
