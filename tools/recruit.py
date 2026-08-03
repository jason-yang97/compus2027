#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""秋招投递追踪 CLI 工具

用法：
  recruit.py add <公司名>             交互式创建公司记录
  recruit.py list [--status S] [--city C] [--priority P]   过滤列表
  recruit.py status <公司名> <新状态>  更新状态并追加时间线
  recruit.py show <公司名>            展示完整记录
  recruit.py search <关键词>          全文搜索
  recruit.py stats                   阶段统计

零第三方依赖，仅使用 Python 标准库。
"""

import argparse
import os
import re
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPANIES_DIR = os.path.join(ROOT, 'recruit', 'companies')
TEMPLATE_FILE = os.path.join(COMPANIES_DIR, '_template.md')

STATUSES = ['待投递', '已投递', '笔试', '面试', 'Offer', '已拒']
TERMINAL_STATUSES = ['Offer', '已拒']
VALID_PRIORITIES = ['高', '中', '低']
VALID_SOURCES = ['官网', '牛客', '内推', '其他']

# 状态流转：旧状态 -> 允许的新状态集合（None 表示任意合法状态）
STATUS_FLOW = {
    '待投递': ['已投递'],
    '已投递': ['笔试', '面试', '已拒'],
    '笔试': ['面试', '已拒'],
    '面试': ['Offer', '已拒'],
    'Offer': [],
    '已拒': [],
}


# ---------- frontmatter 解析 ----------

def parse_frontmatter(content):
    """解析 --- 包裹的 frontmatter，返回 (字段 dict, 正文 str)。

    仅解析 'key: value' 行，跳过注释行（# 开头）。
    """
    if not content.startswith('---'):
        return {}, content
    lines = content.split('\n')
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == '---':
            end = i
            break
    if end is None:
        return {}, content
    fields = {}
    for line in lines[1:end]:
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        if ':' in stripped:
            key, _, value = stripped.partition(':')
            fields[key.strip()] = value.strip()
    body = '\n'.join(lines[end + 1:])
    return fields, body


def serialize_frontmatter(fields):
    """将字段 dict 序列化为 frontmatter 文本（含首尾 ---）。"""
    out = ['---']
    for key, value in fields.items():
        out.append(f'{key}: {value}')
    out.append('---')
    return '\n'.join(out)


def set_field(content, key, value):
    """在 frontmatter 中设置字段，保留文件其余部分不变。

    已存在的 key 就地替换；不存在的 key 追加在第二个 --- 之前。
    """
    lines = content.split('\n')
    if not content.startswith('---'):
        lines = ['---', '', '---'] + lines
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == '---':
            end = i
            break
    if end is None:
        raise ValueError('frontmatter 未闭合')
    replaced = False
    for i in range(1, end):
        stripped = lines[i].strip()
        if stripped.startswith('#'):
            continue
        if ':' in stripped and stripped.partition(':')[0].strip() == key:
            lines[i] = f'{key}: {value}'
            replaced = True
            break
    if not replaced:
        lines.insert(end, f'{key}: {value}')
        end += 1
    return '\n'.join(lines)


def parse_tags(value):
    """解析 '[具身智能, 算法]' 形式为列表；空值返回 []。"""
    if not value:
        return []
    return [t.strip() for t in value.strip('[]').split(',') if t.strip()]


# ---------- 文件操作 ----------

def company_path(name):
    return os.path.join(COMPANIES_DIR, f'{name}.md')


def list_companies():
    """返回 (文件名, 路径) 列表，排除模板与隐藏文件。"""
    if not os.path.isdir(COMPANIES_DIR):
        return []
    result = []
    for fname in sorted(os.listdir(COMPANIES_DIR)):
        if fname.endswith('.md') and not fname.startswith('_'):
            result.append((fname, os.path.join(COMPANIES_DIR, fname)))
    return result


def load_company(name):
    """读取公司记录，返回 (字段 dict, 正文 str, 原始内容 str)。"""
    path = company_path(name)
    if not os.path.isfile(path):
        sys.exit(f'错误：未找到公司记录「{name}」，可用 recruit.py add 创建')
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    fields, body = parse_frontmatter(content)
    return fields, body, content


# ---------- 展示辅助 ----------

def display_width(s):
    return sum(2 if ord(c) > 127 else 1 for c in s)


def pad(s, width):
    return s + ' ' * max(0, width - display_width(s))


def fmt_status(status):
    """状态显示：终态加标记。"""
    if status in TERMINAL_STATUSES:
        return f'{status} (终)'
    return status


# ---------- add ----------

def cmd_add(args):
    name = args.name
    if not re.fullmatch(r'[\w\u4e00-\u9fff\- ]+', name):
        sys.exit('错误：公司名仅支持中文、字母、数字、下划线、连字符和空格')
    path = company_path(name)
    if os.path.exists(path):
        sys.exit(f'错误：公司「{name}」已存在（{path}），可用 status 命令更新状态')

    print(f'正在创建公司记录「{name}」，直接回车使用默认值：')
    city = input(f'  城市（默认：无）: ').strip()
    priority = input(f'  意向度 高/中/低（默认：中）: ').strip() or '中'
    if priority not in VALID_PRIORITIES:
        sys.exit(f'错误：意向度必须为 {"/".join(VALID_PRIORITIES)}')
    today = date.today().isoformat()
    apply_date = input(f'  投递日期（默认：{today}）: ').strip() or today
    deadline = input(f'  截止时间 YYYY-MM-DD（默认：无）: ').strip()
    source = input(f'  信息来源 {" / ".join(VALID_SOURCES)}（默认：无）: ').strip()
    tags = input('  标签，逗号分隔，如 具身智能,算法（默认：具身智能）: ').strip() or '具身智能'
    roles = []
    print('  录入岗位（直接回车结束）：')
    while True:
        role = input('    岗位（格式：名称|城市|链接，城市和链接可省略）: ').strip()
        if not role:
            break
        roles.append(role)

    fields = {
        'company': name,
        'status': '待投递',
        'city': city,
        'priority': priority,
        'apply_date': apply_date,
        'deadline': deadline,
        'source': source,
        'tags': f'[{tags}]',
    }
    body = [f'# {name}', '', '## 岗位', '']
    for r in roles:
        parts = [p.strip() for p in r.split('|')]
        if len(parts) == 1:
            body.append(f'- [ ] {parts[0]}')
        elif len(parts) == 2:
            body.append(f'- [ ] {parts[0]}（{parts[1]}）')
        else:
            body.append(f'- [ ] {parts[0]}（{parts[1]}）— {parts[2]}')
    if not roles:
        body.append('- [ ] 待补充岗位信息')
    body += ['', '## 时间线', '', f'- {today} 创建记录，状态：待投递', '',
             '## 笔试', '', '- 日期：', '- 内容：', '- 结果：', '',
             '## 面试记录', '', '## 备注', '']

    content = serialize_frontmatter(fields) + '\n' + '\n'.join(body)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f'已创建：{path}')


# ---------- list ----------

def cmd_list(args):
    rows = []
    for fname, path in list_companies():
        with open(path, 'r', encoding='utf-8') as f:
            fields, _ = parse_frontmatter(f.read())
        status = fields.get('status', '未知')
        if args.status and status != args.status:
            continue
        if args.city and fields.get('city') != args.city:
            continue
        if args.priority and fields.get('priority') != args.priority:
            continue
        rows.append((fname[:-3], status, fields.get('city', '-'),
                     fields.get('priority', '-'), fields.get('apply_date', '-')))
    if not rows:
        print('（无匹配记录）')
        return
    widths = [max(display_width(r[i]) for r in rows) for i in range(5)]
    widths[0] = max(widths[0], display_width('公司'))
    header = ' | '.join(pad(h, w) for h, w in
                        zip(['公司', '状态', '城市', '意向', '投递日期'], widths))
    print(header)
    print('-' * display_width(header))
    for row in rows:
        print(' | '.join(pad(cell, w) for cell, w in zip(row, widths)))


# ---------- status ----------

def cmd_status(args):
    if args.new_status not in STATUSES:
        sys.exit(f'错误：无效状态「{args.new_status}」，合法值：{" / ".join(STATUSES)}')
    fields, _, content = load_company(args.name)
    old = fields.get('status', '未知')
    if old in TERMINAL_STATUSES:
        print(f'警告：当前状态「{old}」为终态，仍将强制更新为「{args.new_status}」')
    allowed = STATUS_FLOW.get(old, None)
    if allowed and args.new_status not in allowed:
        print(f'提示：状态「{old}」通常流向 {"/".join(allowed)}，已强制更新')

    today = date.today().isoformat()
    content = set_field(content, 'status', args.new_status)
    entry = f'- {today} 状态更新：{old} → {args.new_status}'
    lines = content.split('\n')
    inserted = False
    for i, line in enumerate(lines):
        if line.strip() == '## 时间线':
            lines.insert(i + 1, entry)
            inserted = True
            break
    if not inserted:
        lines += ['', '## 时间线', '', entry]
    content = '\n'.join(lines)
    with open(company_path(args.name), 'w', encoding='utf-8') as f:
        f.write(content)
    print(f'「{args.name}」状态已更新：{old} → {args.new_status}（{today}）')


# ---------- show ----------

def cmd_show(args):
    fields, body, _ = load_company(args.name)
    print(f'# {args.name}  ({fields.get("status", "未知")})')
    print(f'  城市：{fields.get("city", "-")}  意向：{fields.get("priority", "-")}')
    print(f'  投递日期：{fields.get("apply_date", "-")}  截止：{fields.get("deadline", "-")}')
    print(f'  来源：{fields.get("source", "-")}  标签：{fields.get("tags", "-")}')
    print('-' * 50)
    print(body.strip())


# ---------- search ----------

def cmd_search(args):
    keyword = args.keyword
    hits = []
    for fname, path in list_companies():
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        if keyword in fname:
            hits.append((fname[:-3], '文件名'))
        for lineno, line in enumerate(content.split('\n'), 1):
            if keyword in line:
                hits.append((fname[:-3], f'{lineno}: {line.strip()}'))
    if not hits:
        print(f'未找到包含「{keyword}」的内容')
        return
    print(f'命中 {len(hits)} 处：')
    for company, detail in hits:
        print(f'  [{company}] {detail}')


# ---------- stats ----------

def cmd_stats(args):
    counter = {s: 0 for s in STATUSES}
    total = 0
    high_priority = 0
    applied = 0
    for _, path in list_companies():
        with open(path, 'r', encoding='utf-8') as f:
            fields, _ = parse_frontmatter(f.read())
        status = fields.get('status', '未知')
        counter[status] = counter.get(status, 0) + 1
        total += 1
        if fields.get('priority') == '高':
            high_priority += 1
        if status not in ('待投递',):
            applied += 1
    print(f'公司总数：{total}    已投递（含后续阶段）：{applied}    高意向：{high_priority}')
    print('-' * 40)
    print(f'  待投递：{counter["待投递"]}')
    print(f'  已投递：{counter["已投递"]}')
    print(f'  笔试：  {counter["笔试"]}')
    print(f'  面试：  {counter["面试"]}')
    print(f'  Offer： {counter["Offer"]}')
    print(f'  已拒：  {counter["已拒"]}')


# ---------- 入口 ----------

def main():
    parser = argparse.ArgumentParser(
        prog='recruit.py', description='秋招投递追踪工具')
    sub = parser.add_subparsers(dest='command', required=True)

    p_add = sub.add_parser('add', help='交互式创建公司记录')
    p_add.add_argument('name', help='公司名')

    p_list = sub.add_parser('list', help='列出公司记录')
    p_list.add_argument('--status', help='按状态过滤')
    p_list.add_argument('--city', help='按城市过滤')
    p_list.add_argument('--priority', help='按意向度过滤')

    p_status = sub.add_parser('status', help='更新投递状态')
    p_status.add_argument('name', help='公司名')
    p_status.add_argument('new_status', help=f'新状态：{" / ".join(STATUSES)}')

    p_show = sub.add_parser('show', help='展示完整记录')
    p_show.add_argument('name', help='公司名')

    p_search = sub.add_parser('search', help='全文搜索')
    p_search.add_argument('keyword', help='关键词')

    sub.add_parser('stats', help='阶段统计')

    args = parser.parse_args()
    handlers = {
        'add': cmd_add,
        'list': cmd_list,
        'status': cmd_status,
        'show': cmd_show,
        'search': cmd_search,
        'stats': cmd_stats,
    }
    handlers[args.command](args)


if __name__ == '__main__':
    main()
