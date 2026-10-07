#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全量导出网页数据源（不做方向关键词过滤），供 tools/build_web.py 构建。

默认抓取三类源，输出统一行格式（字段名与飞书表对齐）：
  1. 飞书多维表格汇总表（朱迪学姐27届）          --with-feishu-base
  2. GitHub 秋招汇总仓库（Campus2026 等 3 个）    --with-github
  3. 飞书招聘系统企业岗位（companies.json 8 家）  --with-jobs

用法：
  tools/.venv/Scripts/python tools/scraper/fetch_feishu_all.py
  tools/.venv/Scripts/python tools/scraper/fetch_feishu_all.py --no-jobs
"""

import argparse
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scrape_feishu_base import (  # noqa: E402
    fetch_clientvars, fetch_records, load_sources, parse_url,
)
from scrape_feishu import fmt_time, fmt_recruit_type  # noqa: E402
from scrape_github import load_config, parse_entries, fetch_raw  # noqa: E402

API_QUERY = ('/api/v1/search/job/posts?keyword=&limit={limit}&offset=0'
             '&job_category_id_list=&tag_id_list=&location_code_list='
             '&subject_id_list=&recruitment_id_list=&portal_type=6'
             '&job_function_id_list=&storefront_id_list=&portal_entrance=1')


def fetch_positions_csrf(page, limit):
    """带 CSRF token 的岗位接口调用（飞书 ATS 已要求 x-csrf-token）。"""
    query = API_QUERY.replace('{limit}', "' + limit + '")
    js = """async (limit) => {
      const t = await fetch('/api/v1/csrf/token', {method: 'POST',
        headers: {'Content-Type': 'application/json'}, body: '{}'});
      const tj = await t.json();
      const token = (tj && tj.data && tj.data.token) || '';
      const r = await fetch('""" + query + """', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'x-csrf-token': token},
        body: JSON.stringify({keyword: '', limit: limit, offset: 0,
          job_category_id_list: [], tag_id_list: [], location_code_list: [],
          subject_id_list: [], recruitment_id_list: []})
      });
      const j = await r.json();
      return j.data ? j.data : {error: 'http ' + r.status};
    }"""
    return page.evaluate(js, limit)

OUT_DEFAULT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'recruit', 'data', 'feishu_base_all.json')
GITHUB_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sources.json')
COMPANIES_JSON = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'recruit', 'data', 'companies.json')


def github_sources():
    """GitHub 汇总源 -> [{name,url,rows}]。"""
    sources = []
    for src in load_config(GITHUB_CONFIG).get('github_sources', []):
        print(f'抓取 GitHub 源 {src["name"]}（{src["repo"]}）...', flush=True)
        content = fetch_raw(src['repo'], src.get('branch', ''), src.get('readme', 'README.md'))
        if content is None:
            print('  [跳过] 抓取失败')
            continue
        entries = parse_entries(content)
        rows = []
        for company, title, link, update, note, _kind in entries:
            rows.append({
                '公司': company[:80],
                '招聘岗位': title[:200],
                '工作地点': '',
                '招聘届次': '',
                '截止时间': '',
                '简历投递链接': link if link.startswith('http') else '',
                '是否笔试': '',
                '备注': note[:200],
                '学历要求': '', '专业要求': '', '企业类型': '', '行业类别': '',
                '批次': '', '开始时间': '', '更新时间': update,
            })
        print(f'  解析 {len(rows)} 条')
        sources.append({'name': f'GitHub·{src["name"]}', 'url': src.get('homepage', ''), 'rows': rows})
    return sources


# 飞书招聘系统企业的基础属性（企业类型, 行业类别）——表中仅此 8 家，直接标注
FEISHU_ORG_META = {
    'aicarrier': ('事业单位', '人工智能'),
    'xiaopeng': ('民企', '汽车制造/维修/零配件'),
    'k0fqxcszc9': ('民企', '机器人/智能制造'),
    'x2-robot': ('民企', '机器人/智能制造'),
    'nio': ('民企', '汽车制造/维修/零配件'),
    'agirobot': ('民企', '机器人/智能制造'),
    'owm6ymi5v9b': ('民企', '机器人/智能制造'),
    'mammotion': ('民企', '机器人/智能制造'),
}


def feishu_job_rows(page, limit):
    """飞书招聘系统企业全量岗位 -> 统一行格式。"""
    with open(COMPANIES_JSON, encoding='utf-8') as f:
        companies = [c for c in json.load(f)['companies']
                     if c.get('recruit_system') == 'feishu' and c.get('org')]
    rows = []
    today = date.today().isoformat()
    for c in companies:
        org, name = c['org'], c['name']
        ent, ind = FEISHU_ORG_META.get(org, ('民企', ''))
        try:
            page.goto(f'https://{org}.jobs.feishu.cn/', timeout=30000, wait_until='domcontentloaded')
            page.wait_for_timeout(4000)
            data = fetch_positions_csrf(page, limit)
        except Exception as e:
            print(f'  [跳过] {name}({org}): {type(e).__name__}', flush=True)
            continue
        posts = (data or {}).get('job_post_list') or []
        print(f'  {name}({org}): {len(posts)} 岗位', flush=True)
        for p in posts:
            rtype = fmt_recruit_type(p)
            cat = (p.get('job_category') or {}).get('name', '')
            city = ' / '.join(
                (ct or {}).get('name', '') for ct in (p.get('city_list') or []) if (ct or {}).get('name'))
            # 批次按岗位类型归类：实习 > 校招 > 社招
            rt_all = f'{rtype} {cat}'
            batch = '实习' if '实习' in rt_all else ('校招' if '校招' in rt_all else ('社招' if '社招' in rt_all else ''))
            rows.append({
                '公司': name,
                '招聘岗位': (p.get('title') or '')[:200],
                '工作地点': city,
                '招聘届次': '',
                '截止时间': '尽快投递',
                '简历投递链接': f'https://{org}.jobs.feishu.cn/',
                '是否笔试': '',
                '备注': ' / '.join(x for x in (rtype, cat) if x)[:200],
                '学历要求': '', '专业要求': '', '企业类型': ent, '行业类别': ind,
                '批次': batch,
                '开始时间': today,
                '更新时间': fmt_time(p.get('publish_time')),
            })
    return rows


def humanize(value, option_map):
    """把值中的选项 ID 替换为选项文本；其余文本原样返回。"""
    if not value:
        return ''
    tokens = value.split()
    if tokens and all(t in option_map for t in tokens):
        return ' / '.join(option_map[t] for t in tokens)
    return value


def cell_with_url(full):
    """单元格 [{type,text,link}] -> (文本, 首个链接 URL)。"""
    if not full:
        return '', ''
    v = full.get('value')
    if not isinstance(v, list):
        return (str(v), '') if isinstance(v, (str, int, float)) else ('', '')
    parts, url = [], ''
    for seg in v:
        if isinstance(seg, dict):
            parts.append(seg.get('text') or '')
            if not url:
                link = seg.get('link') or seg.get('url') or seg.get('href') or ''
                if isinstance(link, dict):
                    link = link.get('url') or link.get('link') or ''
                if link and link.startswith('http'):
                    url = link
        else:
            parts.append(str(seg))
    return ' '.join(p for p in parts if p), url


def main():
    parser = argparse.ArgumentParser(description='全量导出网页数据源')
    parser.add_argument('--sources', default='', help='仅跑指定飞书汇总表源名（逗号分隔）')
    parser.add_argument('--out', default=OUT_DEFAULT, help='输出 JSON 路径')
    parser.add_argument('--no-base', action='store_true', help='跳过飞书汇总表')
    parser.add_argument('--no-github', action='store_true', help='跳过 GitHub 汇总源')
    parser.add_argument('--no-jobs', action='store_true', help='跳过飞书招聘系统岗位')
    parser.add_argument('--limit', type=int, default=200, help='飞书招聘每企业岗位数上限')
    args = parser.parse_args()

    result = []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit('缺少 playwright：请执行 tools/.venv/Scripts/pip install playwright')

    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 800})

        if not args.no_base:
            sources = load_sources()
            if args.sources:
                wanted = set(args.sources.split(','))
                sources = [s for s in sources if s['name'] in wanted]
            if not sources:
                print('[跳过] sources.json 未配置 feishu_base_sources')
            for src in sources:
                name = src['name']
                info = parse_url(src['url'])
                print(f'抓取 {name}（{info["app"]}）...', flush=True)
                try:
                    page.goto(src['url'], timeout=60000, wait_until='domcontentloaded')
                    page.wait_for_timeout(12000)
                    field_map, option_map = fetch_clientvars(page, info['app'], info['table'], info['view'])
                    records = fetch_records(page, info['app'], info['table'], info['view'])
                except Exception as e:
                    print(f'  [跳过] {name}: {type(e).__name__}: {e}')
                    continue

                rows = []
                for rec in records.values():
                    row = {}
                    for fid, fname in field_map.items():
                        if fname in row:
                            continue
                        text, url = cell_with_url(rec.get(fid))
                        text = humanize(text, option_map)
                        if '链接' in fname:
                            row[fname] = url or (text if text.startswith('http') else '')
                        else:
                            row[fname] = text
                    rows.append(row)
                print(f'  记录 {len(rows)} 条')
                result.append({'name': name, 'url': src['url'], 'rows': rows})

        if not args.no_jobs:
            print('抓取飞书招聘系统企业岗位...', flush=True)
            result.append({'name': '飞书招聘系统', 'url': '',
                           'rows': feishu_job_rows(page, args.limit)})

        browser.close()

    if not args.no_github:
        result.extend(github_sources())

    result = [s for s in result if s['rows']]
    if not result:
        sys.exit('未抓到任何数据')
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False)
    total = sum(len(r['rows']) for r in result)
    names = '、'.join(f"{r['name']}({len(r['rows'])})" for r in result)
    print(f'完成：共 {total} 条 [{names}] -> {args.out}')


if __name__ == '__main__':
    main()
