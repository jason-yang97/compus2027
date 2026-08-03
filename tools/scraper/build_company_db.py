#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建企业招聘入口库：从候选文件与汇总源自动提取企业并分类。

输出 recruit/data/companies.json：
{
  "generated_at": "YYYY-MM-DD",
  "companies": [
    {"name": "智元机器人", "recruit_system": "feishu", "org": "agirobot",
     "url": "https://agirobot.jobs.feishu.cn/", "source": "自动提取"},
    ...
  ]
}

招聘系统分类（按链接域名）：
  feishu  -> *.jobs.feishu.cn      一个适配器批量抓取
  moka    -> *.mokahr.com
  zhiye   -> *.zhiye.com           智联招聘系统
  beisen  -> talent.*.com          北森
  website -> 自研官网/其他         链接监控模式
  unknown -> 未发现招聘链接        待补充

用法：
  python3 tools/scraper/build_company_db.py [--out recruit/data/companies.json]
"""

import argparse
import json
import os
import re
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INBOX_DIR = os.path.join(ROOT, 'recruit', 'inbox')
DEFAULT_OUT = os.path.join(ROOT, 'recruit', 'data', 'companies.json')
SOURCES_JSON = os.path.join(ROOT, 'tools', 'scraper', 'sources.json')

# 招聘系统识别规则（含 org 提取正则）
SYSTEM_RULES = [
    ('feishu', r'https?://([a-z0-9-]+)\.jobs\.feishu\.cn', None),
    ('moka', r'https?://[a-z0-9-]+\.mokahr\.com',
     r'(?:campus_apply|campus-recruitment|su)/([a-z0-9_-]+)'),
    ('zhiye', r'https?://([a-z0-9-]+)\.zhiye\.com', None),
    ('beisen', r'https?://talent\.([a-z0-9-]+)\.com', None),
]
LINK_RE = re.compile(r'\]\((https?://[^)\s]+)\)')
# 结构化价值：飞书/Moka/智联/北森 优于 官网/公众号
SYSTEM_ORDER = {'feishu': 4, 'moka': 3, 'zhiye': 3, 'beisen': 3, 'website': 1}


def system_score(url):
    for system, pat, _ in SYSTEM_RULES:
        if re.search(pat, url):
            return SYSTEM_ORDER[system]
    return 1


def merge_entry(raw, name, url):
    """合并企业条目：同名时保留结构化价值更高的链接。"""
    if not url:
        return
    if name not in raw or system_score(url) > system_score(raw[name]):
        raw[name] = url


def classify(url):
    """按链接域名返回 (recruit_system, org)。"""
    for system, pat, org_pat in SYSTEM_RULES:
        m = re.search(pat, url)
        if m:
            org = m.group(1) if m.lastindex else ''
            if org_pat:
                mo = re.search(org_pat, url)
                if mo:
                    org = mo.group(1)
            return system, org
    return 'website', ''


def extract_from_candidates():
    """从 inbox 候选文件提取 {公司名: 链接}。"""
    raw = {}
    if not os.path.isdir(INBOX_DIR):
        return raw
    for fname in sorted(os.listdir(INBOX_DIR)):
        if not fname.endswith('_candidates.md'):
            continue
        path = os.path.join(INBOX_DIR, fname)
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.startswith('| '):
                    continue
                cells = [c.strip() for c in line.strip('|').split('|')]
                if len(cells) < 5 or cells[0] in ('公司', '公司名'):
                    continue
                name = cells[0]
                m = LINK_RE.search(cells[1]) if len(cells) > 1 else None
                url = m.group(1) if m else ''
                merge_entry(raw, name, url)
    return raw


def extract_from_campus2026():
    """从 Campus2026 汇总源 README 提取 {公司名: 链接}。"""
    import urllib.request
    raw = {}
    url = 'https://raw.githubusercontent.com/namewyf/Campus2026/master/README.md'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'recruit-scraper/1.0'})
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read().decode('utf-8', errors='replace')
    except Exception:
        print('警告：Campus2026 README 抓取失败，跳过该源')
        return raw
    for line in content.split('\n'):
        line = line.strip()
        if not line.startswith('|'):
            continue
        cells = [c.strip() for c in line.strip('|').split('|')]
        if len(cells) < 2:
            continue
        name = cells[0]
        if re.fullmatch(r'[-:\s]+', name) or name == '公司':
            continue
        m = LINK_RE.search(cells[1])
        url = m.group(1) if m else ''
        merge_entry(raw, name, url)
    return raw


def main():
    parser = argparse.ArgumentParser(description='构建企业招聘入口库')
    parser.add_argument('--out', default=DEFAULT_OUT, help='输出 JSON 路径')
    args = parser.parse_args()

    raw = {}
    raw.update(extract_from_candidates())
    raw.update(extract_from_campus2026())

    # 关注公司名单补入，无链接的标记待补充
    with open(SOURCES_JSON, 'r', encoding='utf-8') as f:
        config = json.load(f)
    for wc in config.get('watch_companies', []):
        raw.setdefault(wc, '')

    companies = []
    for name, url in sorted(raw.items()):
        if not url:
            companies.append({'name': name, 'recruit_system': 'unknown',
                              'org': '', 'url': '', 'source': '关注名单'})
            continue
        system, org = classify(url)
        companies.append({'name': name, 'recruit_system': system,
                          'org': org, 'url': url, 'source': '自动提取'})

    out_dir = os.path.dirname(args.out)
    os.makedirs(out_dir, exist_ok=True)
    payload = {'generated_at': date.today().isoformat(), 'companies': companies}
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    by_sys = {}
    for c in companies:
        by_sys[c['recruit_system']] = by_sys.get(c['recruit_system'], 0) + 1
    print(f'企业总数: {len(companies)}')
    for system, count in sorted(by_sys.items(), key=lambda x: -x[1]):
        print(f'  {system:8s} {count}')
    print(f'已写入: {args.out}')


if __name__ == '__main__':
    main()
