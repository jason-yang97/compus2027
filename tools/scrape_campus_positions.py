#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按公司适配器抓取官网校招岗位（先支持腾讯）。

结果缓存 recruit/data/campus_positions.json：{公司: {"titles": [...], "updated": "YYYY-MM-DD"}}
抓取阶段（fetch_feishu_all.py）会用它替换该公司的公司级公告标题。

用法：tools/.venv/Scripts/python tools/scrape_campus_positions.py [--force]
"""

import argparse
import json
import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools', 'scraper'))
from fetch_feishu_all import load_json, save_json  # noqa: E402

CACHE_PATH = os.path.join(ROOT, 'recruit', 'data', 'campus_positions.json')
MAX_TITLES = 1000   # 每家公司最多保留岗位数


def fetch_tencent(page):
    """腾讯校招：POST /api/v1/position/searchPosition 分页拉取。"""
    page.goto('https://join.qq.com/post.html', timeout=45000, wait_until='domcontentloaded')
    page.wait_for_timeout(6000)
    js = """async () => {
      const out = [];
      for (let pageIndex = 1; pageIndex <= 12; pageIndex++) {
        const r = await fetch('/api/v1/position/searchPosition?timestamp=' + Date.now(), {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({projectIdList: [], projectMappingIdList: [1, 2, 104, 14, 20],
            keyword: '', bgList: [], workCountryType: 0, workCityList: [], recruitCityList: [],
            positionFidList: [], pageIndex: pageIndex, pageSize: 200})});
        const j = await r.json();
        const lst = ((j.data || {}).positionList) || [];
        for (const x of lst) if (x.positionTitle) out.push(x.positionTitle);
        if (lst.length < 200) break;
      }
      return out;
    }"""
    return page.evaluate(js)


ADAPTERS = {
    '腾讯': fetch_tencent,
}


def main():
    parser = argparse.ArgumentParser(description='抓取官网校招岗位')
    parser.add_argument('--force', action='store_true', help='忽略当日缓存强制重抓')
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit('缺少 playwright')

    cache = load_json(CACHE_PATH, {})
    today = date.today().isoformat()
    todo = [c for c in ADAPTERS if args.force or (cache.get(c) or {}).get('updated') != today]
    if not todo:
        print('今日已抓取，跳过')
        return

    clean_env = {k: v for k, v in os.environ.items() if not k.lower().endswith('_proxy')}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True, env=clean_env)
        page = browser.new_page(viewport={'width': 1600, 'height': 1000})
        for company in todo:
            try:
                titles = ADAPTERS[company](page)
            except Exception as e:
                print(f'  [跳过] {company}: {type(e).__name__}: {e}', flush=True)
                continue
            titles = list(dict.fromkeys(t for t in titles if t))[:MAX_TITLES]
            cache[company] = {'titles': titles, 'updated': today}
            print(f'  {company}: {len(titles)} 个岗位', flush=True)
        browser.close()

    save_json(CACHE_PATH, cache)
    print(f'完成：缓存 {len(cache)} 家公司 -> {CACHE_PATH}')


if __name__ == '__main__':
    main()
