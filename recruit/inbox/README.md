# inbox — 待审核候选信息

本目录存放半自动搜集脚本产出的待审核招聘信息候选文件。

命名规范：`<日期>_candidates.md`，例如 `2026-08-03_candidates.md`。

**审核流程**：

1. 运行 `python3 tools/scraper/scrape_github.py` 生成候选文件
2. 人工审核文件内容，筛选与具身智能方向相关的岗位
3. 对通过审核的公司执行 `python3 tools/recruit.py add <公司名>` 正式入库
4. 审核完毕后删除或归档本目录中的候选文件
