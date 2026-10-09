#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""并发打开飞书系岗位详情页，检测「该职位已下线」横幅，输出验活结果。

输出 web/data/link_check.json：{url: True(有效)/False(已下架)/None(未能验证)}。
构建脚本 build_web.py --validate 读取该文件剔除已下架岗位。

用法：tools/.venv/Scripts/python tools/validate_feishu_links.py [--in raw.json] [--timeout-min 25]
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


async def check_page(browser, url, sem, results, deadline):
    if time.time() > deadline:
        return
    async with sem:
        if time.time() > deadline:
            return
        page = await browser.new_page()
        try:
            await page.goto(url, timeout=15000, wait_until='domcontentloaded')
            await page.wait_for_timeout(1800)
            txt = await page.evaluate('document.body.innerText')
            results[url] = DEAD_MARK not in txt
        except Exception:
            results[url] = None   # 加载失败按"未验证"处理，保留数据
        finally:
            await page.close()


async def run(urls, deadline):
    results = {}
    sem = asyncio.Semaphore(CONCURRENCY)
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(channel='chrome', headless=True)
        context = await browser.new_context(viewport={'width': 1280, 'height': 800})
        tasks = [check_page(context, url, sem, results, deadline) for url in urls]
        await asyncio.gather(*tasks)
        await browser.close()
    return results


def main():
    parser = argparse.ArgumentParser(description='飞书系岗位链接验活')
    parser.add_argument('--in', dest='src', default=os.path.join(ROOT, 'recruit', 'data', 'feishu_base_all.json'))
    parser.add_argument('--timeout-min', type=int, default=35, help='验活总时长上限（分钟）')
    parser.add_argument('--scope', choices=['campus', 'all'], default='all',
                        help='campus=只验校招/实习/未标注岗位（云端快速模式）；all=全部')
    args = parser.parse_args()

    with open(args.src, encoding='utf-8') as f:
        sources = json.load(f)
    # 校招/实习/未标注岗位优先验活（时限内先保证重点数据），社招排后
    priority, normal = [], []
    seen = set()
    for s in sources:
        for r in s['rows']:
            u = (r.get('简历投递链接') or '').strip()
            if 'jobs.feishu.cn' not in u or u in seen:
                continue
            seen.add(u)
            (normal if '社招' in (r.get('批次') or '') else priority).append(u)
    urls = priority + normal
    if args.scope == 'campus':
        urls = priority   # 云端模式：只验校招范围
    print(f'待验活链接 {len(urls)} 个（范围 {args.scope}，并发 {CONCURRENCY}，上限 {args.timeout_min} 分钟）', flush=True)

    deadline = time.time() + args.timeout_min * 60
    results = asyncio.run(run(urls, deadline))

    valid = sum(1 for v in results.values() if v is True)
    dead = sum(1 for v in results.values() if v is False)
    unknown = sum(1 for v in results.values() if v is None)
    print(f'验活完成：有效 {valid}，已下架 {dead}，未验证 {unknown}', flush=True)

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False)
    print(f'结果写入 {OUT_PATH}')


if __name__ == '__main__':
    main()
