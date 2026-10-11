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
        'r': role[:40000] if (r.get('岗位来源') == '官网') else role[:500],
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
        'pos': r.get('岗位来源') or '',
        'roles': r.get('官网岗位') or [],
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

    # 内推码（人工维护：公司 -> [{code, note}]）
    codes_path = os.path.join(ROOT, 'recruit', 'data', 'referral_codes.json')
    codes_map = {}
    if os.path.exists(codes_path):
        try:
            with open(codes_path, encoding='utf-8') as f:
                codes_map = json.load(f)
        except Exception:
            codes_map = {}

    def codes_for(company):
        if company in codes_map:
            return codes_map[company]
        for k, v in codes_map.items():
            if len(k) >= 2 and k in company:
                return v
        return []

    # 管理后台导出的隐藏清单（公司||岗位||来源）
    hidden_path = os.path.join(ROOT, 'recruit', 'data', 'hidden.json')
    hidden = set()
    if os.path.exists(hidden_path):
        try:
            with open(hidden_path, encoding='utf-8') as f:
                hidden = set(json.load(f))
        except Exception:
            hidden = set()

    # 工作地点补全：抓取阶段没填上的，从公告正文/视觉读图缓存补齐（按链接匹配）
    loc_caches = []
    for p in (os.path.join(ROOT, 'recruit', 'data', 'article_locations.json'),
              os.path.join(ROOT, 'recruit', 'data', 'vision_locations.json')):
        if os.path.exists(p):
            try:
                with open(p, encoding='utf-8') as f:
                    loc_caches.append(json.load(f))
            except Exception:
                pass

    with open(args.src, encoding='utf-8') as f:
        sources = json.load(f)

    records, dropped, dead = [], 0, 0
    for src in sources:
        for r in src['rows']:
            if not (r.get('工作地点') or '').strip():
                link = (r.get('简历投递链接') or '').strip()
                for cache in loc_caches:
                    if cache.get(link):
                        r['工作地点'] = cache[link]
                        break
            rec = build_record(r, src['name'])
            if rec and codes_map:
                c = codes_for(rec['c'])
                if c:
                    rec['codes'] = c
            if rec and hidden and f"{rec['c']}||{rec['r']}||{rec['src']}" in hidden:
                dropped += 1
                continue
            if rec is None:
                dropped += 1
                continue
            # 已确认下架（验活 false）的岗位从数据里移除
            entry = link_check.get(rec['url'])
            if entry is False or (isinstance(entry, dict) and entry.get('v') is False):
                dead += 1
                continue
            records.append(rec)

    # 去重：GitHub 汇总源的记录，若该公司已被其他源以 2027 届收录则跳过（避免重复）
    def norm_company(name):
        t = re.sub(r'[（(【\[].*?[）)】\]]', '', name or '')
        return re.sub(r'\s+', '', t).lower()

    primary_blob = '|'.join(
        norm_company(r['c']) for r in records
        if not r['src'].startswith('GitHub') and 2027 in r['yrs'])

    # 表头残留/通用词，不参与去重匹配
    GENERIC_NAMES = {'公司', '企业', '岗位', '招聘', '集团', '有限', '科技', '中国', '大学', '学院'}

    def covered_by_primary(name):
        n = norm_company(name)
        # 排除表头残留/通用词；2 字公司名（腾讯/百度等）正常参与匹配
        return bool(n) and n not in GENERIC_NAMES and len(n) >= 2 and n in primary_blob

    before = len(records)
    records = [r for r in records
               if not (r['src'].startswith('GitHub') and r.get('pos') != '官网'
                       and covered_by_primary(r['c']))]
    dedup_dropped = before - len(records)

    # 公告补全：GitHub 等源本身没有公告链接，按公司名从学姐表（几乎每行都有公告）补上
    ann_map = {}
    for s in sources:
        for row in s['rows']:
            a = (row.get('公告链接') or '').strip()
            k = norm_company(row.get('公司'))
            if a and k and k not in ann_map:
                ann_map[k] = a

    # 公司名实体后缀，匹配公告时剥掉（携程旅行 ↔ 携程集团）
    ANN_SUFFIX = re.compile(r'(集团|公司|有限|股份|控股|旅行网|旅行|旅游)+$')

    def ann_core(key):
        return ANN_SUFFIX.sub('', key)

    # 公司别名：源里叫法与学姐表不同（金山软件 → 金山办公）
    alias_path = os.path.join(ROOT, 'recruit', 'data', 'company_aliases.json')
    aliases = {}
    if os.path.exists(alias_path):
        try:
            with open(alias_path, encoding='utf-8') as f:
                aliases = {norm_company(k): norm_company(v)
                           for k, v in json.load(f).items() if not k.startswith('_')}
        except Exception:
            aliases = {}

    def ann_lookup(key):
        if not key:
            return ''
        if key in ann_map:
            return ann_map[key]
        # 剥掉实体后缀后相等（携程旅行 → 携程集团、宇树科技股份有限公司 → 宇树科技）。
        # 不做包含式模糊匹配：避免把 A 公司的公告安到同名的子团队上。
        core = ann_core(key)
        if core and core != key:
            if core in ann_map:
                return ann_map[core]
            for k in ann_map:
                if ann_core(k) == core:
                    return ann_map[k]
        return ''

    def ann_for(company):
        key = norm_company(company)
        if not key:
            return ''
        # 先按原名找，找不到再按别名指向的学姐表公司名找
        return ann_lookup(key) or ann_lookup(aliases.get(key, ''))

    ann_filled = 0
    for rec in records:
        if not rec.get('ann'):
            a = ann_for(rec['c'])
            if a:
                rec['ann'] = a
                ann_filled += 1

    # 默认排序：更新时间倒序（无更新时间的排后），同日按公司名
    records.sort(key=lambda x: (x['upd'] or '0000', x['c']), reverse=True)

    # 「今日新增」基准日：以「开始时间」为准，取数据中最新的一天（不超过构建日）。
    # 学姐表发布与云端构建时间异步，若只认构建当天会漏掉当天稍晚发布的批次，
    # 因此用数据里最新的开始时间作为基准日；官网岗位另用首次抓取日单独判定。
    build_day = date.today().isoformat()
    starts = [r['start'] for r in records if r.get('start') and r['start'] <= build_day]
    new_ref = max(starts) if starts else build_day

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, 'records.json')
    payload = {
        'updated': build_day,
        'newRef': new_ref,
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
    print(f'有效记录 {len(records)} 条（丢弃空行 {dropped}，验活剔除下架 {dead}，去重剔除 {dedup_dropped}），输出 {out_path}（{size_mb:.1f} MB）')
    print('来源分布:', dict(by_src))
    print(f'公告补全 {ann_filled} 条（原本无公告链接，按公司名从学姐表补齐）')
    print(f'免笔试 {n_free} / 含2027届 {n_2027} / 含24-25届 {n_2425} / 央国企 {n_yangqi}')


if __name__ == '__main__':
    main()
