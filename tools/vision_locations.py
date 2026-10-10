#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用 Workers AI 的 gemma-4-26b-a4b-it（视觉）从招聘公告图片中提取工作城市。

- 只处理「正文文字里没提到城市」的公告文章（见 article_locations.json）
- 每篇文章取最大的若干张图，调用视觉模型读图，用城市词表匹配结果
- 结果缓存到 recruit/data/vision_locations.json（随仓库同步，每天只处理新增文章）

环境变量 CF_AI_TOKEN（或 .secrets/cf_ai_token.txt.txt）；免费额度内运行。
用法：tools/.venv/Scripts/python tools/vision_locations.py [--max-articles 40]
"""

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools', 'scraper'))
from fetch_feishu_all import CITY_WORDS, LOC_CACHE_PATH, article_images, fetch_article_text  # noqa: E402

ACCOUNT_ID = '9e89490c0b4c73e67bf6dc132792ca58'
MODEL = '@cf/google/gemma-4-26b-a4b-it'
VISION_CACHE = os.path.join(ROOT, 'recruit', 'data', 'vision_locations.json')
TOKEN_FILE = os.path.join(ROOT, '.secrets', 'cf_ai_token.txt.txt')
PROMPT = ('这是中国公司的招聘公告图片。请快速找出图中实际印出的招聘公司名和工作城市，'
          '一句话给出结论（城市用顿号分隔）；没有城市就写"无城市信息"。不要长篇分析。')


def read_token():
    t = os.environ.get('CF_AI_TOKEN', '').strip()
    if t:
        return t
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, encoding='utf-8') as f:
            return f.read().strip()
    return ''


def download(url):
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36',
        'Referer': 'https://mp.weixin.qq.com/'})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def ask_model(token, img_bytes):
    """返回模型输出的全部文本（含思考内容），失败返回 ''。"""
    b64 = base64.b64encode(img_bytes).decode()
    body = json.dumps({'messages': [{'role': 'user', 'content': [
        {'type': 'text', 'text': PROMPT},
        {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + b64}}]}],
        'max_tokens': 3000}).encode()
    req = urllib.request.Request(
        f'https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/{MODEL}',
        data=body, headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            j = json.loads(resp.read().decode('utf-8', errors='replace'))
        m = ((j.get('result') or {}).get('choices') or [{}])[0].get('message', {})
        return (m.get('content') or '') + ' ' + (m.get('reasoning_content') or '')
    except urllib.error.HTTPError as e:
        if e.code in (429, 400) and b'neurons' in e.read()[:300].lower():
            raise RuntimeError('免费额度用尽')
        return ''
    except Exception:
        return ''


def cities_from_text(text):
    return [c for c in CITY_WORDS if c in text]


def process_article(token, url, per_article):
    """读一篇文章的图片，返回城市文本。"""
    found = []
    for iu in article_images(url, per_article):
        try:
            data = download(iu)
        except Exception:
            continue
        if len(data) > 5 * 1024 * 1024:   # 过大跳过
            continue
        out = ask_model(token, data)
        for c in cities_from_text(out):
            if c not in found:
                found.append(c)
        if found:
            break
    return ' / '.join(found[:6])


def main():
    parser = argparse.ArgumentParser(description='视觉模型提取公告图片中的工作地点')
    parser.add_argument('--max-articles', type=int, default=40, help='本次最多处理文章数（控制额度）')
    parser.add_argument('--per-article', type=int, default=2, help='每篇文章最多看图数')
    parser.add_argument('--concurrency', type=int, default=4)
    args = parser.parse_args()

    token = read_token()
    if not token:
        print('缺少 CF_AI_TOKEN（或 .secrets/cf_ai_token.txt.txt）')
        return

    text_cache = {}
    if os.path.exists(LOC_CACHE_PATH):
        with open(LOC_CACHE_PATH, encoding='utf-8') as f:
            text_cache = json.load(f)
    vision_cache = {}
    if os.path.exists(VISION_CACHE):
        with open(VISION_CACHE, encoding='utf-8') as f:
            vision_cache = json.load(f)

    todo = [u for u, v in text_cache.items()
            if not v and 'mp.weixin.qq.com' in u and u not in vision_cache][:args.max_articles]
    print(f'待读图文章 {len(todo)} 篇（并发 {args.concurrency}，每篇最多 {args.per_article} 图）', flush=True)

    done = 0
    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futs = {ex.submit(process_article, token, u, args.per_article): u for u in todo}
        for fut in futs:
            url = futs[fut]
            try:
                vision_cache[url] = fut.result()
            except RuntimeError as e:
                print(f'  停止：{e}', flush=True)
                break
            except Exception:
                vision_cache[url] = ''
            done += 1
            if done % 10 == 0:
                print(f'  已处理 {done}/{len(todo)}', flush=True)

    os.makedirs(os.path.dirname(VISION_CACHE), exist_ok=True)
    with open(VISION_CACHE, 'w', encoding='utf-8') as f:
        json.dump(vision_cache, f, ensure_ascii=False)
    hit = sum(1 for v in vision_cache.values() if v)
    print(f'完成：本次 {done} 篇，缓存累计 {len(vision_cache)} 篇，其中有地点 {hit} 篇')


if __name__ == '__main__':
    main()
