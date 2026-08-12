#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
사이트 점검 스크립트 (표준 라이브러리만 사용)
- 이 파일이 있는 tools/ 폴더의 상위 폴더에 있는 모든 .html 파일을 검사합니다.
- 사용법:  python tools/check.py
- 실행할 때마다 결과를 data/checks/YYYY-MM-DD.json 으로 저장합니다.
  (화면 출력은 그대로 유지, 같은 날 다시 실행하면 덮어씁니다.)
"""

import os
import re
import sys
import json
import glob
import datetime

# ── 설정 ────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOMAIN = "https://ellite.co.kr"
# 이 사이트의 대표 전화번호
SITE_PHONE = "010-8145-1911"
# 사이트 이름 (폴더 이름을 사용)
SITE_NAME = os.path.basename(BASE_DIR)

# 금지 문구
FORBIDDEN = [
    "최고급", "완벽한", "최상의", "최저가", "최대 규모",
    "비교해보", "추가 비용 없이", "강남 프리미엄",
    "평균 출근", "무료 발렛", "© 2025", "12만원부터",
]

# canonical 이 의도적으로 자기 파일명과 다른 경우 예외 등록
#   예)  "hours.html": "https://ellite-gangnam.com/location.html"
CANONICAL_EXCEPTIONS = {
    # 현재는 모든 페이지가 자기 자신을 canonical 로 사용하므로 비어 있음
}

PHONE_RE = re.compile(r"0\d{1,2}-\d{3,4}-\d{4}")
TAG_RE = re.compile(r"<[^>]+>")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def meta_content(html, key, attr="property"):
    m = re.search(r'<meta\s+%s=["\']%s["\']\s+content=["\']([^"\']*)["\']' % (attr, re.escape(key)), html)
    return m.group(1) if m else None


def canonical_of(html):
    m = re.search(r'<link\s+rel=["\']canonical["\']\s+href=["\']([^"\']*)["\']', html)
    return m.group(1) if m else None


def loc_to_filename(url):
    """sitemap/canonical URL → 파일명. 루트('/')는 index.html 로 본다."""
    path = url.split("://", 1)[-1]
    path = path.split("/", 1)[1] if "/" in path else ""
    path = path.split("#")[0].split("?")[0]
    return path if path else "index.html"


def sentence_of(html, phrase):
    """금지 문구가 들어간 부분의 태그를 제거한 짧은 문장을 반환."""
    idx = html.find(phrase)
    seg = html[max(0, idx - 60): idx + len(phrase) + 60]
    text = TAG_RE.sub("", seg)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def main():
    html_files = sorted(
        os.path.basename(p) for p in glob.glob(os.path.join(BASE_DIR, "*.html"))
    )
    if not html_files:
        print("검사할 html 파일이 없습니다:", BASE_DIR)
        return 0

    docs = {f: read(os.path.join(BASE_DIR, f)) for f in html_files}
    problems = 0

    # 항목별 문제 기록 (JSON 저장용)
    recs = {i: [] for i in range(1, 11)}
    section_titles = {}

    def head(n, title):
        section_titles[n] = title
        print("\n[%d] %s" % (n, title))

    def record(n, file, detail):
        recs[n].append({"file": file, "detail": detail})

    # 1) 금지 문구
    head(1, "금지 문구")
    found = False
    for f in html_files:
        for ph in FORBIDDEN:
            if ph in docs[f]:
                found = True
                problems += 1
                sent = sentence_of(docs[f], ph)
                print("  - %s : \"%s\"  →  …%s…" % (f, ph, sent))
                record(1, f, "\"%s\" → %s" % (ph, sent))
    if not found:
        print("  문제 없음")

    # 2) 전화번호
    head(2, "전화번호 (%s 이 아닌 번호)" % SITE_PHONE)
    found = False
    for f in html_files:
        for num in sorted(set(PHONE_RE.findall(docs[f]))):
            if num != SITE_PHONE:
                found = True
                problems += 1
                print("  - %s : %s" % (f, num))
                record(2, f, num)
    if not found:
        print("  문제 없음")

    # 3) canonical 자기 파일명 일치
    head(3, "canonical 불일치")
    found = False
    for f in html_files:
        can = canonical_of(docs[f])
        if not can:
            found = True; problems += 1
            print("  - %s : canonical 태그 없음" % f)
            record(3, f, "canonical 태그 없음")
            continue
        if f in CANONICAL_EXCEPTIONS:
            if can != CANONICAL_EXCEPTIONS[f]:
                found = True; problems += 1
                print("  - %s : 예외 등록값과 다름 (%s)" % (f, can))
                record(3, f, "예외 등록값과 다름 (%s)" % can)
            continue
        if loc_to_filename(can) != f:
            found = True; problems += 1
            print("  - %s : canonical=%s (자기 파일명과 다름)" % (f, can))
            record(3, f, "canonical=%s (자기 파일명과 다름)" % can)
    if not found:
        print("  문제 없음")

    # 4) og:image vs twitter:image
    head(4, "og:image 와 twitter:image 불일치")
    found = False
    for f in html_files:
        og = meta_content(docs[f], "og:image", "property")
        tw = meta_content(docs[f], "twitter:image", "name")
        if og is not None and tw is not None and og != tw:
            found = True; problems += 1
            print("  - %s : og=%s / twitter=%s" % (f, og, tw))
            record(4, f, "og=%s / twitter=%s" % (og, tw))
    if not found:
        print("  문제 없음")

    # 5) 필수 메타 태그
    head(5, "필수 메타 태그 누락")
    found = False
    for f in html_files:
        h = docs[f]
        missing = []
        if not re.search(r"<title>[^<]+</title>", h): missing.append("title")
        if meta_content(h, "description", "name") is None: missing.append("meta description")
        if canonical_of(h) is None: missing.append("canonical")
        if meta_content(h, "og:title", "property") is None: missing.append("og:title")
        if meta_content(h, "og:description", "property") is None: missing.append("og:description")
        if meta_content(h, "og:image", "property") is None: missing.append("og:image")
        if missing:
            found = True; problems += 1
            print("  - %s : %s" % (f, ", ".join(missing)))
            record(5, f, ", ".join(missing))
    if not found:
        print("  문제 없음")

    # 6) title 중복
    head(6, "title 중복")
    titles = {}
    for f in html_files:
        m = re.search(r"<title>([^<]*)</title>", docs[f])
        if m:
            titles.setdefault(m.group(1).strip(), []).append(f)
    found = False
    for t, fs in titles.items():
        if len(fs) > 1:
            found = True; problems += 1
            print("  - \"%s\" : %s" % (t, ", ".join(fs)))
            record(6, ", ".join(fs), "중복 title: \"%s\"" % t)
    if not found:
        print("  문제 없음")

    # 7) JSON-LD 파싱
    head(7, "JSON-LD 파싱 오류")
    found = False
    for f in html_files:
        for blk in re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', docs[f], re.S):
            try:
                json.loads(blk)
            except Exception as e:
                found = True; problems += 1
                print("  - %s : %s" % (f, e))
                record(7, f, str(e))
    if not found:
        print("  문제 없음")

    # 8) 이미지 alt
    head(8, "img alt 누락/빈값")
    found = False
    for f in html_files:
        for tag in re.findall(r"<img\b[^>]*>", docs[f]):
            m = re.search(r'\balt=["\']([^"\']*)["\']', tag)
            if m is None or m.group(1).strip() == "":
                found = True; problems += 1
                src = re.search(r'\bsrc=["\']([^"\']*)["\']', tag)
                detail = src.group(1) if src else tag[:60]
                print("  - %s : %s" % (f, detail))
                record(8, f, detail)
    if not found:
        print("  문제 없음")

    # 9) 내부 링크 (존재하지 않는 파일)
    head(9, "깨진 내부 링크 (같은 폴더 html)")
    existing = set(html_files)
    found = False
    for f in html_files:
        seen = set()
        for href in re.findall(r'href=["\']([^"\']+)["\']', docs[f]):
            if href.startswith(("http://", "https://", "mailto:", "tel:", "#", "//")):
                continue
            target = href.split("#")[0].split("?")[0].lstrip("/")
            if target.endswith(".html") and target and target not in existing and target not in seen:
                seen.add(target)
                found = True; problems += 1
                print("  - %s → %s (파일 없음)" % (f, target))
                record(9, f, "%s (파일 없음)" % target)
    if not found:
        print("  문제 없음")

    # 10) sitemap.xml 대조
    head(10, "sitemap.xml 대조")
    sm_path = os.path.join(BASE_DIR, "sitemap.xml")
    if not os.path.exists(sm_path):
        problems += 1
        print("  - sitemap.xml 파일이 없습니다")
        record(10, "sitemap.xml", "파일이 없습니다")
    else:
        sm = read(sm_path)
        sm_files = set(loc_to_filename(u) for u in re.findall(r"<loc>([^<]+)</loc>", sm))
        page_files = set(html_files)
        missing_in_sm = sorted(page_files - sm_files)
        missing_files = sorted(sm_files - page_files)
        if not missing_in_sm and not missing_files:
            print("  문제 없음")
        for f in missing_in_sm:
            problems += 1
            print("  - sitemap 에 빠짐: %s" % f)
            record(10, f, "sitemap 에 빠짐")
        for f in missing_files:
            problems += 1
            print("  - sitemap 에 있으나 파일 없음: %s" % f)
            record(10, f, "sitemap 에 있으나 파일 없음")

    print("\n" + "=" * 40)
    print("검사한 html 파일: %d개" % len(html_files))
    print("발견된 문제: %d건" % problems)

    # ── 결과 저장 (data/checks/YYYY-MM-DD.json) ──────────────
    today = datetime.date.today().isoformat()
    checks_dir = os.path.join(BASE_DIR, "data", "checks")
    os.makedirs(checks_dir, exist_ok=True)
    result = {
        "date": today,
        "site": SITE_NAME,
        "html_count": len(html_files),
        "total_problems": problems,
        "sections": [
            {
                "no": n,
                "title": section_titles.get(n, ""),
                "count": len(recs[n]),
                "problems": recs[n],
            }
            for n in range(1, 11)
        ],
    }
    save_path = os.path.join(checks_dir, today + ".json")
    with open(save_path, "w", encoding="utf-8") as fp:
        json.dump(result, fp, ensure_ascii=False, indent=2)
    print("결과 저장: %s" % os.path.relpath(save_path, BASE_DIR))

    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
