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


def fetch_tencent_details(page, post_ids):
    """逐个取岗位详情（岗位描述/岗位要求），分批执行避免单次调用过长。"""
    out = {}
    js = """async (ids) => {
      const res = {};
      for (const pid of ids) {
        try {
          const r = await fetch('/api/v1/jobDetails/getJobDetailsByPostId?postId=' + pid + '&timestamp=' + Date.now());
          const j = await r.json();
          const d = j.data || {};
          // 普通岗位用 desc/request；青云课题类用 topicDetail/topicRequirement
          res[pid] = {d: (d.desc || d.topicDetail || '').trim(),
                      q: (d.request || d.topicRequirement || '').trim()};
        } catch (e) { res[pid] = {d: '', q: ''}; }
      }
      return res;
    }"""
    for i in range(0, len(post_ids), 40):
        out.update(page.evaluate(js, post_ids[i:i + 40]))
    return out


def fetch_tencent(page):
    """腾讯校招：列表接口 + 详情接口（岗位描述/要求）。"""
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
        for (const x of lst) {
          if (!x.positionTitle) continue;
          out.push({
            t: x.positionTitle,
            c: (x.workCities || '').trim().split(/\\s+/).filter(Boolean).join(' / '),
            k: x.recruitLabelName || x.projectName || '',
            b: (x.bgs || '').trim().split(/\\s+/).filter(Boolean).join(' '),
            p: x.postId || '',
            u: x.postId ? 'https://join.qq.com/post_detail.html?postid=' + x.postId : ''
          });
        }
        if (lst.length < 200) break;
      }
      return out;
    }"""
    positions = page.evaluate(js)
    ids = [p['p'] for p in positions if p.get('p')]
    if ids:
        print(f'    抓取 {len(ids)} 个岗位的详情（描述/要求）...', flush=True)
        details = fetch_tencent_details(page, ids)
        for p in positions:
            det = details.get(p.get('p')) or {}
            if det.get('d'):
                p['d'] = det['d'][:800]
            if det.get('q'):
                p['q'] = det['q'][:500]
    return positions


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
                positions = ADAPTERS[company](page)
            except Exception as e:
                print(f'  [跳过] {company}: {type(e).__name__}: {e}', flush=True)
                continue
            seen_titles, dedup = set(), []
            for p in positions:
                if p.get('t') and p['t'] not in seen_titles:
                    seen_titles.add(p['t'])
                    dedup.append(p)
            cache[company] = {'positions': dedup[:MAX_TITLES], 'updated': today}
            print(f'  {company}: {len(dedup[:MAX_TITLES])} 个岗位（含地点/类型/事业群）', flush=True)
        browser.close()

    save_json(CACHE_PATH, cache)
    print(f'完成：缓存 {len(cache)} 家公司 -> {CACHE_PATH}')


if __name__ == '__main__':
    main()
