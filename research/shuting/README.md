# 舒婷风格语料

按 [`selection.json`](selection.json) 的优先级整理中华诗库《舒婷诗选》网页正文，
供文风分析与本地研究使用。结构沿用 [`research/haizi/`](../haizi/README.md)。

## 文件

| 文件 | 位置 | 说明 |
|---|---|---|
| `selection.json` | 本目录（纳入仓库） | 核心 16 首、四个风格子库的篇目与提取假设 |
| `collect.py` | 本目录（纳入仓库） | 抓取、解析、构建语料的可重跑脚本 |
| `manifest.json` | 本目录（纳入仓库） | 全部条目的编号、分级、行数、来源地址，不含正文 |
| `coverage.md` | 本目录（纳入仓库） | 覆盖报告：篇数、核心篇目、子库篇数、已知缺口 |
| `corpus.jsonl` | `var/shuting/`（gitignored） | 全文字料，一行一篇 |
| `raw/pages/` | `var/shuting/`（gitignored） | 抓取页面的 UTF-8 缓存 |
| `raw/fetch-log.json` | `var/shuting/`（gitignored） | 快照地址、抓取时间与 SHA-256 |

## 来源

取自 [中华诗库·舒婷诗选](https://www.shigeku.com/shiku/xs/shuting.htm)。该页把 35 首
放在同一 HTML 里，以 `<a name="1">…<a name="35">` 锚点分隔；解析时按锚点切分，
诗末创作日期移入 `metadata.composed`，题记保留在正文之前。

同一数据库另有 `shiku.org`、`shitan.org`、`shiren.org` 镜像，内容相同。
网页未注明纸本版本。`source_verified` 只表示网页与目录条目已核对，**未与纸本逐字校勘**；
网页存在错字（如《神女峰》「美丽的优伤」），应以《舒婷的诗》等印本复核。

## 重新生成

```powershell
python research/shuting/collect.py fetch     # 下载并缓存单页
python research/shuting/collect.py build     # 解析缓存，写 corpus.jsonl 与 manifest.json
python research/shuting/collect.py report    # 重写 coverage.md
```

## 语料格式

每行一个对象，字段沿用 [`poetry_agent/style/corpus.py`](../../poetry_agent/style/corpus.py)：

- `poem_id`：`shuting-` 加页面锚点序号，如 `shuting-33`
- `title` / `text`：标题与正文（保留原始分行，空行表示分节）
- `source_url`：实际取回的地址
- `period`：网页没有分期，统一为 `null`
- `metadata.tier` / `core_rank` / `group` / `focus`：对应 `selection.json` 的分级与提取假设
- `metadata.composed` / `subtitle`：诗末日期与副题、题记
- `split`：按 `poem_id` 哈希做的确定性划分，默认 10% 留出

## 覆盖与缺口

- 网页 35 首全部收录，其中核心 16 首、子库 19 首。
- **缺代表作**：《致橡树》《双桅船》《会唱歌的鸢尾花》《落叶》《思念》《也许》等
  均不在此页，语料不能代表舒婷创作全貌，更不能据此断言风格边界。
- 补足办法：另找可核对的来源，把篇目与本地缓存路径加入 `selection.json`，再重跑 build；
  或提供《舒婷的诗》电子书／纸本扫描后单独导入。
- 网页没有创作年表以外的分期信息，`period` 为空，只能依据 `composed` 粗排时间。

## 权利

舒婷作品权利归作者及出版方。本仓库只提交篇目、分级与统计，**不分发全文**；
正文仅落盘到 `var/`（见 `.gitignore`）。语料仅供本地文风研究，不能据此主张
再分发或商业训练许可；引用时请自行核对来源与授权。
