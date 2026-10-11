#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓取「可抓取」的招聘公告正文（政府/企业官网等），用 Workers AI 抽取结构化字段。

- 只处理学姐表里非微信公众号的公告链接（微信正文抓不到，已排除）
- 正文抓得到（>=300 字）的才送模型抽取：专业要求 / 截止时间 / 学历要求
- 结果缓存到 recruit/data/ann_ai_fields.json（随仓库同步，每天只处理新增链接）

环境变量 CF_AI_TOKEN / CF_AIG_TOKEN；CF_AI_GATEWAY 默认 default。
用法：python tools/extract_announcements.py [--max 300] [--concurrency 4]
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACCOUNT_ID = '9e89490c0b4c73e67bf6dc132792ca58'
MODEL = '@cf/meta/llama-3.3-70b-instruct-fp8-fast'
GATEWAY = os.environ.get('CF_AI_GATEWAY', '').strip() or 'default'
CACHE = os.path.join(ROOT, 'recruit', 'data', 'ann_ai_fields.json')
SRC = os.path.join(ROOT, 'recruit', 'data', 'feishu_base_all.json')
# 已确认抓不到正文的域名（JS 壳 + 验证码，urllib/Playwright 都拿不到内容）
BLOCKED = ('offerleida.com',)
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36',
      'Accept-Language': 'zh-CN,zh;q=0.9'}
PROMPT = ('下面是一篇中国校园招聘公告的正文。请抽取三样信息，只输出 JSON，不要解释：\n'
          '{"major":"专业要求（如 计算机相关专业；原文没写就空字符串）",'
          '"deadline":"报名/投递截止日期，尽量转成 2026-10-31 这种格式；没有具体日期就空字符串",'
          '"edu":"学历要求（如 本科、硕士、博士，顿号分隔；没写就空字符串）"}\n'
          '原文没有的信息一律留空，不要编造。\n\n正文：\n')


def read_secret(*names):
    for n in names:
        p = os.path.join(ROOT, '.secrets', n)
        if os.path.exists(p):
            with open(p, encoding='utf-8') as f:
                return f.read().strip()
    return ''


def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return default
    return default


def fetch_text(url):
    """抓取网页正文纯文本；失败/太短返回 ''。"""
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=25) as resp:
            raw = resp.read()
    except Exception:
        return ''
    if len(raw) > 3 * 1024 * 1024:
        return ''
    text = ''
    for enc in ('utf-8', 'gbk', 'gb18030'):
        try:
            text = raw.decode(enc)
            break
        except Exception:
            continue
    if not text:
        text = raw.decode('utf-8', errors='replace')
    text = re.sub(r'<(script|style|noscript)\b.*?</\1>', ' ', text, flags=re.S | re.I)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'&[a-zA-Z#0-9]+;', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def call_model(token, gw_token, text):
    body = json.dumps({'messages': [{'role': 'user', 'content': PROMPT + text[:8000]}],
                       'max_tokens': 600, 'temperature': 0}).encode()
    url = (f'https://gateway.ai.cloudflare.com/v1/{ACCOUNT_ID}/{GATEWAY}/workers-ai/{MODEL}'
           if GATEWAY else
           f'https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/{MODEL}')
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json',
               'User-Agent': UA['User-Agent']}
    if GATEWAY:
        headers['cf-aig-metadata'] = json.dumps({'app': 'compus2027'})
        if gw_token:
            headers['cf-aig-authorization'] = f'Bearer {gw_token}'
    req = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            j = json.loads(resp.read().decode('utf-8', errors='replace'))
    except urllib.error.HTTPError as e:
        detail = e.read()[:300]
        if b'neurons' in detail.lower() or b'quota' in detail.lower():
            raise RuntimeError('免费额度用尽')
        return None
    except Exception:
        return None
    msg = ((j.get('result') or {}).get('choices') or [{}])[0].get('message', {})
    out = (msg.get('content') or '') or (msg.get('reasoning_content') or '')
    m = re.search(r'\{.*\}', out, re.S)
    if not m:
        return {}
    try:
        d = json.loads(m.group(0))
    except Exception:
        return {}
    res = {}
    for k in ('major', 'deadline', 'edu'):
        v = str(d.get(k) or '').strip()
        if v and v.lower() not in ('none', 'null', '无', '空', '-', 'n/a'):
            res[k] = v[:400]
    return res


def collect_urls(sources):
    seen = {}
    for s in sources:
        if not s['name'].startswith('校招汇总'):
            continue
        for r in s['rows']:
            a = (r.get('公告链接') or '').strip()
            if a and 'mp.weixin.qq.com' not in a and a not in seen:
                seen[a] = (r.get('公司') or '')[:20]
    return seen


def main():
    ap = argparse.ArgumentParser(description='抓取公告正文并用 AI 抽取专业要求/截止时间/学历')
    ap.add_argument('--max', type=int, default=300)
    ap.add_argument('--concurrency', type=int, default=4)
    args = ap.parse_args()

    token = os.environ.get('CF_AI_TOKEN', '').strip() or read_secret('cf_ai_token.txt', 'cf_ai_token.txt.txt')
    if not token:
        print('缺少 CF_AI_TOKEN')
        return
    gw_token = os.environ.get('CF_AIG_TOKEN', '').strip() or read_secret('gateway_token.txt', 'gateway_token.txt.txt')

    sources = load_json(SRC, [])
    if not sources:
        print('缺少源数据', SRC)
        return
    cache = load_json(CACHE, {})
    urls = collect_urls(sources)
    todo = [u for u in urls if u not in cache and not any(b in u for b in BLOCKED)][:args.max]
    print(f'待处理公告 {len(todo)} 条（已缓存 {len(cache)} / 共 {len(urls)}）', flush=True)
    if not todo:
        return

    def work(u):
        text = fetch_text(u)
        if len(text) < 300:
            return u, {'_skip': 'thin' if text else 'fetch-fail'}
        try:
            f = call_model(token, gw_token, text)
        except RuntimeError as e:
            raise
        if f is None:
            return u, {'_skip': 'api-fail'}
        return u, f if f else {'_skip': 'no-field'}

    done = 0
    try:
        with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
            for u, v in ex.map(work, todo):
                cache[u] = v
                if v.get('major') or v.get('deadline') or v.get('edu'):
                    done += 1
    except RuntimeError as e:
        print(f'  停止：{e}', flush=True)

    cache = {'_说明': '公告正文 AI 抽取：链接 -> {major, deadline, edu}；_skip 表示抓不到/无字段', **cache}
    with open(CACHE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)
    print(f'本次抽取到字段 {done} 条，缓存共 {len(cache) - 1} 条 -> {CACHE}', flush=True)


if __name__ == '__main__':
    main()
