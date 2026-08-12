#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2주치 데이터를 모아 리포트를 만드는 스크립트 (표준 라이브러리만 사용)

사용법:  python tools/report.py

- data/checks/  : check.py 가 남긴 점검 결과 JSON (YYYY-MM-DD.json)
- data/gsc/     : 서치콘솔 CSV (YYYY-MM-DD-queries.csv, YYYY-MM-DD-pages.csv)
- 결과          : reports/YYYY-MM-DD-report.md 로 저장하고 화면에도 출력
"""

import os
import re
import csv
import sys
import json
import glob
import datetime
import subprocess

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE_NAME = os.path.basename(BASE_DIR)
PERIOD_DAYS = 14

DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


# ── 유틸 ────────────────────────────────────────────────
def git(args):
    """BASE_DIR 에서 git 실행. 실패하면 None 반환."""
    try:
        r = subprocess.run(
            ["git", "-C", BASE_DIR] + args,
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            return None
        return r.stdout
    except Exception:
        return None


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def num(x):
    """'1,234' / '3.5%' / '' 같은 값을 float 로. 실패하면 0."""
    if x is None:
        return 0.0
    s = str(x).strip().replace(",", "").replace("%", "")
    if s == "":
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def fmt_delta(cur, prev, reverse=False, digits=0):
    """증감 표기. reverse=True 면 값이 낮을수록 좋음(순위)."""
    d = cur - prev
    if abs(d) < (0.5 if digits == 0 else 10 ** (-digits) / 2):
        return "±0"
    up = d > 0
    arrow = "▲" if up else "▼"
    if reverse:  # 순위: 숫자가 내려가면 상승
        arrow = "▲" if not up else "▼"
    val = abs(d)
    val = int(round(val)) if digits == 0 else round(val, digits)
    return "%s%s" % (arrow, val)


# ── 1. 점검 결과 ─────────────────────────────────────────
def section_checks():
    out = ["## 1. 점검 결과", ""]
    files = sorted(glob.glob(os.path.join(BASE_DIR, "data", "checks", "*.json")))
    if not files:
        out += ["점검 데이터가 없습니다. 먼저 `python tools/check.py` 를 실행하세요.", ""]
        return "\n".join(out)

    cur = load_json(files[-1])
    cur_total = cur.get("total_problems", 0)
    cur_date = cur.get("date", "?")

    def flatten(doc):
        items = set()
        for sec in doc.get("sections", []):
            for p in sec.get("problems", []):
                items.add((sec.get("no"), sec.get("title", ""),
                           p.get("file"), p.get("detail")))
        return items

    if len(files) < 2:
        out += [
            "- 이번 회차(%s) 문제: **%d건**" % (cur_date, cur_total),
            "- 비교할 지난 회차 데이터가 아직 없습니다. (다음 실행부터 증감 비교)",
            "",
        ]
        cur_set = flatten(cur)
        if cur_set:
            out.append("### 현재 남은 문제")
            for no, title, f, detail in sorted(cur_set, key=lambda x: (x[0] or 0, str(x[2]))):
                out.append("- [%s] %s : %s" % (title, f, detail))
            out.append("")
        return "\n".join(out)

    prev = load_json(files[-2])
    prev_total = prev.get("total_problems", 0)
    prev_date = prev.get("date", "?")
    diff = cur_total - prev_total
    sign = "±0" if diff == 0 else ("+%d" % diff if diff > 0 else "%d" % diff)

    out += [
        "- 이번 회차: **%s** — 문제 **%d건**" % (cur_date, cur_total),
        "- 지난 회차: %s — 문제 %d건" % (prev_date, prev_total),
        "- 증감: **%s건**" % sign,
        "",
    ]

    cur_set = flatten(cur)
    prev_set = flatten(prev)
    new_problems = sorted(cur_set - prev_set, key=lambda x: (x[0] or 0, str(x[2])))
    fixed_problems = sorted(prev_set - cur_set, key=lambda x: (x[0] or 0, str(x[2])))

    out.append("### 새로 생긴 문제")
    if new_problems:
        for no, title, f, detail in new_problems:
            out.append("- [%s] %s : %s" % (title, f, detail))
    else:
        out.append("- 없음")
    out.append("")

    out.append("### 해결된 문제")
    if fixed_problems:
        for no, title, f, detail in fixed_problems:
            out.append("- [%s] %s : %s" % (title, f, detail))
    else:
        out.append("- 없음")
    out.append("")
    return "\n".join(out)


# ── 2. 이번 기간 수정 내역 ───────────────────────────────
def section_commits():
    out = ["## 2. 이번 기간 수정 내역 (최근 %d일)" % PERIOD_DAYS, ""]
    raw = git([
        "log", "--since=%d days ago" % PERIOD_DAYS, "--date=short", "--reverse",
        "--pretty=format:@@@%h\t%ad\t%s", "--numstat",
    ])
    if raw is None:
        out += ["git 정보를 읽을 수 없습니다. (git 저장소가 아니거나 git 미설치)", ""]
        return "\n".join(out)

    commits = []
    cur = None
    for line in raw.splitlines():
        if line.startswith("@@@"):
            if cur:
                commits.append(cur)
            h, ad, subj = (line[3:].split("\t", 2) + ["", "", ""])[:3]
            cur = {"hash": h, "date": ad, "subject": subj, "files": 0}
        elif line.strip() and cur is not None:
            # numstat 줄: added\tdeleted\tpath
            if "\t" in line:
                cur["files"] += 1
    if cur:
        commits.append(cur)

    if not commits:
        out += ["최근 %d일간 커밋이 없습니다." % PERIOD_DAYS, ""]
        return "\n".join(out)

    out.append("| 날짜 | 커밋 | 메시지 | 변경 파일 |")
    out.append("|---|---|---|---|")
    for c in commits:
        out.append("| %s | `%s` | %s | %d개 |" % (c["date"], c["hash"], c["subject"], c["files"]))
    out.append("")
    out.append("- 총 커밋 수: %d개" % len(commits))
    out.append("")
    return "\n".join(out)


# ── 3. 페이지 현황 ───────────────────────────────────────
def section_pages():
    out = ["## 3. 페이지 현황", ""]
    html_files = sorted(os.path.basename(p) for p in glob.glob(os.path.join(BASE_DIR, "*.html")))
    out.append("- 현재 html 파일 수: **%d개**" % len(html_files))

    raw = git([
        "log", "--since=%d days ago" % PERIOD_DAYS, "--diff-filter=A",
        "--name-only", "--pretty=format:",
    ])
    out.append("")
    out.append("### 이번 기간에 새로 추가된 페이지")
    if raw is None:
        out.append("- git 정보를 읽을 수 없어 확인 불가")
        out.append("")
        return "\n".join(out)

    added = []
    for line in raw.splitlines():
        line = line.strip()
        if line.endswith(".html") and "/" not in line and line not in added:
            added.append(line)
    if added:
        for f in sorted(added):
            mark = "" if f in html_files else "  (현재 없음)"
            out.append("- %s%s" % (f, mark))
    else:
        out.append("- 없음")
    out.append("")
    return "\n".join(out)


# ── 4. 검색 순위 (서치콘솔 CSV) ──────────────────────────
def _read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _col(row, *names):
    """헤더 이름(한/영)을 유연하게 매칭."""
    low = {k.strip().lower(): k for k in row.keys()}
    for n in names:
        if n.lower() in low:
            return row[low[n.lower()]]
    return None


def _gsc_rounds(kind):
    """kind='queries' 또는 'pages'. (date, path) 목록을 날짜순 정렬로 반환."""
    files = glob.glob(os.path.join(BASE_DIR, "data", "gsc", "*-%s.csv" % kind))
    rounds = []
    for p in files:
        m = DATE_RE.search(os.path.basename(p))
        if m:
            rounds.append((m.group(1), p))
    rounds.sort()
    return rounds


def section_search():
    out = ["## 4. 검색 순위", ""]
    q_rounds = _gsc_rounds("queries")
    p_rounds = _gsc_rounds("pages")

    if not q_rounds and not p_rounds:
        out += [
            "서치콘솔 CSV가 아직 없습니다. 이 섹션은 건너뜁니다.",
            "",
            "> `data/gsc/` 폴더에 `YYYY-MM-DD-queries.csv`, `YYYY-MM-DD-pages.csv` 를",
            "> 넣으면 다음 리포트부터 검색어 순위·노출·클릭 변화가 자동 정리됩니다.",
            "",
        ]
        return "\n".join(out)

    # 4-1. 검색어 비교
    if q_rounds:
        out.append("### 검색어")
        cur_date, cur_path = q_rounds[-1]

        def parse_queries(path):
            d = {}
            for row in _read_csv(path):
                q = _col(row, "query", "검색어", "queries")
                if not q:
                    continue
                d[q.strip()] = {
                    "clicks": num(_col(row, "clicks", "클릭수", "클릭 수")),
                    "impr": num(_col(row, "impressions", "노출수", "노출 수")),
                    "pos": num(_col(row, "position", "게재순위", "평균 게재순위")),
                }
            return d

        cur = parse_queries(cur_path)
        if len(q_rounds) >= 2:
            prev_date, prev_path = q_rounds[-2]
            prev = parse_queries(prev_path)
            out.append("- 비교: %s ↔ %s" % (prev_date, cur_date))
            out.append("")
            out.append("| 검색어 | 순위 | 노출 | 클릭 | 순위변화 |")
            out.append("|---|---|---|---|---|")
            for q in sorted(cur, key=lambda k: cur[k]["pos"] or 999):
                c = cur[q]
                pv = prev.get(q)
                if pv:
                    ch = fmt_delta(c["pos"], pv["pos"], reverse=True)
                else:
                    ch = "신규"
                out.append("| %s | %.1f | %d | %d | %s |" % (
                    q, c["pos"], int(c["impr"]), int(c["clicks"]), ch))
            out.append("")

            new_q = [q for q in cur if q not in prev]
            gone_q = [q for q in prev if q not in cur]
            up_q, down_q = [], []
            for q in cur:
                if q in prev:
                    d = prev[q]["pos"] - cur[q]["pos"]  # +면 순위 상승
                    if d >= 5:
                        up_q.append((q, d))
                    elif d <= -5:
                        down_q.append((q, -d))

            out.append("**새로 진입한 검색어:** " + (", ".join(sorted(new_q)) if new_q else "없음"))
            out.append("")
            out.append("**사라진 검색어:** " + (", ".join(sorted(gone_q)) if gone_q else "없음"))
            out.append("")
            out.append("**순위 5계단 이상 상승:** " + (
                ", ".join("%s(▲%d)" % (q, int(d)) for q, d in sorted(up_q, key=lambda x: -x[1])) if up_q else "없음"))
            out.append("")
            out.append("**순위 5계단 이상 하락:** " + (
                ", ".join("%s(▼%d)" % (q, int(d)) for q, d in sorted(down_q, key=lambda x: -x[1])) if down_q else "없음"))
            out.append("")
        else:
            out.append("- 회차가 1개뿐이라 변화 비교는 다음 회차부터 가능합니다. (기준: %s)" % cur_date)
            out.append("")
            out.append("| 검색어 | 순위 | 노출 | 클릭 |")
            out.append("|---|---|---|---|")
            for q in sorted(cur, key=lambda k: cur[k]["pos"] or 999):
                c = cur[q]
                out.append("| %s | %.1f | %d | %d |" % (q, c["pos"], int(c["impr"]), int(c["clicks"])))
            out.append("")

    # 4-2. 페이지 상위 10
    if p_rounds:
        out.append("### 페이지 (노출·클릭 상위 10)")
        cur_date, cur_path = p_rounds[-1]
        rows = []
        for row in _read_csv(cur_path):
            pg = _col(row, "page", "페이지", "pages")
            if not pg:
                continue
            rows.append({
                "page": pg.strip(),
                "clicks": num(_col(row, "clicks", "클릭수", "클릭 수")),
                "impr": num(_col(row, "impressions", "노출수", "노출 수")),
            })
        rows.sort(key=lambda r: (r["impr"], r["clicks"]), reverse=True)
        out.append("- 기준: %s" % cur_date)
        out.append("")
        out.append("| 페이지 | 노출 | 클릭 |")
        out.append("|---|---|---|")
        for r in rows[:10]:
            out.append("| %s | %d | %d |" % (r["page"], int(r["impr"]), int(r["clicks"])))
        out.append("")
    return "\n".join(out)


# ── 5. 다음 확인 사항 ────────────────────────────────────
def section_next():
    out = ["## 5. 다음 확인 사항", ""]
    out += [
        "자동 판단이 어려운 항목입니다. 아래를 직접 확인하세요.",
        "",
        "- [ ] 순위 11~20위 검색어 — 1페이지(10위 이내)로 올릴 후보",
        "- [ ] 노출은 있는데 클릭 0인 페이지 — 제목·설명(메타) 점검 대상",
        "- [ ] 4주 이상 노출 0인 페이지 — 내용 보강 대상",
        "",
    ]
    return "\n".join(out)


def main():
    today = datetime.date.today().isoformat()
    parts = [
        "# %s 2주 리포트 (%s)" % (SITE_NAME, today),
        "",
        section_checks(),
        section_commits(),
        section_pages(),
        section_search(),
        section_next(),
    ]
    report = "\n".join(parts).rstrip() + "\n"

    reports_dir = os.path.join(BASE_DIR, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    out_path = os.path.join(reports_dir, "%s-report.md" % today)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)

    # 화면 출력
    print(report)
    print("리포트 저장: %s" % os.path.relpath(out_path, BASE_DIR))
    return 0


if __name__ == "__main__":
    sys.exit(main())
