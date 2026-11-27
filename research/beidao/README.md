# 北岛风格语料

按 [`selection.json`](selection.json) 的优先级整理中华诗库《北岛诗集》网页正文，
供文风分析与本地研究使用。结构沿用 [`research/haizi/`](../haizi/README.md)。

## 文件

| 文件 | 位置 | 说明 |
|---|---|---|
| `selection.json` | 本目录（纳入仓库） | 核心 30 首、十个风格子库、长诗《白日梦》的篇目与提取假设 |
| `collect.py` | 本目录（纳入仓库） | 抓取、解析、构建语料的可重跑脚本 |
| `manifest.json` | 本目录（纳入仓库） | 全部条目的编号、分级、行数、来源地址，不含正文 |
| `coverage.md` | 本目录（纳入仓库） | 覆盖报告：分节篇数、核心篇目、子库篇数 |
| `corpus.jsonl` | `var/beidao/`（gitignored） | 全文字料，一行一篇 |
| `raw/pages/` | `var/beidao/`（gitignored） | 抓取页面的 UTF-8 缓存 |
| `raw/fetch-log.json` | `var/beidao/`（gitignored） | 每个快照的地址、抓取时间与 SHA-256 |

## 来源

目录与正文取自 [中华诗库·北岛诗集](https://www.shigeku.com/shiku/xs/beidao/index.htm)，
同一数据库另有 `shiku.org`、`shitan.org`、`shiren.org` 镜像。目录按网页原有编号
`100—813` 分八节，正文逐篇取回；`000.htm` 为诗人简介，不计入语料。

网页未注明纸本版本。`source_verified` 只表示网页与目录条目已核对，**未与纸本逐字校勘**；
异文、错字与可疑断行应以《北岛诗选》等印本复核。

## 重新生成

```powershell
python research/beidao/collect.py fetch      # 下载并缓存；已缓存页面会跳过
python research/beidao/collect.py build      # 解析缓存，写 corpus.jsonl 与 manifest.json
python research/beidao/collect.py report     # 重写 coverage.md
```

`fetch` 每次请求间隔约 1 秒。站点偶发「服务器太忙」页，脚本会退避重试。

## 语料格式

每行一个对象，字段沿用 [`poetry_agent/style/corpus.py`](../../poetry_agent/style/corpus.py)：

- `poem_id`：`beidao-` 加目录编号，如 `beidao-109`
- `title` / `text`：网页标题与正文（保留原始分行，空行表示分节）
- `source_url`：实际取回的地址
- `period`：网页分节，如「一、（1972-1986）」「七、《今天》（二零零一）」
- `metadata.tier` / `core_rank` / `group` / `focus`：对应 `selection.json` 的分级与提取假设
- `metadata.catalog_path` / `catalog_title`：目录编号与目录写法
- `split`：按 `poem_id` 哈希做的确定性划分，默认 10% 留出

未进入核心或风格子库的其余篇目仍会收录，`tier=B`、`group=未分组`。

## 覆盖与缺口

- 目录共 203 首，全部取回；核心 30 首、十个子库与长诗《白日梦》均在其中。
- 《白日梦》按网页版本收录（510 行），未与其他版本比对。
- 网页无注释、无异文校记；长诗分节以数字标出，未见章节标题。
- 同名《无题》多首按目录编号分条保留，不合并。

## 权利

北岛作品权利归作者及出版方。本仓库只提交篇目、分级与统计，**不分发全文**；
正文仅落盘到 `var/`（见 `.gitignore`）。语料仅供本地文风研究，不能据此主张
再分发或商业训练许可；引用时请自行核对来源与授权。
