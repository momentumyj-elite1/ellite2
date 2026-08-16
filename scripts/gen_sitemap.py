#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sitemap.xml 자동 생성 스크립트 (표준 라이브러리만 사용)

- 저장소 루트의 모든 .html 파일을 찾아 sitemap.xml 을 다시 씁니다.
- 각 URL 의 lastmod 는 그 파일의 마지막 git 커밋 날짜를 사용합니다.
    · 아직 커밋되지 않은 수정(작업 중)이 있으면 파일 수정시각(mtime)을 씁니다.
      → 페이지를 고친 뒤 '커밋하기 전에' 이 스크립트를 돌리면
        오늘 날짜가 lastmod 로 들어갑니다.
    · git 이력이 아예 없으면 mtime 으로 대체합니다.
- index.html 은 loc 를 도메인 루트("<DOMAIN>/")로 기록합니다.
- priority / changefreq 는 기존 sitemap.xml 값을 그대로 유지하고,
  기존에 없던(새로 추가된) 페이지는 0.7 / monthly 를 기본값으로 씁니다.

사용법:  python scripts/gen_sitemap.py
"""

import os
import re
import sys
import glob
import datetime
import subprocess

# ── 저장소별 설정 (다른 저장소에 넣을 때 이 값만 바꾸면 됩니다) ──
DOMAIN = "https://ellite.co.kr"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITEMAP = os.path.join(ROOT, "sitemap.xml")
DEFAULT_PRIORITY = "0.7"
DEFAULT_CHANGEFREQ = "monthly"


def run_git(args):
    try:
        r = subprocess.run(["git", "-C", ROOT] + args,
                           capture_output=True, text=True, timeout=30)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def loc_to_filename(loc):
    """loc URL → 파일명. 루트('/')는 index.html 로 본다."""
    p = loc.split("://", 1)[-1]
    p = p.split("/", 1)[1] if "/" in p else ""
    p = p.split("#")[0].split("?")[0]
    return p if p else "index.html"


def parse_existing():
    """기존 sitemap.xml 에서 파일명별 (priority, changefreq) 를 읽는다."""
    meta = {}
    if not os.path.exists(SITEMAP):
        return meta
    xml = open(SITEMAP, encoding="utf-8").read()
    for block in re.findall(r"<url>(.*?)</url>", xml, re.S):
        loc = re.search(r"<loc>([^<]+)</loc>", block)
        if not loc:
            continue
        fn = loc_to_filename(loc.group(1).strip())
        pr = re.search(r"<priority>([^<]+)</priority>", block)
        cf = re.search(r"<changefreq>([^<]+)</changefreq>", block)
        meta[fn] = (pr.group(1).strip() if pr else None,
                    cf.group(1).strip() if cf else None)
    return meta


def mtime_date(path):
    return datetime.date.fromtimestamp(os.path.getmtime(path)).isoformat()


def is_dirty(relpath):
    """해당 파일에 커밋되지 않은 변경(수정/미추적)이 있으면 True."""
    out = run_git(["status", "--porcelain", "--", relpath])
    if out is None:      # git 사용 불가
        return False
    return out.strip() != ""


def lastmod_of(fn):
    path = os.path.join(ROOT, fn)
    # 커밋 전 수정 상태면 실제 수정 시각(오늘) 사용
    if is_dirty(fn):
        return mtime_date(path)
    d = run_git(["log", "-1", "--format=%cs", "--", fn])
    if d:                # git 마지막 커밋 날짜
        return d
    return mtime_date(path)   # git 이력 없음 → mtime


def main():
    files = sorted(os.path.basename(p)
                   for p in glob.glob(os.path.join(ROOT, "*.html")))
    if not files:
        print("html 파일이 없습니다:", ROOT)
        return 0

    # index.html 을 맨 앞에 두고 나머지는 알파벳순
    ordered = ([f for f in files if f == "index.html"] +
               [f for f in files if f != "index.html"])

    existing = parse_existing()
    base = DOMAIN.rstrip("/")

    rows = []
    for fn in ordered:
        loc = base + "/" if fn == "index.html" else base + "/" + fn
        pr, cf = existing.get(fn, (None, None))
        rows.append((fn, loc, lastmod_of(fn),
                     cf or DEFAULT_CHANGEFREQ, pr or DEFAULT_PRIORITY))

    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for fn, loc, lm, cf, pr in rows:
        out += ["  <url>",
                "    <loc>%s</loc>" % loc,
                "    <lastmod>%s</lastmod>" % lm,
                "    <changefreq>%s</changefreq>" % cf,
                "    <priority>%s</priority>" % pr,
                "  </url>"]
    out.append("</urlset>")
    open(SITEMAP, "w", encoding="utf-8").write("\n".join(out) + "\n")

    print("sitemap.xml 갱신 완료 — 총 %d개 URL" % len(rows))
    for fn, loc, lm, cf, pr in rows:
        print("  %-30s %s  (%s, %s)" % (fn, lm, cf, pr))
    return 0


if __name__ == "__main__":
    sys.exit(main())
