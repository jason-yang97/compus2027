#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全量导出网页数据源（不做方向关键词过滤），供 tools/build_web.py 构建。

默认抓取三类源，输出统一行格式（字段名与飞书表对齐）：
  1. 飞书多维表格汇总表（朱迪学姐27届）          --with-feishu-base
  2. GitHub 秋招汇总仓库（Campus2026 等 3 个）    --with-github
  3. 飞书招聘系统企业岗位（companies.json 8 家）  --with-jobs

用法：
  tools/.venv/Scripts/python tools/scraper/fetch_feishu_all.py
  tools/.venv/Scripts/python tools/scraper/fetch_feishu_all.py --no-jobs
"""

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scrape_feishu_base import (  # noqa: E402
    fetch_clientvars, fetch_records, load_sources, parse_url,
)
from scrape_feishu import fmt_time, fmt_recruit_type  # noqa: E402
from scrape_github import load_config, parse_entries, fetch_raw  # noqa: E402


def fetch_positions_csrf(page, limit, keyword=''):
    """带 CSRF token 分页拉取岗位列表（最多 limit 条，支持关键词）。"""
    import urllib.parse
    kw = urllib.parse.quote(keyword)
    collected = {}
    offset = 0
    total = None
    token = fetch_csrf_token(page)
    while len(collected) < limit and (total is None or offset < (total or 0)):
        size = min(200, limit - len(collected))
        js = """async (args) => {
          const r = await fetch('/api/v1/search/job/posts?keyword=' + args.kw
            + '&limit=' + args.size + '&offset=' + args.offset
            + '&job_category_id_list=&tag_id_list=&location_code_list='
            + '&subject_id_list=&recruitment_id_list=&portal_type=6'
            + '&job_function_id_list=&storefront_id_list=&portal_entrance=1', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'x-csrf-token': args.token},
            body: JSON.stringify({keyword: args.kwRaw, limit: args.size, offset: args.offset,
              job_category_id_list: [], tag_id_list: [], location_code_list: [],
              subject_id_list: [], recruitment_id_list: []})
          });
          const j = await r.json();
          return j.data ? j.data : {error: 'http ' + r.status};
        }"""
        try:
            data = page.evaluate(js, {'kw': kw, 'kwRaw': keyword, 'size': size,
                                      'offset': offset, 'token': token})
        except Exception:
            token = fetch_csrf_token(page)
            continue
        if not data or data.get('error') or not data.get('job_post_list'):
            break
        total = data.get('count') or total
        for x in data['job_post_list']:
            collected[x.get('id')] = x
        offset += size
    return {'count': total or len(collected), 'job_post_list': list(collected.values())}

OUT_DEFAULT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'recruit', 'data', 'feishu_base_all.json')
GITHUB_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sources.json')
COMPANIES_JSON = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'recruit', 'data', 'companies.json')
# 已见岗位记录：url -> 首次收录日期（随仓库同步，保证跨天不重置日期）
SEEN_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'recruit', 'data', 'feishu_seen.json')
# 公告正文提取的城市缓存：url -> 城市文本（随仓库同步，避免每天重复抓文章）
LOC_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'recruit', 'data', 'article_locations.json')
# 视觉模型读图提取的城市缓存：url -> 城市文本（由 tools/vision_locations.py 生成）
VISION_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'recruit', 'data', 'vision_locations.json')

# 城市/地区词表（用于从公告正文提取工作地点）
CITY_WORDS = [
    '北京', '上海', '广州', '深圳', '天津', '重庆', '杭州', '南京', '苏州', '无锡', '常州', '南通',
    '徐州', '扬州', '盐城', '泰州', '镇江', '宿迁', '连云港', '淮安',
    '宁波', '温州', '嘉兴', '绍兴', '台州', '金华', '湖州', '衢州', '丽水', '舟山',
    '合肥', '芜湖', '蚌埠', '马鞍山', '安庆', '滁州',
    '福州', '厦门', '泉州', '漳州', '莆田', '宁德', '龙岩', '三明', '南平',
    '南昌', '赣州', '九江', '上饶', '宜春', '吉安',
    '济南', '青岛', '烟台', '潍坊', '临沂', '淄博', '济宁', '泰安', '威海', '日照', '东营', '滨州', '德州', '聊城', '菏泽', '枣庄',
    '郑州', '洛阳', '南阳', '新乡', '许昌', '焦作', '安阳', '平顶山', '信阳', '商丘', '周口', '开封', '濮阳', '漯河', '三门峡',
    '武汉', '宜昌', '襄阳', '荆州', '黄石', '十堰', '孝感', '荆门', '黄冈', '咸宁', '随州',
    '长沙', '株洲', '湘潭', '衡阳', '岳阳', '常德', '郴州', '邵阳', '益阳', '永州', '怀化', '娄底', '张家界',
    '成都', '绵阳', '德阳', '宜宾', '南充', '泸州', '自贡', '乐山', '内江', '眉山', '达州', '遂宁', '广元', '攀枝花',
    '贵阳', '遵义', '六盘水', '安顺', '毕节',
    '昆明', '曲靖', '玉溪', '大理', '丽江',
    '西安', '咸阳', '宝鸡', '渭南', '榆林', '延安', '汉中', '安康',
    '兰州', '天水', '酒泉', '嘉峪关',
    '西宁', '银川', '乌鲁木齐', '克拉玛依', '拉萨',
    '沈阳', '大连', '鞍山', '抚顺', '本溪', '丹东', '锦州', '营口', '盘锦', '葫芦岛',
    '长春', '吉林', '四平', '通化', '松原',
    '哈尔滨', '齐齐哈尔', '大庆', '牡丹江', '佳木斯',
    '石家庄', '唐山', '保定', '廊坊', '沧州', '邯郸', '邢台', '秦皇岛', '张家口', '承德', '衡水',
    '太原', '大同', '临汾', '运城', '长治', '晋中', '阳泉', '晋城',
    '呼和浩特', '包头', '鄂尔多斯', '赤峰',
    '南宁', '柳州', '桂林', '北海', '玉林', '梧州',
    '海口', '三亚', '儋州',
    '香港', '澳门', '台湾', '台北', '新竹', '台中', '台南', '高雄',
    '东莞', '佛山', '珠海', '中山', '惠州', '江门', '肇庆', '汕头', '湛江', '茂名', '揭阳', '潮州', '梅州', '清远', '韶关', '阳江', '河源', '云浮', '汕尾',
    '新加坡', '东京', '首尔', '硅谷', '西雅图', '圣何塞', '纽约', '伦敦', '慕尼黑', '巴黎', '迪拜', '曼谷', '吉隆坡', '雅加达', '海外',
    '全国', '多地',
]


def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return default
    return default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)


def fetch_article_text(url):
    """抓取公告网页正文纯文本（公众号文章等）。"""
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/120.0 Safari/537.36'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode('utf-8', errors='replace')
        html = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', html, flags=re.S | re.I)
        text = re.sub(r'<[^>]+>', ' ', html)
        return re.sub(r'\s+', ' ', text)
    except Exception:
        return ''


def extract_cities(text):
    """从文本中提取城市名（按出现顺序去重，最多 6 个）。"""
    hits = []
    for c in CITY_WORDS:
        if c in text and c not in hits:
            hits.append(c)
    return ' / '.join(hits[:6])


def github_sources():
    """GitHub 汇总源 -> [{name,url,rows}]。"""
    sources = []
    for src in load_config(GITHUB_CONFIG).get('github_sources', []):
        print(f'抓取 GitHub 源 {src["name"]}（{src["repo"]}）...', flush=True)
        content = fetch_raw(src['repo'], src.get('branch', ''), src.get('readme', 'README.md'))
        if content is None:
            print('  [跳过] 抓取失败')
            continue
        entries = parse_entries(content)
        rows = []
        for company, title, link, update, note, _kind in entries:
            # 届次/批次从标题与备注文本提取（备注里常写「27届校招」「实习」等）
            rounds, _edu = extract_rounds_degrees(f'{title} {note}')
            rt = f'{title} {note}'
            batch = '实习' if '实习' in rt else ('校招' if '校招' in rt else ('社招' if '社招' in rt else ''))
            rows.append({
                '公司': company[:80],
                '招聘岗位': title[:200],
                # 表格里的地点常被并进备注，先从文本提取，空的话后面抓公告正文补
                '工作地点': extract_cities(f'{title} {note}'),
                '招聘届次': rounds,
                '截止时间': '',
                '简历投递链接': link if link.startswith('http') else '',
                '是否笔试': '',
                '备注': note[:200],
                '学历要求': '', '专业要求': '', '企业类型': '', '行业类别': '',
                '批次': batch,
                # 汇总源没有岗位发布日，文章日期即起点：开始时间 = 更新时间
                '开始时间': update,
                '更新时间': update,
            })
        print(f'  解析 {len(rows)} 条')
        sources.append({'name': f'GitHub·{src["name"]}', 'url': src.get('homepage', ''), 'rows': rows})
    # 工作地点补全：抓公告正文提取城市（带缓存，只抓没抓过的文章）
    loc_cache = load_json(LOC_CACHE_PATH, {})
    todo = [r for r in (row for s in sources for row in s['rows'])
            if not r['工作地点'] and r['简历投递链接'].startswith('http')
            and r['简历投递链接'] not in loc_cache]
    if todo:
        print(f'  抓取 {len(todo)} 篇公告正文提取工作地点...', flush=True)
        def work(row):
            loc_cache[row['简历投递链接']] = extract_cities(fetch_article_text(row['简历投递链接']))
        with ThreadPoolExecutor(max_workers=8) as ex:
            list(ex.map(work, todo))
    vision_cache = load_json(VISION_CACHE_PATH, {})
    for s in sources:
        for r in s['rows']:
            if not r['工作地点']:
                link = r['简历投递链接']
                # 优先正文提取结果，其次视觉模型读图结果
                r['工作地点'] = loc_cache.get(link, '') or vision_cache.get(link, '')
    save_json(LOC_CACHE_PATH, loc_cache)
    filled = sum(1 for s in sources for r in s['rows'] if r['工作地点'])
    print(f'  工作地点补全：{filled} 条有地点', flush=True)
    return sources


DEGREE_ORDER = ['大专', '本科', '硕士', '博士']
DEGREE_RE = re.compile(r'(大专|专科|本科|学士|硕士|研究生|博士)')
# 接口配置 degree_required 代码 -> 可投递学历（保留最低门槛 + 展开"及以上"的更高学历）
DEGREE_REQ_MAP = {
    20: ['不限', '大专', '本科', '硕士', '博士'],            # 不限
    8: ['博士'],                                          # 博士及以上
    7: ['硕士', '博士'],                                   # 硕士及以上
    6: ['本科', '硕士', '博士'],                            # 本科及以上
    5: ['大专', '本科', '硕士', '博士'],                     # 大专及以上
    4: ['高中', '大专', '本科', '硕士', '博士'],             # 高中及以上
    3: ['中专', '高中', '大专', '本科', '硕士', '博士'],      # 专职及以上
    2: ['初中', '高中', '大专', '本科', '硕士', '博士'],      # 初中及以上
    1: ['小学', '初中', '高中', '大专', '本科', '硕士', '博士'],  # 小学及以上
}


def degree_from_required(code):
    """结构化字段 required_degree -> 学历文本（找不到代码则返回空）。"""
    lst = DEGREE_REQ_MAP.get(code)
    return ' , '.join(lst) if lst else ''


def extract_rounds_degrees(desc):
    """从职位描述提取届次与学历要求的文本（飞书列表接口不返回这两个结构化字段）。"""
    text = desc or ''
    years = []
    for m in re.finditer(r'(20\d{2})\s*届', text):
        y = int(m.group(1))
        if y not in years:
            years.append(y)
    for m in re.finditer(r'(?<!\d)(\d{2})\s*届', text):
        y = 2000 + int(m.group(1))
        if 2020 <= y <= 2035 and y not in years:
            years.append(y)
    parts = [f'{y}届' for y in sorted(years)]
    if '往届' in text:
        parts.append('往届')
    elif re.search(r'不限届|届数不限|届次不限', text):
        parts.append('不限届')
    rounds = ' / '.join(dict.fromkeys(parts))  # 去重保序

    found = set()
    for m in DEGREE_RE.finditer(text):
        d = m.group(1)
        d = {'专科': '大专', '学士': '本科', '研究生': '硕士'}.get(d, d)
        found.add(d)
    if found:
        # 「本科及以上」类表述：向上补全到博士
        if re.search(r'(大专|专科|本科|学士|硕士|研究生|博士)\s*及(以上|相当)', text):
            top = max(DEGREE_ORDER.index(d) for d in found)
            found = set(DEGREE_ORDER[top:])
        edu = ' , '.join(d for d in DEGREE_ORDER if d in found)
    else:
        edu = ''
    return rounds, edu


def fetch_csrf_token(page):
    """获取当前站点的 CSRF token（详情接口用），失败返回空串。"""
    js = """async () => {
      const tk = await fetch('/api/v1/csrf/token', {method: 'POST',
        headers: {'Content-Type': 'application/json'}, body: '{}'});
      const j = await tk.json();
      return (j.data && j.data.token) || '';
    }"""
    for _ in range(2):
        try:
            return page.evaluate(js)
        except Exception:
            page.wait_for_timeout(2000)
    return ''


def fetch_job_detail(page, pid, token):
    """单个岗位详情（列表摘要的 requirement 与详情页不一致，届次只在详情里）。

    必须带 portal_type 参数：缺省上下文里 channel_online_status 恒为 1，
    无法用于验活。
    """
    js = """async (args) => {
      const r = await fetch('/api/v1/job/posts/' + args.pid + '?portal_type=6&with_recommend=false',
        {headers: {'x-csrf-token': args.token}});
      if (!r.ok) return null;
      const j = await r.json();
      return j.data ? j.data.job_post_detail : null;
    }"""
    try:
        return page.evaluate(js, {'pid': pid, 'token': token})
    except Exception:
        return None


# 飞书招聘系统企业的基础属性（企业类型, 行业类别）——表中仅此 8 家，直接标注
FEISHU_ORG_META = {
    'aicarrier': ('事业单位', '人工智能'),
    'xiaopeng': ('民企', '汽车制造/维修/零配件'),
    'k0fqxcszc9': ('民企', '机器人/智能制造'),
    'x2-robot': ('民企', '机器人/智能制造'),
    'nio': ('民企', '汽车制造/维修/零配件'),
    'agirobot': ('民企', '机器人/智能制造'),
    'owm6ymi5v9b': ('民企', '机器人/智能制造'),
    'mammotion': ('民企', '机器人/智能制造'),
}


def feishu_job_rows(page, limit):
    """飞书招聘系统企业全量岗位 -> 统一行格式。

    每家企业：先按默认排序分页抓 limit 条，再用关键词「实习」补搜
    （实习帖可能排在列表深处），之后只对实习/校招/未标注且缺届次的
    岗位调详情接口补届次与学历。
    """
    with open(COMPANIES_JSON, encoding='utf-8') as f:
        companies = [c for c in json.load(f)['companies']
                     if c.get('recruit_system') == 'feishu' and c.get('org')]
    rows = []
    today = date.today().isoformat()
    seen = load_json(SEEN_PATH, {})
    for c in companies:
        org, name = c['org'], c['name']
        ent, ind = FEISHU_ORG_META.get(org, ('民企', ''))
        try:
            page.goto(f'https://{org}.jobs.feishu.cn/', timeout=30000, wait_until='domcontentloaded')
            page.wait_for_timeout(4000)
            posts_map = {}
            for x in (fetch_positions_csrf(page, limit).get('job_post_list') or []):
                posts_map[x.get('id')] = x
            kw_count = 0
            for x in (fetch_positions_csrf(page, limit, keyword='实习').get('job_post_list') or []):
                if x.get('id') not in posts_map:
                    posts_map[x.get('id')] = x
                    kw_count += 1
        except Exception:
            # 单家企业失败自动重试一次（云端偶发超时/风控）
            try:
                page.wait_for_timeout(3000)
                page.goto(f'https://{org}.jobs.feishu.cn/', timeout=30000, wait_until='domcontentloaded')
                page.wait_for_timeout(5000)
                posts_map = {}
                for x in (fetch_positions_csrf(page, limit).get('job_post_list') or []):
                    posts_map[x.get('id')] = x
                kw_count = 0
                for x in (fetch_positions_csrf(page, limit, keyword='实习').get('job_post_list') or []):
                    if x.get('id') not in posts_map:
                        posts_map[x.get('id')] = x
                        kw_count += 1
            except Exception as e:
                print(f'  [跳过] {name}({org}): {type(e).__name__}', flush=True)
                continue
        posts = list(posts_map.values())
        print(f'  {name}({org}): {len(posts)} 岗位（关键词补捞 {kw_count}）', flush=True)
        token = None
        detail_used = 0
        offline_dropped = 0
        fail_streak = 0
        rows_in_org = []
        for p in posts:
            title = (p.get('title') or '')[:200]
            post_url = f'https://{org}.jobs.feishu.cn/index/position/{p.get("id")}/detail'
            first_seen = seen.setdefault(post_url, today)   # 老岗位保留首次收录日，新岗位记今天
            rtype = fmt_recruit_type(p)
            cat = (p.get('job_category') or {}).get('name', '')
            city = ' / '.join(
                (ct or {}).get('name', '') for ct in (p.get('city_list') or []) if (ct or {}).get('name'))
            # 批次按岗位类型归类：实习 > 校招 > 社招（含标题关键词）
            rt_all = f'{title} {rtype} {cat}'
            batch = '实习' if '实习' in rt_all else ('校招' if '校招' in rt_all else ('社招' if '社招' in rt_all else ''))
            # 届次/学历藏在职位描述与职位要求里（列表接口不返回结构化字段）
            full_desc = (p.get('description') or '') + '\n' + (p.get('requirement') or '')
            rounds, edu = extract_rounds_degrees(full_desc)
            # 学历优先用结构化字段（页面头部标签「本科及以上」即此字段）
            edu_struct = degree_from_required((p.get('job_post_info') or {}).get('required_degree'))
            if edu_struct:
                edu = edu_struct
            # 非社招且列表摘要没写届次的，调详情接口补全（详情页的要求文本与摘要不同）
            if batch in ('实习', '校招', '未标注', '') and not rounds and p.get('id') and fail_streak < 5:
                if not token:
                    token = fetch_csrf_token(page)
                d = fetch_job_detail(page, p['id'], token)
                if d is None:
                    token = fetch_csrf_token(page)
                    d = fetch_job_detail(page, p['id'], token)
                if d:
                    fail_streak = 0
                    detail_used += 1
                    d_text = (d.get('description') or '') + '\n' + (d.get('requirement') or '')
                    d_rounds, d_edu = extract_rounds_degrees(d_text)
                    if d_rounds:
                        rounds = d_rounds
                    if d_edu and not edu:
                        edu = d_edu
                else:
                    fail_streak += 1
            rows_in_org.append({
                '公司': name,
                '招聘岗位': title,
                '工作地点': city,
                '招聘届次': rounds,
                '截止时间': '尽快投递',
                # 直链详情页；链接是否有效由 validate_feishu_links.py 每日验活
                '简历投递链接': post_url,
                '是否笔试': '',
                '备注': ' / '.join(x for x in (rtype, cat) if x)[:200],
                '学历要求': edu, '专业要求': '', '企业类型': ent, '行业类别': ind,
                '批次': batch,
                # 开始时间=岗位发布/开始招聘日期；更新时间=首次收录日期（不被每天抓取覆盖）
                '开始时间': fmt_time(p.get('publish_time')) or first_seen,
                '更新时间': first_seen,
            })
        rows.extend(rows_in_org)
        print(f'    其中调详情接口补届次 {detail_used} 个', flush=True)
    save_json(SEEN_PATH, seen)
    # 同公司同岗位名的兄弟帖（不同城市/批次分开挂）共享届次与学历
    groups = {}
    for r in rows:
        groups.setdefault((r['公司'], r['招聘岗位']), []).append(r)
    for group in groups.values():
        donor = next((r for r in group if r['招聘届次']), None)
        if donor:
            for r in group:
                if not r['招聘届次']:
                    r['招聘届次'] = donor['招聘届次']
                if not r['学历要求']:
                    r['学历要求'] = donor['学历要求']
    return rows


def humanize(value, option_map):
    """把值中的选项 ID 替换为选项文本；其余文本原样返回。"""
    if not value:
        return ''
    tokens = value.split()
    if tokens and all(t in option_map for t in tokens):
        return ' / '.join(option_map[t] for t in tokens)
    return value


def cell_with_url(full):
    """单元格 [{type,text,link}] -> (文本, 首个链接 URL)。"""
    if not full:
        return '', ''
    v = full.get('value')
    if not isinstance(v, list):
        return (str(v), '') if isinstance(v, (str, int, float)) else ('', '')
    parts, url = [], ''
    for seg in v:
        if isinstance(seg, dict):
            parts.append(seg.get('text') or '')
            if not url:
                link = seg.get('link') or seg.get('url') or seg.get('href') or ''
                if isinstance(link, dict):
                    link = link.get('url') or link.get('link') or ''
                if link and link.startswith('http'):
                    url = link
        else:
            parts.append(str(seg))
    return ' '.join(p for p in parts if p), url


def main():
    parser = argparse.ArgumentParser(description='全量导出网页数据源')
    parser.add_argument('--sources', default='', help='仅跑指定飞书汇总表源名（逗号分隔）')
    parser.add_argument('--out', default=OUT_DEFAULT, help='输出 JSON 路径')
    parser.add_argument('--no-base', action='store_true', help='跳过飞书汇总表')
    parser.add_argument('--no-github', action='store_true', help='跳过 GitHub 汇总源')
    parser.add_argument('--no-jobs', action='store_true', help='跳过飞书招聘系统岗位')
    parser.add_argument('--limit', type=int, default=500, help='飞书招聘每企业岗位数上限')
    args = parser.parse_args()

    result = []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit('缺少 playwright：请执行 tools/.venv/Scripts/pip install playwright')

    with sync_playwright() as p:
        # 飞书站点国内直连最快：给浏览器进程剔除代理环境变量
        clean_env = {k: v for k, v in os.environ.items() if not k.lower().endswith('_proxy')}
        browser = p.chromium.launch(channel='chrome', headless=True, env=clean_env)
        page = browser.new_page(viewport={'width': 1280, 'height': 800})

        if not args.no_base:
            sources = load_sources()
            if args.sources:
                wanted = set(args.sources.split(','))
                sources = [s for s in sources if s['name'] in wanted]
            if not sources:
                print('[跳过] sources.json 未配置 feishu_base_sources')
            for src in sources:
                name = src['name']
                info = parse_url(src['url'])
                print(f'抓取 {name}（{info["app"]}）...', flush=True)
                try:
                    page.goto(src['url'], timeout=60000, wait_until='domcontentloaded')
                    page.wait_for_timeout(12000)
                    field_map, option_map = fetch_clientvars(page, info['app'], info['table'], info['view'])
                    records = fetch_records(page, info['app'], info['table'], info['view'])
                except Exception as e:
                    print(f'  [跳过] {name}: {type(e).__name__}: {e}')
                    continue

                rows = []
                for rec in records.values():
                    row = {}
                    for fid, fname in field_map.items():
                        if fname in row:
                            continue
                        text, url = cell_with_url(rec.get(fid))
                        text = humanize(text, option_map)
                        if '链接' in fname:
                            row[fname] = url or (text if text.startswith('http') else '')
                        else:
                            row[fname] = text
                    rows.append(row)
                print(f'  记录 {len(rows)} 条')
                result.append({'name': name, 'url': src['url'], 'rows': rows})

        if not args.no_jobs:
            print('抓取飞书招聘系统企业岗位...', flush=True)
            try:
                result.append({'name': '飞书招聘系统', 'url': '',
                               'rows': feishu_job_rows(page, args.limit)})
            except Exception as e:
                print(f'  [失败] 飞书招聘系统: {type(e).__name__}: {e}', flush=True)

        browser.close()

    if not args.no_github:
        result.extend(github_sources())

    result = [s for s in result if s['rows']]
    if not result:
        sys.exit('未抓到任何数据')
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False)
    total = sum(len(r['rows']) for r in result)
    names = '、'.join(f"{r['name']}({len(r['rows'])})" for r in result)
    print(f'完成：共 {total} 条 [{names}] -> {args.out}')


if __name__ == '__main__':
    main()
