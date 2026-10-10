#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""并发打开飞书系岗位详情页，检测「该职位已下线」横幅，输出验活结果。

输出 web/data/link_check.json：{url: {"v": true(有效)/false(已下架)/null(未验证), "ts": 验活时间戳}}
构建脚本 build_web.py 读取该文件剔除已下架岗位；多次运行会合并结果（未覆盖的保留旧值）。

用法：
  tools/.venv/Scripts/python tools/validate_feishu_links.py                    # 全部
  tools/.venv/Scripts/python tools/validate_feishu_links.py --scope campus     # 只验校招/实习/未标注
  tools/.venv/Scripts/python tools/validate_feishu_links.py --scope social     # 只验社招
"""

import argparse
import asyncio
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(ROOT, 'web', 'data', 'link_check.json')
CONCURRENCY = 10
DEAD_MARK = '该职位已下线'
# 确凿的存活信号：详情正文/投递入口出现才算有效（避免页面慢加载导致假阴性）
ALIVE_MARKS = ['职位描述', '岗位职责', '任职要求', '职位要求', '申请职位', '立即投递', '投递简历']


async def check_page(context, url, sem, results, deadline):
    if time.time() > deadline:
        return
    async with sem:
        if time.time() > deadline:
            return
        page = await context.new_page()
        try:
            await page.goto(url, timeout=15000, wait_until='domcontentloaded')
            # 先等下线横幅，再等存活信号；两者都没等到 → 未验证（不误判为有效）
            verdict = None
            # 下架判定：文字「该职位已下线」或专用容器 class NoLongerAvailable（noDataText 是通用占位样式，不作为判据）
            try:
                await page.wait_for_function(
                    "() => document.body.innerText.includes('该职位已下线')"
                    " || !!document.querySelector('[class*=\"NoLongerAvailable\"]')",
                    timeout=10000)
                verdict = False
            except Exception:
                try:
                    marks = ','.join(f"'{m}'" for m in ALIVE_MARKS)
                    await page.wait_for_function(
                        "() => { const t = document.body.innerText;"
                        f" return [{marks}].some(k => t.includes(k)); }}",
                        timeout=10000)
                    verdict = True
                except Exception:
                    verdict = None
            results[url] = {'v': verdict, 'ts': int(time.time())}
        except Exception:
            results[url] = {'v': None, 'ts': int(time.time())}
        finally:
            await page.close()


async def run(urls, deadline):
    results = {}
    sem = asyncio.Semaphore(CONCURRENCY)
    from playwright.async_api import async_playwright
    # 飞书站点国内直连最快：给浏览器进程剔除代理环境变量
    clean_env = {k: v for k, v in os.environ.items() if not k.lower().endswith('_proxy')}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(channel='chrome', headless=True, env=clean_env)
        context = await browser.new_context(viewport={'width': 1280, 'height': 800})
        tasks = [check_page(context, url, sem, results, deadline) for url in urls]
        await asyncio.gather(*tasks)
        await browser.close()
    return results


def load_prev():
    if os.path.exists(OUT_PATH):
        try:
            with open(OUT_PATH, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def prev_ts(entry):
    if isinstance(entry, dict):
        return entry.get('ts', 0)
    return 0   # 旧格式（bool）视为很久以前验过


def main():
    parser = argparse.ArgumentParser(description='飞书系岗位链接验活')
    parser.add_argument('--in', dest='src', default=os.path.join(ROOT, 'recruit', 'data', 'feishu_base_all.json'))
    parser.add_argument('--timeout-min', type=int, default=35, help='本次验活时长上限（分钟）')
    parser.add_argument('--scope', choices=['all', 'campus', 'social'], default='all',
                        help='campus=校招/实习/未标注；social=社招；all=全部')
    args = parser.parse_args()

    with open(args.src, encoding='utf-8') as f:
        sources = json.load(f)
    campus, social, seen = [], [], set()
    for s in sources:
        for r in s['rows']:
            u = (r.get('简历投递链接') or '').strip()
            if 'jobs.feishu.cn' not in u or u in seen:
                continue
            seen.add(u)
            (social if '社招' in (r.get('批次') or '') else campus).append(u)

    urls = {'campus': campus, 'social': social, 'all': campus + social}[args.scope]
    # 最久没验的优先（轮转覆盖），没验过的排最前
    prev = load_prev()
    urls.sort(key=lambda u: prev_ts(prev.get(u)))
    print(f'待验活链接 {len(urls)} 个（范围 {args.scope}：校招 {len(campus)} / 社招 {len(social)}，'
          f'并发 {CONCURRENCY}，上限 {args.timeout_min} 分钟）', flush=True)

    deadline = time.time() + args.timeout_min * 60
    results = asyncio.run(run(urls, deadline))

    # 粘性下架标记：本次未能确认存活（None）但历史确认下架 → 维持下架，防止下架岗位被反复抓回来
    for url, res in results.items():
        if res.get('v') is None:
            pe = prev.get(url)
            if isinstance(pe, dict) and pe.get('v') is False:
                res['v'] = False

    valid = sum(1 for v in results.values() if v.get('v') is True)
    dead = sum(1 for v in results.values() if v.get('v') is False)
    unknown = sum(1 for v in results.values() if v.get('v') is None)
    print(f'验活完成：有效 {valid}，已下架 {dead}，未验证 {unknown}（共 {len(results)} 个）', flush=True)

    # 合并历史结果：本次未覆盖的链接保留上次结论
    merged = dict(prev)
    merged.update(results)
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(merged, f, ensure_ascii=False)
    print(f'结果写入 {OUT_PATH}（累计 {len(merged)} 条）')


if __name__ == '__main__':
    main()
