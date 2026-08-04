#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""飞书多维表格适配器：拉取分享的秋招汇总表（如朱迪学姐 27届汇总表）。

原理（已验证）：
- Playwright 驱动 Chrome 打开分享链接获得游客会话（接口需 cookie，curl 直连返回 Login Required）
- clientvars 接口初始化会话，并获取字段名映射与多选项文本映射
- records 接口分页拉取全量记录（响应为 gzip+base64 编码），解码后提取字段
- 按方向关键词 + 招聘届次过滤，输出候选到 recruit/inbox/

配置：tools/scraper/sources.json 的 feishu_base_sources 数组
  {"name": "源名", "url": "https://xxx.feishu.cn/base/{app}?table={table}&view={view}"}

用法：
  tools/.venv/bin/python tools/scraper/scrape_feishu_base.py
  tools/.venv/bin/python tools/scraper/scrape_feishu_base.py --all-rounds   # 不过滤届次
  tools/.venv/bin/python tools/scraper/scrape_feishu_base.py --orgs 源名     # 只跑指定源
"""

import argparse
import base64
import gzip
import json
import os
import re
import sys
from datetime import date
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INBOX_DIR = os.path.join(ROOT, 'recruit', 'inbox')
COMPANIES_DIR = os.path.join(ROOT, 'recruit', 'companies')
SOURCES_JSON = os.path.join(ROOT, 'tools', 'scraper', 'sources.json')

# 字段名 -> 本适配器的逻辑字段（按名称在表中查找）
FIELD_NAMES = {
    'company': '公司',
    'role': '招聘岗位',
    'location': '工作地点',
    'rounds': '招聘届次',
    'deadline': '截止时间',
    'link': '简历投递链接',
    'written': '是否笔试',
    'note': '备注',
}


def load_sources():
    with open(SOURCES_JSON, 'r', encoding='utf-8') as f:
        config = json.load(f)
    return config.get('feishu_base_sources', [])


def parse_url(url):
    """从分享 URL 解析 app/table/view。"""
    m = re.search(r'/base/([A-Za-z0-9]+)', url)
    q = parse_qs(urlparse(url).query)
    return {
        'app': m.group(1) if m else '',
        'table': (q.get('table') or [''])[0],
        'view': (q.get('view') or [''])[0],
    }


def decode(v):
    """兼容普通 JSON 与 gzip+base64 编码。"""
    if isinstance(v, str) and v.startswith('H4sI'):
        try:
            return json.loads(gzip.decompress(base64.b64decode(v)).decode('utf-8'))
        except Exception:
            return v
    return v


def fetch_clientvars(page, app, table, view):
    """初始化会话并返回 (字段名映射, 选项文本映射)。"""
    page.evaluate(f"""async () => {{
      await fetch('/space/api/v1/bitable/{app}/clientvars?tableID={table}&viewID={view}'
        + '&recordLimit=200&ondemandLimit=200&needBase=true&viewLazyLoad=true'
        + '&ondemandVer=2&openType=0&noMissCS=true&optimizationFlag=1&removeFmlExtra=true');
    }}""")
    page.wait_for_timeout(3000)
    cv = page.evaluate(f"""async () => {{
      const resp = await fetch('/space/api/v1/bitable/{app}/clientvars?tableID={table}&viewID={view}'
        + '&recordLimit=200&ondemandLimit=200&needBase=true&viewLazyLoad=true'
        + '&ondemandVer=2&openType=0&noMissCS=true&optimizationFlag=1&removeFmlExtra=true');
      return await resp.json();
    }}""")
    td = decode((cv.get('data') or {}).get('table'))
    field_map = {}
    option_map = {}
    if isinstance(td, dict):
        for fid, fv in (td.get('fieldMap') or {}).items():
            if isinstance(fv, dict):
                field_map[fid] = fv.get('name') or '?'
                for opt in ((fv.get('property') or {}).get('options') or []):
                    option_map[opt.get('id')] = opt.get('name', '?')
    return field_map, option_map


def fetch_records(page, app, table, view):
    """分页拉取全量记录，返回 {recordId: fields}。"""
    all_records = {}
    offset = 0
    for _ in range(30):
        raw = page.evaluate(f"""async () => {{
          const resp = await fetch('/space/api/v1/bitable/{app}/records?tableId={table}&viewId={view}'
            + '&viewLazyLoad=true&offset={offset}&limit=3000&tableID={table}&viewID={view}&removeFmlExtra=true');
          const j = await resp.json();
          return j.data ? j.data.records : null;
        }}""")
        if not raw:
            break
        d = json.loads(gzip.decompress(base64.b64decode(raw)).decode('utf-8'))
        rm = d.get('recordMap') or {}
        if not rm:
            break
        all_records.update(rm)
        total = d.get('tableRecordNum')
        if len(all_records) >= (total or len(all_records)):
            break
        offset += 3000
    return all_records


def cell_value(fv):
    """字段值 [{type,text,link}] -> 纯文本。"""
    if not fv:
        return ''
    v = fv.get('value')
    if isinstance(v, list):
        parts = []
        for seg in v:
            if isinstance(seg, dict):
                t = seg.get('text') or ''
                parts.append(t)
            else:
                parts.append(str(seg))
        return ' '.join(p for p in parts if p)
    return str(v) if isinstance(v, (str, int, float)) else ''


def main():
    parser = argparse.ArgumentParser(description='飞书多维表格（秋招汇总表）抓取')
    parser.add_argument('--all-rounds', action='store_true', help='不过滤招聘届次（默认只保留含 2027 或未标注的）')
    parser.add_argument('--sources', default='', help='仅跑指定源名（逗号分隔）')
    args = parser.parse_args()

    sources = load_sources()
    if args.sources:
        wanted = set(args.sources.split(','))
        sources = [s for s in sources if s['name'] in wanted]
    if not sources:
        sys.exit('错误：sources.json 未配置 feishu_base_sources（见工具头部说明）')

    # 方向关键词
    with open(SOURCES_JSON, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    keywords = cfg.get('direction_keywords', [])

    existing = {f[:-3] for f in os.listdir(COMPANIES_DIR)
                if f.endswith('.md') and not f.startswith('_')} if os.path.isdir(COMPANIES_DIR) else set()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit('缺少 playwright：请执行 tools/.venv/bin/pip install playwright')

    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 800})
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
                print(f'  [跳过] {name}: {type(e).__name__}')
                continue

            # 字段 ID 反查
            fid = {}
            for logical, fname in FIELD_NAMES.items():
                for f, fn in field_map.items():
                    if fn == fname:
                        fid[logical] = f
                        break
            missing = [k for k in ('company', 'role') if k not in fid]
            if missing:
                print(f'  [跳过] {name}: 缺少字段 {missing}（表字段: {set(field_map.values())}）')
                continue

            hits = []
            for rec in records.values():
                company = cell_value(rec.get(fid['company'])).strip()
                role = cell_value(rec.get(fid.get('role', ''))).strip()
                rounds_raw = cell_value(rec.get(fid.get('rounds', '')))
                rounds = ' / '.join(option_map.get(t, t) for t in rounds_raw.split() if t)
                if not args.all_rounds:
                    if rounds and '2027' not in rounds:
                        continue
                text = f'{company} {role}'
                matched = ''
                for kw in keywords:
                    if kw.lower() in text.lower():
                        matched = f'关键词「{kw}」'
                        break
                if not matched:
                    continue
                hits.append({
                    'company': company, 'role': role[:120],
                    'location': ' / '.join(option_map.get(t, t) for t in cell_value(rec.get(fid.get('location', ''))).split() if t),
                    'rounds': rounds,
                    'deadline': cell_value(rec.get(fid.get('deadline', ''))).strip(),
                    'written': ' / '.join(option_map.get(t, t) for t in cell_value(rec.get(fid.get('written', ''))).split() if t),
                    'link': cell_value(rec.get(fid.get('link', ''))).strip(),
                    'matched': matched,
                })
            print(f'  共 {len(records)} 条记录，命中 {len(hits)} 条')

            if not hits:
                continue
            today = date.today().isoformat()
            lines = [
                f'# {today} {name}（自动抓取，需人工审核）',
                '',
                f'> 来源：{name} — {src["url"]}',
                f'> 记录 {len(records)} 条，命中 {len(hits)} 条（关键词 + 届次过滤）',
                '',
                '| 公司 | 岗位/链接 | 地点 | 届次 | 截止 | 笔试 | 命中 | 状态 |',
                '|---|---|---|---|---|---|---|---|',
            ]
            for h in hits:
                link_cell = f'[{h["link"][:30]}]({h["link"]})' if h['link'] else '-'
                status = '已入库' if h['company'] in existing else '待审核'
                lines.append(
                    f'| {h["company"]} | {h["role"]} | {h["location"]} | {h["rounds"]} | '
                    f'{h["deadline"]} | {h["written"]} | {h["matched"]} | {status} |')
            lines += ['', '## 审核指引', '',
                      '1. 核对岗位与届次后，用 `python3 tools/recruit.py add <公司名>` 建立记录',
                      '2. 投递链接打开后确认岗位详情', '3. 审核完毕后删除本文件', '']
            out_file = os.path.join(INBOX_DIR, f'{today}_{name}_candidates.md')
            with open(out_file, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            print(f'  已写入 {out_file}')
        browser.close()
    print('完成。候选见 recruit/inbox/ 目录。')


if __name__ == '__main__':
    main()
