# 海子风格语料

按 [`selection.json`](selection.json) 的优先级整理《海子诗全编》（西川编，上海三联书店 1997）
正文，供文风分析与本地研究使用。

## 文件

| 文件 | 位置 | 说明 |
|---|---|---|
| `selection.json` | 本目录（纳入仓库） | 核心 30 首、十个风格子库、长诗的篇目与提取假设 |
| `collect.py` | 本目录（纳入仓库） | 抓取、解析、构建语料的可重跑脚本 |
| `manifest.json` | 本目录（纳入仓库） | 全部条目的编号、分级、行数、来源地址与缺篇清单，不含正文 |
| `coverage.md` | 本目录（纳入仓库） | 覆盖报告：核心 30 首核对、子库篇数、长诗缺章 |
| `corpus.jsonl` | `var/haizi/`（gitignored） | 全文字料，一行一篇 |
| `raw/pages/` | `var/haizi/`（gitignored） | 抓取页面的 UTF-8 缓存 |
| `raw/fetch-log.json` | `var/haizi/`（gitignored） | 每个快照的地址、抓取时间与 SHA-256 |

## 来源

目录快照来自 `var/haizi/raw/catalog.html`（《海子诗全编》网页目录）。原站
`www.eywedu.com` 已下线，正文改从 Internet Archive 的同年快照取回；三篇仅在中华诗库
（shitan.org）可见，单独标注来源。`source_verified` 只表示网页与目录条目已核对，
未与纸本逐字校勘；异文与疑字应以印本复核。

## 重新生成

```powershell
python research/haizi/collect.py fetch      # 下载并缓存；已缓存页面会跳过
python research/haizi/collect.py build      # 解析缓存，写 corpus.jsonl 与 manifest.json
python research/haizi/collect.py report     # 重写 coverage.md
```

`fetch` 每次请求间隔约 1 秒，只访问 `web.archive.org` 与 `shitan.org`。404 页面记为
永久缺页，下次运行不再重试。

## 语料格式

每行一个对象，字段沿用 [`poetry_agent/style/corpus.py`](../../poetry_agent/style/corpus.py)：

- `poem_id`：按目录路径生成的稳定编号，如 `haizi-01-001`
- `title` / `text`：网页标题与正文（保留原始分行，空行表示分节）
- `source_url`：实际取回的快照地址
- `period`：所属编次，如「第一编 短诗（1983—1986）」
- `metadata.tier` / `core_rank` / `group` / `focus`：对应 `selection.json` 的分级与提取假设
- `metadata.chapter_count` / `chapters_fetched` / `chapters_complete`：长诗章节覆盖
- `split`：按 `poem_id` 哈希做的确定性划分，默认 10% 留出

## 覆盖与缺口

- 核心 30 首全部取回；目录中同名的两首《秋》分条保留。
- 十个风格子库共 100 条。
- 长诗 10 部中，5 部在归档中只有目录页、没有章节页，未收录正文：
  《太阳·土地篇》《但是水、水》《太阳·大札撒》《太阳·弑》《太阳·你是父亲的好女儿》。
  其余 5 部按已取回的章节拼接，`is_fragment` 标注残缺。
- 补齐长诗的可靠办法是提供《海子诗全集》电子书或纸本扫描；网页转载版本不足以校勘。

## 权利

海子作品及《海子诗全编》的编选内容，权利归作者、编者与出版方。本仓库只提交篇目
与统计，**不分发全文**；正文仅落盘到 `var/`（见 `.gitignore`）。引用时请自行核对来源与授权。
