#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""半自动信息搜集：从 GitHub 秋招汇总仓库抓取招聘信息候选。

流程：抓取 README → 解析 Markdown 表格 → 按方向关键词与关注公司过滤 →
输出候选到 recruit/inbox/<日期>_candidates.md，供人工审核后入库。

用法：
  python3 tools/scraper/scrape_github.py [--config sources.json路径]
  python3 tools/scraper/scrape_github.py --list-sources  仅列出信息源

容错设计：网络异常、仓库格式变化、分支名变化均不阻断执行，失败源在报告中标注。
零第三方依赖，仅使用 Python 标准库。
"""

import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_PATH = os.path.join(ROOT, 'tools', 'scraper', 'sources.json')
INBOX_DIR = os.path.join(ROOT, 'recruit', 'inbox')
COMPANIES_DIR = os.path.join(ROOT, 'recruit', 'companies')

# Markdown 表格行：| 公司 | 状态&&链接 | 更新日期 | 地点 | 备注 |
ROW_RE = re.compile(
    r'^\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|')
LINK_RE = re.compile(r'\[([^\]]+)\]\(([^)\s]+)\)')
# 链接行：[标题](链接) 与日期标记行 **2026.8.1**
LINK_LINE_RE = re.compile(r'^\[(.+?)\]\((https?://[^)\s]+)\)\s*$')
DATE_HEAD_RE = re.compile(r'^\*\*\[?(\d{4}[./-]\d{1,2}[./-]\d{1,2})\]?\*\*')
SEP_RE = re.compile(r'\s*-\s*')
# 论文/资料仓库链接（Awesome-* 系列等），非招聘信息，排除
RESOURCE_LINK_RE = re.compile(r'^Awesome-', re.IGNORECASE)


def load_config(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


# raw.githubusercontent.com 在部分网络环境不可达，直连失败后改走镜像并记忆
_MIRRORS = ['https://gh-proxy.com/']
_direct_ok = True


def fetch_raw(repo, branch, readme):
    """抓取 GitHub raw README，master/main 分支自动回退，失败返回 None。

    直连 raw.githubusercontent.com 失败时自动回退到镜像，并记住直连不可达，
    后续源直接走镜像。
    """
    global _direct_ok
    branches = []
    for b in (branch, 'main', 'master'):
        if b and b not in branches:
            branches.append(b)
    bases = [''] + _MIRRORS if _direct_ok else list(_MIRRORS)
    direct_failed = _direct_ok
    for base in bases:
        for b in branches:
            url = f'{base}https://raw.githubusercontent.com/{repo}/{b}/{readme}'
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'recruit-scraper/1.0'})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    if not base:
                        direct_failed = False
                    return resp.read().decode('utf-8', errors='replace')
            except Exception:
                continue
    if direct_failed:
        _direct_ok = False
    return None


def parse_entries(content):
    """解析 README 为统一条目列表。

    支持两种格式：
    - 表格行：| 公司 | 链接 | 日期 | 地点 | 备注 |
    - 链接行：**[日期]** 后跟 [标题](链接)
    返回 [(公司, 标题, 链接, 日期, 备注, 类型)]。
    """
    entries = []
    cur_date = ''
    for line in content.split('\n'):
        line = line.strip()
        m = DATE_HEAD_RE.match(line)
        if m:
            cur_date = m.group(1).replace('.', '-').replace('/', '-')
            continue
        m = ROW_RE.match(line)
        if m:
            cells = tuple(c.strip() for c in m.groups()[:5])
            if not re.fullmatch(r'[-:\s]+', cells[0]):
                company, status_link, update, location, note = cells
                entries.append((company, company, extract_link(status_link),
                                update, f'{location} {note}'.strip(), 'table'))
            continue
        m = LINK_LINE_RE.match(line)
        if m:
            title, link = m.group(1), m.group(2)
            # 排除论文/资料仓库等非招聘链接
            if RESOURCE_LINK_RE.match(title):
                continue
            parts = SEP_RE.split(title)
            company = parts[0].strip()
            note = ' / '.join(p.strip() for p in parts[1:] if p.strip())
            entries.append((company, title, link, cur_date, note, 'link'))
    return entries


def extract_link(text):
    m = LINK_RE.search(text)
    if m:
        return m.group(2)
    return text if text.startswith('http') else ''


def match_row(row, keywords, watch_companies):
    """按关键词与关注公司过滤，返回 (是否命中, 命中原因)。

    row 为 parse_entries 的统一条目：(公司, 标题, 链接, 日期, 备注, 类型)。
    """
    company, title, link, _, note, _ = row
    haystack = f'{company} {title} {note} {link}'.lower()
    for kw in keywords:
        if kw.lower() in haystack:
            return True, f'关键词「{kw}」'
    for c in watch_companies:
        if c in company:
            return True, f'关注公司「{c}」'
    return False, ''


def load_existing_companies():
    """返回已入库公司名集合（排除模板文件），用于去重。"""
    if not os.path.isdir(COMPANIES_DIR):
        return set()
    return {f[:-3] for f in os.listdir(COMPANIES_DIR)
            if f.endswith('.md') and not f.startswith('_')}


def render_candidates(src, rows, existing):
    today = date.today().isoformat()
    lines = [
        f'# {today} 招聘信息候选（自动生成，需人工审核）',
        '',
        f'> 来源：{src["name"]} — {src["homepage"]}',
        f'> 生成时间：{today}，命中规则：方向关键词 / 关注公司名单',
        '',
        '## 候选列表',
        '',
        '| 公司 | 岗位/链接 | 更新日期 | 备注 | 命中 | 状态 |',
        '|---|---|---|---|---|---|',
    ]
    for row in rows:
        company, title, link, update, note, kind, reason = row
        status = '已入库' if company in existing else '待审核'
        if kind == 'table':
            title_cell = f'[{title}]({link})' if link else '-'
            note_cell = note
        else:
            title_cell = f'[{title}]({link})'
            note_cell = note or '—'
        lines.append(
            f'| {company} | {title_cell} | {update} | {note_cell} | {reason} | {status} |')
    lines += [
        '',
        '## 审核指引',
        '',
        '1. 优先关注备注中标注「校招」「实习」的条目；博后/社招/科研岗可按需忽略',
        '2. 对「待审核」且确认投递的公司执行：`python3 tools/recruit.py add <公司名>`',
        '3. 审核完毕后删除本文件',
        '',
    ]
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description='GitHub 汇总源招聘信息抓取')
    parser.add_argument('--config', default=CONFIG_PATH, help='信息源配置路径')
    parser.add_argument('--list-sources', action='store_true', help='仅列出信息源')
    args = parser.parse_args()

    config = load_config(args.config)
    sources = config.get('github_sources', [])
    keywords = config.get('direction_keywords', [])
    watch = config.get('watch_companies', [])

    if args.list_sources:
        for s in sources:
            print(f'{s["name"]:20s} {s["homepage"]}')
        return

    if not sources:
        sys.exit('错误：未配置任何 github_sources')
    if not keywords and not watch:
        sys.exit('错误：direction_keywords 与 watch_companies 均为空，无法过滤')

    existing = load_existing_companies()
    total_rows = 0
    for src in sources:
        print(f'抓取 {src["name"]}（{src["repo"]}）...', end=' ')
        sys.stdout.flush()
        content = fetch_raw(src['repo'], src.get('branch', ''), src.get('readme', 'README.md'))
        if content is None:
            print('失败（网络或分支问题），已跳过')
            continue
        rows = parse_entries(content)
        hits = []
        for row in rows:
            matched, reason = match_row(row, keywords, watch)
            if matched:
                hits.append((*row, reason))
        total_rows += len(rows)
        if not hits:
            print(f'解析到 {len(rows)} 行，无方向相关命中')
            continue

        # 已入库公司置于列表尾部，便于优先审核
        hits.sort(key=lambda r: r[0] in existing)
        out_file = os.path.join(
            INBOX_DIR, f'{date.today().isoformat()}_{src["name"]}_candidates.md')
        with open(out_file, 'w', encoding='utf-8') as f:
            f.write(render_candidates(src, hits, existing))
        print(f'命中 {len(hits)} 条，已写入 {out_file}')

    print(f'完成。共解析 {total_rows} 行招聘信息，详情见 recruit/inbox/ 目录。')


if __name__ == '__main__':
    main()
