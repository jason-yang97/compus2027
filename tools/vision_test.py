#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""云端视觉模型测试：用 Gemini（或 OpenRouter 的千问）读取招聘图片中的城市信息。

结果写入 vision_test_result.json（由工作流提交回仓库便于查看）。
环境变量：
  GEMINI_KEY      Google AI Studio API Key（优先）
  OPENROUTER_KEY  OpenRouter API Key（可选，用千问视觉模型）
"""

import base64
import json
import os
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'vision_test_result.json')

PROMPT = ('这是中国公司的招聘公告图片。请只根据图中实际印出的文字，找出招聘公司名和工作城市；'
          '如果图中没有文字或文字里没有城市，回答"无城市信息"。用一句话回答，不要推测。')

# 测试图（含已知真值：第 3 张为福田实验室海报，应读出深圳；其余为装饰图/信息图待核）
IMAGES = [
    'https://mmbiz.qpic.cn/mmbiz_gif/LxHWFgFR93m82eoQVTL9nAwOp3J2f8d9zOd8tN5eJZTV8kicViablEpDzxnFBWouhIw80icicQphMYM5E7mZqVvR',
    'https://mmbiz.qpic.cn/mmbiz_png/eFGr89o5sVraU2avGsachMPRZIgghsvChJRkYCQdP7v9CFxYuayVGO9miaDicwWVGBFhIY3Il8M8NQnhsfyWuJvt',
    'https://mmbiz.qpic.cn/mmbiz_png/icm0ZXWeiadqXBEUkfusDOfHhzuHUj6NdYuibcymoyg9kW7Vy4fEVMaMxu0AibaxYqwAFRxicGLjZLWz2SKNoTmV',
    'https://mmbiz.qpic.cn/mmbiz_gif/LxHWFgFR93mAvTCqo55xIFDqwibnplNnTTEnhSOPBicAYpolI0aYeZibTCUkD6NibWia4Q2wF8wGrNGkue0sPvyk',
    'https://mmbiz.qpic.cn/mmbiz_png/x7v6BzInlZK9vDykRKzfjdl1GAY1wFDS06EQVchbSMo4Pa0EQ1KMFQmvHcDgJRRibibG3uhicFUhrzUsILicp641',
]
GEMINI_MODELS = ['gemini-2.5-flash', 'gemini-flash-latest', 'gemini-2.0-flash-001']
OPENROUTER_MODEL = 'qwen/qwen2.5-vl-72b-instruct'


def download(url):
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36',
        'Referer': 'https://mp.weixin.qq.com/'})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def call_gemini(key, data):
    body = json.dumps({'contents': [{'parts': [
        {'text': PROMPT},
        {'inline_data': {'mime_type': 'image/jpeg', 'data': base64.b64encode(data).decode()}}]}]}).encode()
    last = ''
    for model in GEMINI_MODELS:
        url = f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}'
        req = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                j = json.loads(resp.read().decode('utf-8', errors='replace'))
            return f'[{model}] ' + j['candidates'][0]['content']['parts'][0]['text'].strip().replace('\n', ' ')
        except urllib.error.HTTPError as e:
            last = f'HTTP {e.code}: {e.read().decode("utf-8", errors="replace")[:150]}'
        except Exception as e:
            last = type(e).__name__
    return f'<失败 {last}>'


def call_openrouter(key, data):
    body = json.dumps({'model': OPENROUTER_MODEL, 'messages': [{'role': 'user', 'content': [
        {'type': 'text', 'text': PROMPT},
        {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + base64.b64encode(data).decode()}}]}]}).encode()
    req = urllib.request.Request('https://openrouter.ai/api/v1/chat/completions', data=body,
                                 headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            j = json.loads(resp.read().decode('utf-8', errors='replace'))
        return f'[{OPENROUTER_MODEL}] ' + j['choices'][0]['message']['content'].strip().replace('\n', ' ')
    except urllib.error.HTTPError as e:
        return f'<失败 HTTP {e.code}: {e.read().decode("utf-8", errors="replace")[:150]}>'
    except Exception as e:
        return f'<失败 {type(e).__name__}>'


def main():
    gk = os.environ.get('GEMINI_KEY', '').strip()
    ok = os.environ.get('OPENROUTER_KEY', '').strip()
    if not gk and not ok:
        print('未配置 GEMINI_KEY 或 OPENROUTER_KEY')
        return
    results = {'gemini': {}, 'openrouter': {}}
    for url in IMAGES:
        try:
            data = download(url)
        except Exception as e:
            results['gemini'][url] = f'<下载失败 {type(e).__name__}>'
            continue
        if gk:
            results['gemini'][url] = call_gemini(gk, data)
        if ok:
            results['openrouter'][url] = call_openrouter(ok, data)
        print(f'{url[-40:]}: {results["gemini"].get(url, results["openrouter"].get(url))}'[:200], flush=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    print('结果写入', OUT)


if __name__ == '__main__':
    main()
