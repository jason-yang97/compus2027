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
import re
import sys
import urllib.parse
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scrape_feishu_base import (  # noqa: E402
    fetch_clientvars, fetch_records, load_sources, parse_url,
)
from scrape_feishu import fmt_time, fmt_recruit_type  # noqa: E402
from scrape_github import load_config, parse_entries, fetch_raw  # noqa: E402


def fetch_positions_csrf(page, limit, keyword=''):
    """带 CSRF token 分页拉取岗位列表（最多 limit 条，支持关键词）。"""
    import urllib.parse
    kw = urllib.parse.quote(keyword)
    collected = {}
    offset = 0
    total = None
    token = fetch_csrf_token(page)
    while len(collected) < limit and (total is None or offset < (total or 0)):
        size = min(200, limit - len(collected))
        js = """async (args) => {
          const r = await fetch('/api/v1/search/job/posts?keyword=' + args.kw
            + '&limit=' + args.size + '&offset=' + args.offset
            + '&job_category_id_list=&tag_id_list=&location_code_list='
            + '&subject_id_list=&recruitment_id_list=&portal_type=6'
            + '&job_function_id_list=&storefront_id_list=&portal_entrance=1', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'x-csrf-token': args.token},
            body: JSON.stringify({keyword: args.kwRaw, limit: args.size, offset: args.offset,
              job_category_id_list: [], tag_id_list: [], location_code_list: [],
              subject_id_list: [], recruitment_id_list: []})
          });
          const j = await r.json();
          return j.data ? j.data : {error: 'http ' + r.status};
        }"""
        try:
            data = page.evaluate(js, {'kw': kw, 'kwRaw': keyword, 'size': size,
                                      'offset': offset, 'token': token})
        except Exception:
            token = fetch_csrf_token(page)
            continue
        if not data or data.get('error') or not data.get('job_post_list'):
            break
        total = data.get('count') or total
        for x in data['job_post_list']:
            collected[x.get('id')] = x
        offset += size
    return {'count': total or len(collected), 'job_post_list': list(collected.values())}

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


DEGREE_ORDER = ['大专', '本科', '硕士', '博士']
DEGREE_RE = re.compile(r'(大专|专科|本科|学士|硕士|研究生|博士)')


def extract_rounds_degrees(desc):
    """从职位描述提取届次与学历要求的文本（飞书列表接口不返回这两个结构化字段）。"""
    text = desc or ''
    years = []
    for m in re.finditer(r'(20\d{2})\s*届', text):
        y = int(m.group(1))
        if y not in years:
            years.append(y)
    for m in re.finditer(r'(?<!\d)(\d{2})\s*届', text):
        y = 2000 + int(m.group(1))
        if 2020 <= y <= 2035 and y not in years:
            years.append(y)
    parts = [f'{y}届' for y in sorted(years)]
    if '往届' in text:
        parts.append('往届')
    elif re.search(r'不限届|届数不限|届次不限', text):
        parts.append('不限届')
    rounds = ' / '.join(dict.fromkeys(parts))  # 去重保序

    found = set()
    for m in DEGREE_RE.finditer(text):
        d = m.group(1)
        d = {'专科': '大专', '学士': '本科', '研究生': '硕士'}.get(d, d)
        found.add(d)
    if found:
        # 「本科及以上」类表述：向上补全到博士
        if re.search(r'(大专|专科|本科|学士|硕士|研究生|博士)\s*及(以上|相当)', text):
            top = max(DEGREE_ORDER.index(d) for d in found)
            found = set(DEGREE_ORDER[top:])
        edu = ' , '.join(d for d in DEGREE_ORDER if d in found)
    else:
        edu = ''
    return rounds, edu


def fetch_csrf_token(page):
    """获取当前站点的 CSRF token（详情接口用），失败返回空串。"""
    js = """async () => {
      const tk = await fetch('/api/v1/csrf/token', {method: 'POST',
        headers: {'Content-Type': 'application/json'}, body: '{}'});
      const j = await tk.json();
      return (j.data && j.data.token) || '';
    }"""
    for _ in range(2):
        try:
            return page.evaluate(js)
        except Exception:
            page.wait_for_timeout(2000)
    return ''


def fetch_job_detail(page, pid, token):
    """单个岗位详情（列表摘要的 requirement 与详情页不一致，届次只在详情里）。"""
    js = """async (args) => {
      const r = await fetch('/api/v1/job/posts/' + args.pid,
        {headers: {'x-csrf-token': args.token}});
      if (!r.ok) return null;
      const j = await r.json();
      return j.data ? j.data.job_post_detail : null;
    }"""
    try:
        return page.evaluate(js, {'pid': pid, 'token': token})
    except Exception:
        return None


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
    """飞书招聘系统企业全量岗位 -> 统一行格式。

    每家企业：先按默认排序分页抓 limit 条，再用关键词「实习」补搜
    （实习帖可能排在列表深处），之后只对实习/校招/未标注且缺届次的
    岗位调详情接口补届次与学历。
    """
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
            posts_map = {}
            for x in (fetch_positions_csrf(page, limit).get('job_post_list') or []):
                posts_map[x.get('id')] = x
            kw_count = 0
            for x in (fetch_positions_csrf(page, limit, keyword='实习').get('job_post_list') or []):
                if x.get('id') not in posts_map:
                    posts_map[x.get('id')] = x
                    kw_count += 1
        except Exception as e:
            print(f'  [跳过] {name}({org}): {type(e).__name__}', flush=True)
            continue
        posts = list(posts_map.values())
        print(f'  {name}({org}): {len(posts)} 岗位（关键词补捞 {kw_count}）', flush=True)
        token = None
        detail_used = 0
        fail_streak = 0
        rows_in_org = []
        for p in posts:
            title = (p.get('title') or '')[:200]
            rtype = fmt_recruit_type(p)
            cat = (p.get('job_category') or {}).get('name', '')
            city = ' / '.join(
                (ct or {}).get('name', '') for ct in (p.get('city_list') or []) if (ct or {}).get('name'))
            # 批次按岗位类型归类：实习 > 校招 > 社招（含标题关键词）
            rt_all = f'{title} {rtype} {cat}'
            batch = '实习' if '实习' in rt_all else ('校招' if '校招' in rt_all else ('社招' if '社招' in rt_all else ''))
            # 届次/学历藏在职位描述与职位要求里（列表接口不返回结构化字段）
            full_desc = (p.get('description') or '') + '\n' + (p.get('requirement') or '')
            rounds, edu = extract_rounds_degrees(full_desc)
            # 非社招且列表摘要没写届次的，调详情接口补全（详情页的要求文本与摘要不同）
            if batch in ('实习', '校招', '未标注', '') and not rounds and p.get('id') and fail_streak < 5:
                if not token:
                    token = fetch_csrf_token(page)
                d = fetch_job_detail(page, p['id'], token)
                if d is None:
                    token = fetch_csrf_token(page)
                    d = fetch_job_detail(page, p['id'], token)
                if d:
                    fail_streak = 0
                    detail_used += 1
                    d_text = (d.get('description') or '') + '\n' + (d.get('requirement') or '')
                    d_rounds, d_edu = extract_rounds_degrees(d_text)
                    if d_rounds:
                        rounds = d_rounds
                    if d_edu:
                        edu = d_edu
                else:
                    fail_streak += 1
            rows_in_org.append({
                '公司': name,
                '招聘岗位': title,
                '工作地点': city,
                '招聘届次': rounds,
                '截止时间': '尽快投递',
                # 岗位帖子随时可能下架，链接指向官网搜索页（岗位名预填）保证永不过期
                '简历投递链接': f'https://{org}.jobs.feishu.cn/index/position/list?keywords={urllib.parse.quote(title)}',
                '是否笔试': '',
                '备注': ' / '.join(x for x in (rtype, cat) if x)[:200],
                '学历要求': edu, '专业要求': '', '企业类型': ent, '行业类别': ind,
                '批次': batch,
                '开始时间': today,
                '更新时间': fmt_time(p.get('publish_time')),
            })
        rows.extend(rows_in_org)
        print(f'    其中调详情接口补届次 {detail_used} 个', flush=True)
    # 同公司同岗位名的兄弟帖（不同城市/批次分开挂）共享届次与学历
    groups = {}
    for r in rows:
        groups.setdefault((r['公司'], r['招聘岗位']), []).append(r)
    for group in groups.values():
        donor = next((r for r in group if r['招聘届次']), None)
        if donor:
            for r in group:
                if not r['招聘届次']:
                    r['招聘届次'] = donor['招聘届次']
                if not r['学历要求']:
                    r['学历要求'] = donor['学历要求']
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
    parser.add_argument('--limit', type=int, default=500, help='飞书招聘每企业岗位数上限')
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
            try:
                result.append({'name': '飞书招聘系统', 'url': '',
                               'rows': feishu_job_rows(page, args.limit)})
            except Exception as e:
                print(f'  [失败] 飞书招聘系统: {type(e).__name__}: {e}', flush=True)

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
