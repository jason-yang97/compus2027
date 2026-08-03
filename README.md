# 秋招权威仓库

具身智能方向秋招准备与投递追踪的权威仓库。数据以 Markdown 为主，配合命令行工具实现投递状态管理，并通过半自动搜集 + 人工审核的方式获取招聘信息。

## 快速上手

```bash
# 创建公司记录（交互式填写信息）
python3 tools/recruit.py add 宇树科技

# 查看所有投递记录
python3 tools/recruit.py list

# 按状态/城市/意向度过滤
python3 tools/recruit.py list --status 面试 --city 杭州 --priority 高

# 更新投递状态（自动追加时间线）
python3 tools/recruit.py status 宇树科技 笔试

# 查看单个公司完整记录
python3 tools/recruit.py show 宇树科技

# 全文搜索
python3 tools/recruit.py search SLAM

# 阶段统计
python3 tools/recruit.py stats
```

## 目录结构

```
recruit/
├── companies/            # 投递追踪：每家公司一个 Markdown 文件
├── inbox/                # 半自动搜集的待审核候选信息
tools/
├── recruit.py            # CLI 主工具（零第三方依赖）
└── scraper/              # 信息搜集脚本
    ├── sources.json      # 信息源配置
    └── scrape_github.py  # GitHub 汇总源抓取
docs/
└── DESIGN.md             # 数据模型与规范设计
```

## 工作流

### 1. 搜集信息（半自动）

```bash
# 从配置的 GitHub 汇总源抓取候选招聘信息
python3 tools/scraper/scrape_github.py

# 审核 recruit/inbox/ 下生成的候选文件，筛选与具身智能方向相关的岗位
```

### 2. 录入投递

审核通过的公司用 `add` 命令交互式录入；也可以直接复制 `recruit/companies/_template.md` 手动创建。

### 3. 状态追踪

状态机：`待投递 → 已投递 → 笔试 → 面试 → Offer | 已拒`。状态变更统一通过 `status` 命令完成，自动在时间线记录。

### 4. 复盘

面试后在对应公司文件的「面试记录」章节记录问题与复盘，形成面经知识库。

## 状态说明

| 状态 | 含义 |
|---|---|
| 待投递 | 有意向但未投递 |
| 已投递 | 简历已提交 |
| 笔试 | 笔试环节 |
| 面试 | 面试环节（一面/二面/HR 面） |
| Offer | 已拿到 offer（终态） |
| 已拒 | 流程终止/被拒（终态） |

## 开发

- 数据模型与命令规范见 [docs/DESIGN.md](docs/DESIGN.md)
- 工具仅依赖 Python 标准库，Python 3.8+
- 半自动搜集的抓取脚本容错设计：网络异常、仓库格式变化均不影响已入库数据
