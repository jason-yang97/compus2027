#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用 Workers AI（llama-3.3-70b）为「学姐表未收录的公司」推断 企业类型 / 行业类别。

- 只处理非学姐源、且学姐表里没有的公司（主要是 GitHub/飞书源里的具身智能、AI 初创）
- 公司名 + 一句岗位上下文喂给模型，让它从固定词表里选，保证与站内筛选口径一致
- 结果缓存到 recruit/data/company_ai_meta.json（随仓库同步，每天只处理新增公司，几乎零成本）

环境变量 CF_AI_TOKEN / CF_AIG_TOKEN（或 .secrets/*.txt）；CF_AI_GATEWAY 默认 default。
用法：python tools/classify_companies.py [--max 200] [--batch 20]
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
CACHE = os.path.join(ROOT, 'recruit', 'data', 'company_ai_meta.json')
SRC = os.path.join(ROOT, 'recruit', 'data', 'feishu_base_all.json')

ENT = ['民企', '央国企', '外企', '合资', '事业单位', '其他']
IND = ['互联网/人工智能', '智能硬件/机器人', '电子/通信/半导体', '软件技术', '新能源',
       '车企/汽车零部件', '高端装备与国防科技/航空航天', '医疗/医药/生物', '金融业', '制造业',
       '能源/化工/环保', '消费品', '教育/培训/科研', '交通/物流/仓储', '其他']

LINE_RE = re.compile(r'^\s*(\d+)\s*[.、:：|｜]?\s*(.+)$')


def norm_company(name):
    t = re.sub(r'[（(【\[].*?[）)】\]]', '', str(name or ''))
    return re.sub(r'\s+', '', t).lower()


def read_secret(*names):
    for n in names:
        p = os.path.join(ROOT, '.secrets', n)
        if os.path.exists(p):
            with open(p, encoding='utf-8') as f:
                return f.read().strip()
    return ''


def pick(value, options):
    """把模型给的取值对齐到固定词表（容忍截断/多余符号）。"""
    v = str(value or '').strip().strip('*`。. 　')
    if v in options:
        return v
    for o in options:
        if o in v or v in o:
            return o
    return ''


def parse_out(text, idx2comp):
    got = {}
    for line in (text or '').splitlines():
        m = LINE_RE.match(line.strip())
        if not m:
            continue
        i = int(m.group(1))
        parts = re.split(r'[|｜]', m.group(2))
        if len(parts) < 2:
            continue
        comp = idx2comp.get(i)
        if not comp:
            continue
        ent = pick(parts[0], ENT)
        ind = pick(parts[1], IND)
        if ent or ind:
            got[comp] = {'ent': ent, 'ind': ind}
    return got


def call_model(token, gw_token, items):
    """items: [(i, company, ctx)] -> {company: {ent, ind}}"""
    lines = [f'{i}. {c} —— {ctx}' for i, c, ctx in items]
    prompt = ('给下面每家公司标注两个属性，用于招聘网站的筛选。\n'
              f"企业类型可选（必须原样选一个）：{' / '.join(ENT)}；高校/研究院/实验室/国家实验室归「事业单位」。\n"
              f"行业类别可选（必须原样选一个）：{' / '.join(IND)}\n"
              '只输出「序号|企业类型|行业类别」每行一条，不要解释、不要公司名、不要JSON。\n\n'
              + '\n'.join(lines))
    body = json.dumps({'messages': [{'role': 'user', 'content': prompt}],
                       'max_tokens': 60 * len(items) + 200, 'temperature': 0}).encode()
    url = (f'https://gateway.ai.cloudflare.com/v1/{ACCOUNT_ID}/{GATEWAY}/workers-ai/{MODEL}'
           if GATEWAY else
           f'https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/{MODEL}')
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json',
               'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36'}
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
        return {}
    except Exception:
        return {}
    msg = ((j.get('result') or {}).get('choices') or [{}])[0].get('message', {})
    out = (msg.get('content') or '') or (msg.get('reasoning_content') or '')
    return parse_out(out, {i: c for i, c, _ in items})


def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return default
    return default


def collect_todo(sources):
    """非学姐源、学姐表未收录的公司 -> {公司: 上下文}"""
    summary = set()
    for s in sources:
        if s['name'].startswith('校招汇总'):
            for r in s['rows']:
                k = norm_company(r.get('公司'))
                if k:
                    summary.add(k)
    need = {}
    for s in sources:
        if s['name'].startswith('校招汇总'):
            continue
        for r in s['rows']:
            c = (r.get('公司') or '').strip()
            if not c:
                continue
            k = norm_company(c)
            if k in summary or k in need:
                continue
            ctx = ((r.get('招聘岗位') or '') or (r.get('备注') or ''))[:40].replace('\n', ' ')
            need[c] = ctx
    return need


def main():
    ap = argparse.ArgumentParser(description='AI 推断未收录公司的企业类型/行业类别')
    ap.add_argument('--max', type=int, default=400, help='本次最多处理公司数')
    ap.add_argument('--batch', type=int, default=20, help='每次请求的公司数')
    ap.add_argument('--concurrency', type=int, default=3)
    args = ap.parse_args()

    token = os.environ.get('CF_AI_TOKEN', '').strip() or read_secret('cf_ai_token.txt', 'cf_ai_token.txt.txt')
    if not token:
        print('缺少 CF_AI_TOKEN（或 .secrets/cf_ai_token.txt）')
        return
    gw_token = os.environ.get('CF_AIG_TOKEN', '').strip() or read_secret('gateway_token.txt', 'gateway_token.txt.txt')

    sources = load_json(SRC, [])
    if not sources:
        print('缺少源数据', SRC)
        return
    cache = load_json(CACHE, {})
    need = collect_todo(sources)
    todo = [c for c in need if c not in cache][:args.max]
    print(f'待分类公司 {len(todo)} 家（已缓存 {len(cache)}，批 {args.batch}，模型 {MODEL}）', flush=True)
    if not todo:
        return

    def run(items):
        return call_model(token, gw_token, items)

    remaining = list(todo)
    done = 0
    # 多轮：先整批，返回不全就缩小批大小重试剩下的，最后逐个兜底
    for bs in (args.batch, 8, 3, 1):
        if not remaining:
            break
        chunks = [remaining[i:i + bs] for i in range(0, len(remaining), bs)]
        batch_items = [[(j + 1, c, need.get(c, '')) for j, c in enumerate(ch)] for ch in chunks]
        try:
            with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
                results = list(ex.map(run, batch_items))
        except RuntimeError as e:
            print(f'  停止：{e}', flush=True)
            break
        for ch, res in zip(chunks, results):
            for c, v in res.items():
                if c not in cache:
                    cache[c] = v
                    done += 1
        got = len(remaining) - len([c for c in remaining if c not in cache])
        remaining = [c for c in remaining if c not in cache]
        print(f'  批 {bs}：本轮补 {got} 家，仍缺 {len(remaining)} 家', flush=True)

    cache = {'_说明': 'AI 推断的企业类型/行业类别：公司名 -> {ent, ind}，供学姐表未收录的公司补全', **cache}
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)
    print(f'本次分类 {done} 家，缓存共 {len(cache) - 1} 家 -> {CACHE}', flush=True)


if __name__ == '__main__':
    main()
