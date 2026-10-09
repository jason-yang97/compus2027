#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实验：用 Cloudflare Workers AI 的视觉模型(llava)从招聘公告图片中提取工作地点。

用法：tools/.venv/Scripts/python tools/vision_probe.py [--articles 5] [--per-article 2]
图片会保存到 .secrets/vision_imgs/ 便于人工核对。
"""

import argparse
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools', 'scraper'))
from fetch_feishu_all import LOC_CACHE_PATH, CITY_WORDS, fetch_article_text  # noqa: E402

ACCOUNT_ID = '9e89490c0b4c73e67bf6dc132792ca58'
MODEL = '@cf/llava-hf/llava-1.5-7b-hf'
TOKEN_PATH = os.path.join(ROOT, '.secrets', 'cf_ai_token.txt.txt')
IMG_DIR = os.path.join(ROOT, '.secrets', 'vision_imgs')
PROMPT = ('这是中国公司的招聘公告图片。请找出图中写的工作城市/工作地点，'
          '只输出城市名，用顿号分隔；如果图中没有城市信息，输出"无"。')


def read_token():
    with open(TOKEN_PATH, encoding='utf-8') as f:
        return f.read().strip()


def get(url, headers=None, timeout=15):
    req = urllib.request.Request(url, headers=headers or {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def article_images(url, limit):
    """从公众号文章 HTML 提取图片地址（data-src 优先）。"""
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode('utf-8', errors='replace')
    except Exception:
        return []
    urls = re.findall(r'data-src="(https?://[^"]+)"', html) or re.findall(r'<img[^>]+src="(https?://[^"]+)"', html)
    seen, out = set(), []
    for u in urls:
        if u in seen:
            continue
        seen.add(u)
        if 'qpic.cn' in u or 'weixin' in u:
            out.append(u)
        if len(out) >= limit:
            break
    return out


def llava_cities(token, img_bytes):
    """调用 Workers AI llava 读图，返回模型输出文本。"""
    body = json.dumps({'image': list(img_bytes), 'prompt': PROMPT, 'max_tokens': 120}).encode()
    req = urllib.request.Request(
        f'https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/{MODEL}',
        data=body, headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=90) as resp:
        j = json.loads(resp.read().decode('utf-8', errors='replace'))
    res = j.get('result') or {}
    return res.get('description') or json.dumps(j, ensure_ascii=False)[:200]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--articles', type=int, default=5)
    parser.add_argument('--per-article', type=int, default=2)
    args = parser.parse_args()

    token = read_token()
    cache = json.load(open(LOC_CACHE_PATH, encoding='utf-8'))
    # 正文里没提到城市的文章 = 地点只可能在图里的候选
    empty = [u for u, v in cache.items() if not v and 'mp.weixin.qq.com' in u]
    print(f'正文无城市的文章 {len(empty)} 篇，取前 {args.articles} 篇测试')
    os.makedirs(IMG_DIR, exist_ok=True)

    tested = 0
    for art in empty[:args.articles]:
        imgs = article_images(art, args.per_article)
        print(f'\n文章: {art[:70]}  图片 {len(imgs)} 张')
        for i, iu in enumerate(imgs):
            try:
                data = get(iu)
            except Exception as e:
                print(f'  图片下载失败 {type(e).__name__}')
                continue
            fn = os.path.join(IMG_DIR, f'img{tested:02d}.jpg')
            with open(fn, 'wb') as f:
                f.write(data)
            try:
                ans = llava_cities(token, data)
            except Exception as e:
                ans = f'<调用失败 {type(e).__name__}: {e}>'
            print(f'  [{tested}] {len(data)//1024}KB -> llava: {ans[:150]}')
            print(f'      本地图片: {fn}')
            tested += 1
            if tested >= args.articles * args.per_article:
                break
        if tested >= args.articles * args.per_article:
            break
    print(f'\n共测试 {tested} 张图')


if __name__ == '__main__':
    main()
