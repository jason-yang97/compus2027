#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 fetch_feishu_all.py 的全量导出构建为网页数据 web/data/records.json。

规范化内容：
- 拆分多值字段：工作地点 / 行业类别 / 企业类型 / 学历要求
- 届次提取年份集合 + 特殊届次（海外/往届/不限）
- 批次打标签：秋招/春招/实习/寒假实习/暑假实习/补录/提前批/未标注
- 是否笔试归类：免笔试机会 / 明确有笔试 / 未明确
- 截止时间归一为 ISO 日期（招满为止/尽快投递等保留原文）
- 毫秒时间戳（开始/更新时间）转为日期
- 专业要求/备注剔除表格作者的模板话术（「按照岗位筛选…宝宝~」）
- 每条记录带来源字段 src

用法：python tools/build_web.py [--in recruit/data/feishu_base_all.json]
"""

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, 'web', 'data')

# 飞书日期字段按北京时间（东八区）存取，转换时固定时区，避免依赖运行机器的时区
CST = timezone(timedelta(hours=8))

YEAR_RE = re.compile(r'20\d{2}')
DATE_RES = [
    re.compile(r'(20\d{2})[./-](\d{1,2})[./-](\d{1,2})'),
    re.compile(r'(20\d{2})年(\d{1,2})月(\d{1,2})日?'),
]
FREE_TEST_RE = re.compile(r'免笔试|取消笔试|没有笔试|无常规笔试')
# 表格作者的模板话术（非真实专业要求/备注），整体剔除
BOILER_RE = re.compile(r'按照岗位筛选[^。；;\n]*?(宝宝|必看文档)[^。；;\n]*[~～]?')
# 届次里的特殊选项文本
ROUND_SPECIALS = [('海外', '海外'), ('往届', '往届'), ('不限', '不限')]

# 批次 -> 标签（按出现顺序判断，均基于子串包含）
BATCH_TAGS = [
    ('寒假实习', '寒假实习'),
    ('暑假实习', '暑假实习'),
    ('暑期实习', '暑假实习'),
    ('秋招', '秋招'),
    ('春招', '春招'),
    ('实习', '实习'),
    ('社招', '社招'),
    ('校招', '校招'),
    ('补录', '补录'),
    ('补招', '补录'),
    ('提前批', '提前批'),
]


def split_multi(text):
    return [t.strip() for t in (text or '').split(' / ') if t.strip() and t.strip() != '/']


def split_edu(text):
    """'本科, 硕士, 博士' -> ['本科','硕士','博士']。"""
    return [t.strip() for t in re.split(r'[,，、;；/]', text or '') if t.strip()]


def clean_boiler(text):
    """剔除模板话术，返回清理后的文本。"""
    t = BOILER_RE.sub(' ', text or '')
    return t.strip(' ；;，,/')


def parse_rounds(text):
    """届次 -> (年份列表, 特殊届次标签列表)。"""
    years = sorted({int(y) for y in YEAR_RE.findall(text or '')})
    specials = [tag for key, tag in ROUND_SPECIALS if key in (text or '')]
    return years, specials


def norm_date(text):
    """'2026/10/31'、'2026-5-1'、13位毫秒时间戳 -> ISO 日期，其余返回 ''。"""
    t = (text or '').strip()
    if re.fullmatch(r'1\d{12}', t):
        try:
            return datetime.fromtimestamp(int(t) / 1000, tz=CST).strftime('%Y-%m-%d')
        except (ValueError, OSError):
            return ''
    for rex in DATE_RES:
        m = rex.search(t)
        if m:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            try:
                return date(y, mo, d).isoformat()
            except ValueError:
                return ''
    return ''


def batch_tags(batch, role):
    tags = []
    for key, tag in BATCH_TAGS:
        if key in (batch or '') and tag not in tags:
            tags.append(tag)
    if not tags:
        # 批次为空时从岗位名兜底推断
        if '实习' in (role or ''):
            tags.append('实习')
        else:
            tags.append('未标注')
    return tags


def build_record(r, src):
    company = (r.get('公司') or '').strip()
    role = (r.get('招聘岗位') or '').strip()
    if not company and not role:
        return None
    written = (r.get('是否笔试') or '').strip()
    free = 1 if FREE_TEST_RE.search(written) else 0
    forced = 1 if written == '有笔试' else 0
    years, specials = parse_rounds(r.get('招聘届次'))
    # 无任何届次信息时显式标注「未标注」（届次筛选里也会出现该选项）
    if not years and not specials:
        specials = ['未标注']
    deadline_raw = (r.get('截止时间') or '').strip()
    major_c = clean_boiler(r.get('专业要求'))
    note_c = clean_boiler(r.get('备注'))
    edu = split_edu(r.get('学历要求'))
    # 学历列常见缺「大专」标注：公司/岗位文本明确提到专科或大专时补上（学校类雇主除外）
    if '大专' not in edu:
        hit = re.search(r'大专|专科', f"{role}{major_c}{note_c}")
        if not hit and re.search(r'大专|专科', company) and not re.search(r'学校|学院', company):
            hit = True
        if hit:
            edu.insert(0, '大专')
    rec = {
        'c': company or '（未标注公司）',
        'r': role[:500],
        'city': split_multi(r.get('工作地点')),
        'ind': split_multi(r.get('行业类别')),
        'ent': split_multi(r.get('企业类型')),
        'edu': edu,
        'yrs': years + specials,
        'tags': batch_tags(r.get('批次'), role),
        'batch': (r.get('批次') or '').strip(),
        'free': free,
        'test': forced,
        'written': written[:60],
        'dl': norm_date(deadline_raw),
        'dlRaw': deadline_raw[:30],
        'major': major_c[:500],
        'note': note_c[:300],
        'url': (r.get('简历投递链接') or '').strip(),
        'ann': (r.get('公告链接') or '').strip(),
        'start': norm_date(r.get('开始时间')),
        'upd': norm_date(r.get('更新时间')),
        'src': src,
    }
    return rec


def main():
    parser = argparse.ArgumentParser(description='构建网页数据')
    parser.add_argument('--in', dest='src', default=os.path.join(ROOT, 'recruit', 'data', 'feishu_base_all.json'))
    parser.add_argument('--validate', action='store_true',
                        help='构建前验活飞书系链接，剔除已下架岗位（约 15-20 分钟）')
    args = parser.parse_args()

    # 链接验活：调 validate_feishu_links.py 逐个打开详情页检测下架横幅
    if args.validate:
        import subprocess
        validator = os.path.join(ROOT, 'tools', 'validate_feishu_links.py')
        print('=== 验活飞书系岗位链接 ===', flush=True)
        try:
            subprocess.run([sys.executable, validator, '--in', args.src],
                           timeout=2700, check=False)
        except subprocess.TimeoutExpired:
            print('验活超时，未验活部分保留', flush=True)
        except Exception as e:
            print(f'验活失败（不阻断构建）：{type(e).__name__}: {e}', flush=True)

    link_check = {}
    check_path = os.path.join(OUT_DIR, 'link_check.json')
    if os.path.exists(check_path):
        with open(check_path, encoding='utf-8') as f:
            link_check = json.load(f)

    with open(args.src, encoding='utf-8') as f:
        sources = json.load(f)

    records, dropped, dead = [], 0, 0
    for src in sources:
        for r in src['rows']:
            rec = build_record(r, src['name'])
            if rec is None:
                dropped += 1
                continue
            # 已确认下架（验活 False）的岗位从数据里移除
            if rec['url'] and link_check.get(rec['url']) is False:
                dead += 1
                continue
            records.append(rec)

    # 默认排序：更新时间倒序（无更新时间的排后），同日按公司名
    records.sort(key=lambda x: (x['upd'] or '0000', x['c']), reverse=True)

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, 'records.json')
    payload = {
        'updated': date.today().isoformat(),
        'total': len(records),
        'sources': [{'name': s['name'], 'url': s['url']} for s in sources],
        'records': records,
    }
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, separators=(',', ':'))

    size_mb = os.path.getsize(out_path) / 1048576
    n_free = sum(1 for x in records if x['free'])
    n_2027 = sum(1 for x in records if 2027 in x['yrs'])
    n_2425 = sum(1 for x in records if {2024, 2025} & set(x['yrs']))
    n_yangqi = sum(1 for x in records if '央国企' in x['ent'])
    from collections import Counter
    by_src = Counter(x['src'] for x in records)
    print(f'有效记录 {len(records)} 条（丢弃空行 {dropped}，验活剔除下架 {dead}），输出 {out_path}（{size_mb:.1f} MB）')
    print('来源分布:', dict(by_src))
    print(f'免笔试 {n_free} / 含2027届 {n_2027} / 含24-25届 {n_2425} / 央国企 {n_yangqi}')


if __name__ == '__main__':
    main()
