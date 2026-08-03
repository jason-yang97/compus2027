# 秋招仓库设计文档

本文档定义秋招仓库的数据模型、状态机与工具规范，是仓库的权威设计参考。

## 1. 目录结构

```
recruit/
├── companies/            # 投递追踪核心：每家公司一个 Markdown 文件
│   └── _template.md      # 公司记录模板
├── data/
│   └── companies.json    # 企业招聘入口库（系统分类，飞书适配器数据源）
└── inbox/                # 半自动搜集产出的待审核候选信息
tools/
├── recruit.py            # CLI 主工具（Python 标准库，零第三方依赖）
├── .venv/                # 虚拟环境（playwright，已 gitignore）
└── scraper/
    ├── sources.json      # 信息源配置（GitHub 汇总源）
    ├── scrape_github.py  # GitHub 汇总源抓取
    ├── build_company_db.py  # 构建企业招聘入口库
    └── scrape_feishu.py  # 飞书招聘系统岗位批量抓取
docs/
└── DESIGN.md             # 本文档
```

## 2. 数据模型：公司记录文件

路径：`recruit/companies/<公司名>.md`，文件名与 frontmatter 的 `company` 字段一致。

### 2.1 frontmatter 字段

| 字段 | 必填 | 取值 | 说明 |
|---|---|---|---|
| `company` | 是 | 任意字符串 | 公司名，须与文件名一致 |
| `status` | 是 | 见状态机 | 当前投递状态 |
| `city` | 否 | 任意字符串 | 目标工作城市 |
| `priority` | 否 | 高/中/低 | 意向度 |
| `apply_date` | 否 | YYYY-MM-DD | 投递日期 |
| `deadline` | 否 | YYYY-MM-DD | 投递截止时间 |
| `source` | 否 | 官网/牛客/内推/其他 | 信息来源 |
| `tags` | 否 | 逗号分隔数组 | 自定义标签，如 [具身智能, 算法] |

### 2.2 状态机

```
待投递 → 已投递 → 笔试 → 面试 → Offer | 已拒
```

- `已拒`、`Offer` 为终态
- 状态变更通过 `recruit.py status` 完成，自动在「时间线」追加记录

### 2.3 正文结构

- `## 岗位`：岗位列表，checkbox 标记投递状态，可带投递链接
- `## 时间线`：`- YYYY-MM-DD 事件` 格式，状态变更自动追加
- `## 笔试`：日期、内容、结果
- `## 面试记录`：每轮一个三级标题，记录问题与复盘
- `## 备注`：自由内容

## 3. CLI 命令规范（tools/recruit.py）

| 命令 | 说明 |
|---|---|
| `recruit.py add <公司名>` | 交互式创建公司记录 |
| `recruit.py list [--status] [--city] [--priority]` | 过滤列表 |
| `recruit.py status <公司名> <新状态>` | 更新状态并追加时间线 |
| `recruit.py show <公司名>` | 展示完整记录 |
| `recruit.py search <关键词>` | 全文搜索 |
| `recruit.py stats` | 阶段统计 |

## 4. 半自动搜集流程

1. `sources.json` 声明 GitHub 汇总仓库等信息源（默认：Campus2026 互联网校招汇总、Xbotics 具身智能社区内推清单、具身智能招贤榜）
2. `scrape_github.py` 抓取 README（支持表格与链接行两种格式），按方向关键词与关注公司名单过滤，产出候选
3. 候选写入 `recruit/inbox/<日期>_<信息源>_candidates.md`，标注命中原因与已入库状态
4. 人工审核后用 `recruit.py add` 入库，审核完毕删除候选文件

## 4.1 企业招聘入口库（companies.json）

- 由 `build_company_db.py` 从候选文件与 Campus2026 汇总源自动提取企业，按链接域名分类
- 系统分类：`feishu`（*.jobs.feishu.cn）/ `moka`（*.mokahr.com）/ `zhiye`（*.zhiye.com）/ `beisen`（talent.*.com）/ `website`（自研官网）/ `unknown`（待补充）
- 同名企业多条记录时保留结构化价值更高的链接（飞书 > Moka/智联/北森 > 官网）
- 飞书系企业可手动增补（`{"name": ..., "recruit_system": "feishu", "org": ...}`）

## 4.2 飞书招聘适配器（scrape_feishu.py）

- 原理：Playwright 驱动系统 Chrome 获取浏览器指纹（curl 直连被字节风控拒绝），页面同源调用岗位接口
  `POST /api/v1/search/job/posts?portal_type=6&portal_entrance=1`（无签名可用）
- 数据：岗位标题/发布时间/招聘类型/类别，按方向关键词过滤后输出到 inbox
- 依赖：`tools/.venv`（playwright）+ 系统 Chrome；企业清单来自 companies.json 中 `feishu` 系
- 当前状态：8 家飞书系企业（智元/小鹏/星动纪元/自变量/蔚来/上海AI实验室/银河通用/松灵），
  接口返回以社招岗位为主，校招岗位开放后同接口可获取

## 5. 扩展预留

- `recruit/interviews/`：面试复盘知识库（后续）
- `recruit/notes/`：八股/项目笔记（后续）
- scraper 多源：牛客源、Moka/智联/北森适配器（companies.json 已分类，按需实现）
