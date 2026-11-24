# prophet-vault

**把 Prophet 精算模型变成可检索、可互链、可版本对比的知识库。**

[![tests](https://github.com/f895726831-code/Prophet_Vault/actions/workflows/ci.yml/badge.svg)](https://github.com/f895726831-code/Prophet_Vault/actions/workflows/ci.yml)

[English](README.md) | 简体中文

---

Prophet 模型存放在二进制工作区里：一个 Firebird 数据库（`PROPHET.PRW`）加上若干索引文件。
模型能跑，但查不了。本应十秒钟解决的问题，往往要花半天：

| 问题 | 没有这套工具 | 有这套工具 |
|---|---|---|
| `NET_CF` 到底怎么算的？ | 打开 Prophet，逐个变量翻 | 在知识库里搜到，一键查看 |
| 改了 `DUR_M` 会影响什么？ | 没人说得清，只能跑一遍看报不报错 | 依赖图谱，一键展开上下游 |
| 这个月和上个月的模型差在哪？ | 二进制文件，`diff` 毫无用处 | 结构化的变更报告 |
| 这个变量属于哪个 Library？ | 九个 Library 手工翻 | 页面上直接标注 |

本仓库即为此而做的工具中**可复用的部分**。它读取 Prophet 工作区，对全部变量、公式、
Indicator 与依赖关系生成**带版本的快照**，再把快照渲染成两种形态：

* **Obsidian 知识库** —— 每个变量一个 Markdown 页面，用 `[[wikilink]]` 表达引用关系，
  配 Mermaid 依赖图，于是 15,000 个变量的模型变得可以浏览；索引表在构建时算好，无需任何 Obsidian 社区插件；
* **单文件依赖图谱** —— 一个 HTML 页面，只渲染当前焦点变量及其 1~3 层邻居，
  在 Obsidian 自带图谱卡顿的规模下依然流畅；默认从 CDN 加载 ECharts，
  用 `--echarts` 可内联成完全离线的单文件。

该工具在约 15,000 个变量、26,000 条公式块、550 个已声明 Indicator 的生产模型上验证过，
并被组织成可复用于其他 Prophet 工作区、也可改造成其他建模平台适配器的形式。

---

## 快速开始（不需要装 Prophet）

包内自带合成模型生成器，几十秒即可看到全部产物：

```bash
git clone https://github.com/f895726831-code/Prophet_Vault.git
cd Prophet_Vault
pip install -e .

python -m prophet_vault demo --out examples
```

生成内容：

```
examples/
├── snapshots/demo_2026-01/     # 146 个变量，"上个月"
├── snapshots/demo_2026-02/     # 148 个变量，"这个月"
├── diffs/demo_diff.json        # 新增 3、删除 1、公式变更 1 ...
├── diffs/demo_diff_report.md   # 人类可读的变更报告
├── vault/                      # Obsidian 知识库，用 Obsidian 打开此文件夹
└── dependency-graph.html       # 任意浏览器打开
```

`vault/` 每次运行都会重新生成，因此不纳入仓库（见 [`examples/README.md`](examples/README.md)）。

打开 `examples/dependency-graph.html`，在左侧搜索变量名并点击，即可看到公式、上游与下游依赖。
其中全部为虚构的演示数据。

## 接入真实 Prophet 工作区

```bash
# 1. 可选：确认工具能看到数据库
python -m prophet_vault schema \
  --isql "C:/Prophet/ProphetServer/ProphetSuite/Firebird_3_0/isql.exe" \
  --prw  "D:/models/PROPHET.PRW"

# 2. 生成快照（较重的一步：一万五千变量约需数分钟）
python -m prophet_vault snapshot \
  --isql "C:/Prophet/.../isql.exe" --prw "D:/models/PROPHET.PRW" --label 2026-08

# 3. 渲染
python -m prophet_vault build-vault --snapshot output/snapshots/2026-08 --vault my_vault
python -m prophet_vault graph       --snapshot output/snapshots/2026-08 -o graph.html

# 4. 下个月：再取快照、对比、把增量应用到已有知识库
python -m prophet_vault snapshot     --prw "D:/models/PROPHET.PRW" --label 2026-09
python -m prophet_vault diff         --old output/snapshots/2026-08 --new output/snapshots/2026-09
python -m prophet_vault update-vault --diff output/diffs/latest_diff.json \
                                     --vault my_vault --snapshot output/snapshots/2026-09
```

也可以改用环境变量：`PROPHET_ISQL_PATH`、`PROPHET_PRW_PATH`、`PROPHET_ISQL_USER`、
`PROPHET_ISQL_PASS`；`PROPHET_WORKSPACE_DIR` 供 `extract-rci` 使用，并让 `snapshot`
从 `VAR_LIST.RCI` 补充更长的变量描述；`PROPHET_OUTPUT_DIR`、`PROPHET_VAULT_DIR`
分别作为 `--out`、`--vault` 的默认值。

工具对模型**只读**：不写 `.PRW`、不启动 Prophet、不需要 Prophet 许可——
`isql.exe` 只是安装包里自带的 Firebird 客户端。

## 一个页面长什么样

`vault/Variables/Conventional/A/AGG_004.md`（演示模型）：

```markdown
---
name: AGG_004
description: "Aggregated result 4 (redefined for the new reporting basis)"
datatype: 0
num_dimensions: 0
is_array: 0
library: Conventional
tags: [variable]
version_history:
  - date: "2026-03-01"
    change: "DESCRIPTION_CHANGED"
---

# AGG_004

> Aggregated result 4 (redefined for the new reporting basis)

## Definition        ← Prophet 公式原文，代码块保留缩进
## Indicators        ← 该变量受哪些 Indicator 条件控制
## References        ← 它引用了谁（[[wikilink]]，可点击）
## Referenced by     ← 谁引用了它
## Dependency graph  ← Mermaid 有向图
```

## 工作原理

```
   Prophet 工作区
   ┌───────────────────────────┐
   │ PROPHET.PRW (Firebird)    │──► isql.exe ──► 定宽列 / BLOB 解析器
   │ VAR_LIST.RCI (二进制)     │──► 二进制扫描 ──► 变量描述
   └───────────────────────────┘
                 │
                 ▼
        snapshot/<label>/  ──►  variables.csv, formulas.csv, indicators.csv,
        （纯 CSV + JSON）        references.csv, formula_hashes.csv, metadata.json
                 │
      ┌──────────┴───────────┐
      ▼                      ▼
  diff/<old>-vs-<new>.json   build-vault / graph
      │                      │
      ▼                      ▼
  update-vault          Obsidian 知识库、单文件 HTML
```

**快照**是纯 CSV，因此可以纳入 git、手工 diff、用 pandas 读取、或直接交给审计。
**变更报告**是纯 JSON 加一份 Markdown，于是模型改动也能像代码改动一样走评审。

## 设计取舍

* **用 `isql.exe` 而不是数据库驱动。** `.PRW` 是 Firebird *嵌入式* 数据库，不同 Prophet
  版本的内核格式不同；Python 驱动只绑定一种客户端库，换版本就失效，而安装包内的
  `isql.exe` 永远匹配。详见 [docs/prw-extraction.md](docs/prw-extraction.md)。
* **引用先当“候选词”提取，再与真实变量表取交集。** 这是分词而非 Prophet 语法解析，
  也无需更复杂：未知标识符与未收录关键字都会在交集里自然消失。
* **公式用归一化哈希比较，而不是文本。** 重新缩进不算模型变更，多一项才算。
* **页面只整体重渲染，绝不做字符串补丁。** 围绕 `##` 标题的字符串手术，在有人手工
  编辑过一次页面之后就会失效。
* **图谱只渲染焦点子图。** 节点上万时全量布局必然卡顿；一个节点加 N 层邻居是即时的。
  详见 [docs/dependency-graph.md](docs/dependency-graph.md)。
* **目录先按 Library 再按首字母分层。** 一个目录塞 15,000 个文件，Obsidian、资源管理器和
  git 都会难受。

## 仓库结构

```
prophet_vault/            # 可导入的包，仅用标准库
├── cli.py                #   argparse 命令行（python -m prophet_vault）
├── config.py             #   路径与凭据，可用环境变量覆盖
├── _io.py                #   UTF-8 / LF 稳定写入（保证产物可复现）
├── rci.py                #   VAR_LIST.RCI 二进制解析
├── isql.py               #   isql 子进程 + 定宽列 / BLOB 输出解析
├── extract.py            #   PRW 查询 → 模型数据、引用推导
├── formulas.py           #   分词、保留字、公式哈希
├── snapshot.py           #   快照 CSV 契约
├── diff.py               #   快照对比与报告
├── vault.py              #   Obsidian 渲染与增量更新
├── graph.py              #   HTML 依赖图谱
├── demo.py               #   合成模型生成器
└── templates/dependency_graph.html
tests/                    # 149 个测试，无需网络、无需安装 Prophet
examples/                 # 已生成的演示快照、变更报告与图谱
docs/                     # 设计与参考文档（英文）
```

## 测试

```bash
pip install -e ".[dev]"
pytest
```

测试完全离线，从不接触 Prophet 安装：模型数据来自合成生成器，`isql` 解析器则用
录制下来的输出形态做验证。

## 局限与边界

* 面向 **Prophet**（FIS）。表名列名并非公开 API；若你的版本不同，先跑
  `python -m prophet_vault schema` 看实际表名，再调整
  [`prophet_vault/extract.py`](prophet_vault/extract.py) 里的 SQL 常量。其余流水线
  （快照、对比、知识库、图谱）与模型平台无关。
* 解析器是**启发式**的，不是格式规范。`VAR_LIST.RCI` 的记录没有长度字段，`isql` 的
  定宽输出遇到超宽值会折行；两者都已写入文档、都做了容错，也都不是逐字节精确。
* **Windows 优先**：Prophet 服务端在 Windows 上，代码直接调用 `isql.exe`；
  其余部分与平台无关。
* 不是计算引擎。它记录并比较模型，不运行模型。

## 文档

| 文档 | 内容 |
|---|---|
| [architecture.md](docs/architecture.md) | 数据流、模块边界、扩展点 |
| [data-model.md](docs/data-model.md) | 快照 CSV/JSON 契约 |
| [prw-extraction.md](docs/prw-extraction.md) | 通过 `isql` 读取 Firebird `.PRW` |
| [rci-format.md](docs/rci-format.md) | `VAR_LIST.RCI` 二进制布局与解析策略 |
| [dependency-graph.md](docs/dependency-graph.md) | 图谱数据契约与渲染取舍 |
| [obsidian-vault.md](docs/obsidian-vault.md) | 知识库结构、frontmatter、Dataview、Mermaid |
| [monthly-update.md](docs/monthly-update.md) | 快照／对比／更新的月度作业流程 |
| [troubleshooting.md](docs/troubleshooting.md) | 登录失败、编码、截断、链接失效 |

## 参与贡献

欢迎 Issue 与 PR——尤其欢迎：你手上 Prophet 版本的解析修正，以及其他建模平台的适配器
（适配器只需产出快照契约）。详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 致谢与工具链

本仓库的代码最初源自一个内部精算工具，由 **Claude Code**（VS Code 中的 AI 编程助手）实现：基于 `isql` 的 PRW 提取、`VAR_LIST.RCI` 二进制格式逆向、Vault 生成器与 HTML 依赖图谱，都是它在真实 Prophet 工作区上逐轮迭代写出来的。

而这个公开仓库的整理工作——包结构重构、剥离模型专属代码、离线测试套件、合成演示数据生成器与文档——由 **DeepSeek Harness** 完成。

两者都是由精算人员驱动的 AI 编程工具：需求、评审与验收由人负责，设计取舍与理由记录在 [`docs/`](docs/) 中。

角色分工见 [CONTRIBUTORS.md](CONTRIBUTORS.md)。

## 许可

MIT，见 [LICENSE](LICENSE)。

Prophet 为其权利人商标。本项目为独立、非官方项目，与厂商无隶属或背书关系；
它只读取你本机已有的文件，不附带任何厂商代码。
