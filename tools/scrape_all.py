#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""秋招信息汇总入口：一键运行全部搜集源。

依次执行：
  1. GitHub 汇总源（互联网大厂 + 具身智能社区）   python3 运行
  2. 飞书招聘系统（8 家头部公司结构化岗位）         Playwright 运行
  3. 飞书多维表格汇总表（朱迪学姐 27 届全行业）     Playwright 运行

用法：
  python3 tools/scrape_all.py          # 一键搜集全部
  python3 tools/scrape_all.py --source github   # 只跑指定源（github/feishu/feishu_base）
"""

import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
# venv 解释器位置：Windows 在 Scripts/python.exe，类 Unix 在 bin/python
if os.name == 'nt':
    VENV_PY = os.path.join(ROOT, 'tools', '.venv', 'Scripts', 'python.exe')
else:
    VENV_PY = os.path.join(ROOT, 'tools', '.venv', 'bin', 'python')

SOURCES = {
    'github': ('GitHub 汇总源', [PY, os.path.join(ROOT, 'tools', 'scraper', 'scrape_github.py')]),
    'feishu': ('飞书招聘系统', [VENV_PY, os.path.join(ROOT, 'tools', 'scraper', 'scrape_feishu.py')]),
    'feishu_base': ('飞书汇总表', [VENV_PY, os.path.join(ROOT, 'tools', 'scraper', 'scrape_feishu_base.py')]),
}


def main():
    parser = argparse.ArgumentParser(description='秋招信息汇总入口')
    parser.add_argument('--source', default='', choices=list(SOURCES) + [''],
                        help='只运行指定源，默认运行全部')
    args = parser.parse_args()

    targets = [args.source] if args.source else list(SOURCES)
    print('=' * 56)
    print('秋招信息汇总入口')
    print('=' * 56)
    ok, fail = [], []
    for key in targets:
        name, cmd = SOURCES[key]
        print(f'\n>>> [{name}]')
        try:
            result = subprocess.run(cmd, cwd=ROOT, timeout=900)
            if result.returncode == 0:
                ok.append(name)
            else:
                fail.append(name)
        except subprocess.TimeoutExpired:
            fail.append(name + '（超时）')
        except FileNotFoundError:
            fail.append(name + '（缺少 tools/.venv，请先执行安装）')
    print('\n' + '=' * 56)
    print(f'完成：成功 {len(ok)} 个源，失败 {len(fail)} 个源')
    if ok:
        print('成功:', '、'.join(ok))
    if fail:
        print('失败:', '、'.join(fail))
        sys.exit(1)
    print('候选文件见 recruit/inbox/ 目录')


if __name__ == '__main__':
    main()
