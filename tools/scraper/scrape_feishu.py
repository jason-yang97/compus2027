#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""飞书招聘系统适配器：批量抓取飞书系企业校招岗位。

原理（已探测验证）：
- 用 Playwright 驱动系统 Chrome 打开企业招聘页，获得真实浏览器指纹与 cookie
  （字节系风控会拒绝无浏览器指纹的 curl 直连，返回 HTTP 400）
- 在页面上下文同源调用岗位接口（无需逆向 _signature 签名）：
    POST /api/v1/search/job/posts?keyword=&limit=100&offset=0&portal_type=6&portal_entrance=1
- 解析 JSON -> 按方向关键词过滤 -> 输出候选到 recruit/inbox/

用法：
  tools/.venv/bin/python tools/scraper/scrape_feishu.py
  tools/.venv/bin/python tools/scraper/scrape_feishu.py --orgs agirobot,xiaopeng
  tools/.venv/bin/python tools/scraper/scrape_feishu.py --limit 50

依赖：tools/.venv（playwright），系统 Chrome（channel=chrome）。
"""

import argparse
import json
import os
import re
import sys
from datetime import date, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
COMPANIES_JSON = os.path.join(ROOT, 'recruit', 'data', 'companies.json')
INBOX_DIR = os.path.join(ROOT, 'recruit', 'inbox')
SOURCES_JSON = os.path.join(ROOT, 'tools', 'scraper', 'sources.json')
COMPANIES_DIR = os.path.join(ROOT, 'recruit', 'companies')

API_PATH = ('/api/v1/search/job/posts?keyword=&limit={limit}&offset=0'
            '&job_category_id_list=&tag_id_list=&location_code_list='
            '&subject_id_list=&recruitment_id_list=&portal_type=6'
            '&job_function_id_list=&storefront_id_list=&portal_entrance=1')


def load_companies():
    with open(COMPANIES_JSON, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return [c for c in data['companies'] if c['recruit_system'] == 'feishu' and c['org']]


def load_keywords():
    with open(SOURCES_JSON, 'r', encoding='utf-8') as f:
        config = json.load(f)
    return config.get('direction_keywords', []), config.get('watch_companies', [])


def load_existing():
    if not os.path.isdir(COMPANIES_DIR):
        return set()
    return {f[:-3] for f in os.listdir(COMPANIES_DIR)
            if f.endswith('.md') and not f.startswith('_')}


def match(text, keywords, watch):
    """按关键词与关注公司过滤，返回 (是否命中, 命中原因)。"""
    low = text.lower()
    for kw in keywords:
        if kw.lower() in low:
            return True, f'关键词「{kw}」'
    for c in watch:
        if c in text:
            return True, f'关注公司「{c}」'
    return False, ''


def fetch_positions(page, org, limit):
    """在页面上下文调用飞书岗位接口，返回岗位列表。"""
    js = f"""async () => {{
        const r = await fetch('{API_PATH.format(limit=limit)}', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: '{{}}'
        }});
        const j = await r.json();
        return j.data ? j.data : null;
    }}"""
    return page.evaluate(js)


def fmt_time(ms):
    """毫秒时间戳 -> YYYY-MM-DD。"""
    try:
        return datetime.fromtimestamp(int(ms) / 1000).strftime('%Y-%m-%d')
    except (ValueError, TypeError):
        return ''


def fmt_recruit_type(p):
    """招聘类型：校招/社招/实习 + 全职/兼职。"""
    rt = p.get('recruit_type') or {}
    parent = rt.get('parent') or {}
    name = rt.get('name') or ''
    parent_name = parent.get('name') or ''
    return f'{parent_name}/{name}' if parent_name and name else (parent_name or name)


def scrape_org(page, company, limit, keywords, watch):
    """抓取单个企业岗位，返回命中条目列表与统计。"""
    org = company['org']
    name = company['name']
    url = f'https://{org}.jobs.feishu.cn/'
    try:
        page.goto(url, timeout=30000, wait_until='domcontentloaded')
        page.wait_for_timeout(4000)  # 等待 cookie/指纹与页面就绪
        data = fetch_positions(page, org, limit)
    except Exception as e:
        print(f'  [跳过] {name}({org}): {type(e).__name__}')
        return [], None
    if not data or not data.get('job_post_list'):
        print(f'  {name}({org}): 无岗位（count={data.get("count") if data else "?"}）')
        return [], data.get('count') if data else 0

    posts = data['job_post_list']
    total = data.get('count', len(posts))
    hits = []
    for p in posts:
        title = p.get('title') or ''
        desc = (p.get('description') or '')[:300]
        # 仅匹配岗位标题与描述，避免公司名误命中
        matched, reason = match(f'{title} {desc}', keywords, watch)
        if matched:
            hits.append((name, org, title, p.get('id', ''),
                         fmt_time(p.get('publish_time')),
                         fmt_recruit_type(p),
                         (p.get('job_category') or {}).get('name', ''),
                         reason))
    print(f'  {name}({org}): 共 {total} 岗位，命中 {len(hits)}')
    return hits, total


def render(hits, stats):
    today = date.today().isoformat()
    lines = [
        f'# {today} 飞书招聘岗位候选（自动抓取，需人工审核）',
        '',
        f'> 来源：飞书招聘系统（{len(stats)} 家企业），抓取 {sum(stats.values())} 个岗位，'
        f'命中 {len(hits)} 条',
        f'> 生成时间：{today}，命中规则：方向关键词 / 关注公司名单',
        '',
        '## 候选列表',
        '',
        '| 公司 | 岗位/链接 | 发布日期 | 类型 | 类别 | 命中 | 状态 |',
        '|---|---|---|---|---|---|---|',
    ]
    for name, org, title, pid, pub, rtype, cat, reason in hits:
        link = f'https://{org}.jobs.feishu.cn/'
        status = '已入库' if name in existing_names else '待审核'
        lines.append(
            f'| {name} | [{title}]({link}) | {pub} | {rtype} | {cat} | {reason} | {status} |')
    lines += [
        '',
        '## 审核指引',
        '',
        '1. 确认岗位与方向匹配后，用 `python3 tools/recruit.py add <公司名>` 建立公司记录',
        '2. 岗位链接为招聘首页，详情可在页面内搜索岗位标题',
        '3. 审核完毕后删除本文件',
        '',
    ]
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description='飞书招聘系统岗位批量抓取')
    parser.add_argument('--companies', default=COMPANIES_JSON, help='企业库路径')
    parser.add_argument('--limit', type=int, default=100, help='每企业抓取岗位数上限')
    parser.add_argument('--orgs', default='', help='仅抓取指定 org（逗号分隔）')
    parser.add_argument('--headful', action='store_true', help='显示浏览器窗口（调试用）')
    args = parser.parse_args()

    companies = load_companies()
    if args.orgs:
        org_set = set(args.orgs.split(','))
        companies = [c for c in companies if c['org'] in org_set]
    if not companies:
        sys.exit('错误：企业库中没有 feishu 系企业，请先运行 build_company_db.py')

    keywords, watch = load_keywords()
    global existing_names
    existing_names = load_existing()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit('缺少 playwright：请执行 tools/.venv/bin/pip install playwright')

    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=not args.headful)
        page = browser.new_page(viewport={'width': 1280, 'height': 800})
        all_hits = []
        stats = {}
        print(f'开始抓取 {len(companies)} 家飞书系企业：')
        for c in companies:
            hits, total = scrape_org(page, c, args.limit, keywords, watch)
            all_hits.extend(hits)
            stats[c['name']] = total if total is not None else 0
        browser.close()

    if not all_hits:
        print('所有企业均无方向相关岗位命中。')
        return
    out_file = os.path.join(INBOX_DIR, f'{date.today().isoformat()}_飞书招聘_candidates.md')
    with open(out_file, 'w', encoding='utf-8') as f:
        f.write(render(all_hits, stats))
    print(f'\n完成。命中 {len(all_hits)} 条，已写入 {out_file}')


if __name__ == '__main__':
    main()
