#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2주치 데이터를 모아 리포트를 만드는 스크립트 (표준 라이브러리만 사용)

사용법:  python tools/report.py

입력:
- data/checks/ : check.py 가 남긴 점검 결과 JSON (YYYY-MM-DD.json)
- data/gsc/    : 서치콘솔 CSV (YYYY-MM-DD-queries.csv, YYYY-MM-DD-pages.csv)
- data/todos/  : 지난 회차에 저장한 '다음 2주 할 일' (YYYY-MM-DD.json)

출력:
- reports/YYYY-MM-DD-report.md      : 전체 리포트(마크다운)
- reports/YYYY-MM-DD-summary.html   : 프린트용 A4 요약본 (흑백 인쇄 대응)
- data/todos/YYYY-MM-DD.json         : 이번 회차에 뽑은 '다음 2주 할 일'
                                       (다음 회차 자동 채점용)
"""

import os
import re
import csv
import sys
import json
import glob
import html
import datetime
import subprocess

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE_NAME = os.path.basename(BASE_DIR)
PERIOD_DAYS = 14

DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
TITLE_RE = re.compile(r"<title>([^<]*)</title>")


# ── 공통 유틸 ────────────────────────────────────────────
def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def git(args):
    try:
        r = subprocess.run(["git", "-C", BASE_DIR] + args,
                           capture_output=True, text=True, timeout=30)
        return r.stdout if r.returncode == 0 else None
    except Exception:
        return None


def num(x):
    if x is None:
        return 0.0
    s = str(x).strip().replace(",", "").replace("%", "")
    if s == "":
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def date_of(path):
    m = DATE_RE.search(os.path.basename(path))
    return m.group(1) if m else None


def days_between(a, b):
    return (datetime.date.fromisoformat(a) - datetime.date.fromisoformat(b)).days


def page_to_filename(url):
    """서치콘솔 페이지 URL → html 파일명."""
    u = url.strip().split("#")[0].split("?")[0]
    path = u.split("://", 1)[-1]
    path = path.split("/", 1)[1] if "/" in path else ""
    if path == "" or path.endswith("/"):
        return "index.html"
    return path.rsplit("/", 1)[-1]


def page_title(fname):
    if not fname:
        return None
    p = os.path.join(BASE_DIR, fname)
    if not os.path.exists(p):
        return None
    m = TITLE_RE.search(read(p))
    return m.group(1).strip() if m else None


# ── 점검(check) 데이터 ───────────────────────────────────
def checks_rounds():
    files = sorted(glob.glob(os.path.join(BASE_DIR, "data", "checks", "*.json")))
    out = []
    for p in files:
        try:
            out.append((date_of(p), load_json(p)))
        except Exception:
            pass
    return out


def problems_of(doc):
    out = []
    for sec in doc.get("sections", []):
        for pr in sec.get("problems", []):
            out.append((sec.get("no"), sec.get("title", ""),
                        pr.get("file"), pr.get("detail")))
    return out


# ── 서치콘솔(GSC) 데이터 ─────────────────────────────────
def _read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _col(row, *names):
    low = {k.strip().lower(): k for k in row.keys()}
    for n in names:
        if n.lower() in low:
            return row[low[n.lower()]]
    return None


def gsc_query_rounds():
    files = glob.glob(os.path.join(BASE_DIR, "data", "gsc", "*-queries.csv"))
    rounds = []
    for p in sorted(files):
        d = date_of(p)
        if not d:
            continue
        table = {}
        for row in _read_csv(p):
            q = _col(row, "query", "검색어", "queries")
            if not q:
                continue
            table[q.strip()] = {
                "clicks": num(_col(row, "clicks", "클릭수", "클릭 수")),
                "impr": num(_col(row, "impressions", "노출수", "노출 수")),
                "pos": num(_col(row, "position", "게재순위", "평균 게재순위")),
            }
        rounds.append((d, table))
    rounds.sort(key=lambda x: x[0])
    return rounds


def gsc_page_rounds():
    files = glob.glob(os.path.join(BASE_DIR, "data", "gsc", "*-pages.csv"))
    rounds = []
    for p in sorted(files):
        d = date_of(p)
        if not d:
            continue
        table = {}
        for row in _read_csv(p):
            pg = _col(row, "page", "페이지", "pages")
            if not pg:
                continue
            fn = page_to_filename(pg)
            table[fn] = {
                "url": pg.strip(),
                "clicks": num(_col(row, "clicks", "클릭수", "클릭 수")),
                "impr": num(_col(row, "impressions", "노출수", "노출 수")),
                "pos": num(_col(row, "position", "게재순위", "평균 게재순위")),
            }
        rounds.append((d, table))
    rounds.sort(key=lambda x: x[0])
    return rounds


# ── 할 일(todos) 데이터 ──────────────────────────────────
def todos_rounds():
    files = sorted(glob.glob(os.path.join(BASE_DIR, "data", "todos", "*.json")))
    out = []
    for p in files:
        try:
            out.append((date_of(p), load_json(p)))
        except Exception:
            pass
    return out


def score_todo(item):
    """지난 회차 할 일 1건의 처리 여부를 자동 판정.
    반환: 'done' | 'undone' | 'manual'"""
    chk = item.get("check", {}) or {}
    method = chk.get("method", "manual")
    target = item.get("target_file")
    if method == "contains":
        if not target:
            return "manual"
        p = os.path.join(BASE_DIR, target)
        if not os.path.exists(p):
            return "manual"
        present = chk.get("string", "") in read(p)
        expect = chk.get("expect", "present")
        done = present if expect == "present" else (not present)
        return "done" if done else "undone"
    if method == "title_changed":
        if not target:
            return "manual"
        cur = page_title(target)
        if cur is None:
            return "manual"
        return "done" if cur != chk.get("baseline") else "undone"
    return "manual"


def effect_of(item, cur_pages):
    """완료 항목의 효과 판정 — 저장해 둔 '당시' 노출을 기준으로 현재와 비교."""
    tf = item.get("target_file")
    base = item.get("impressions")
    if not tf or base is None or not cur_pages:
        return "데이터 없음", None
    cm = cur_pages.get(tf)
    if not cm:
        return "데이터 없음", None
    b_clicks = item.get("clicks")
    b_pos = item.get("position")
    detail = "노출 %d → %d, 클릭 %s → %d, 순위 %s → %.1f" % (
        int(base), int(cm["impr"]),
        (str(int(b_clicks)) if b_clicks is not None else "-"), int(cm["clicks"]),
        (("%.1f" % b_pos) if b_pos is not None else "-"), cm["pos"])
    if cm["impr"] > base:
        return "효과 있음", detail
    if cm["impr"] < base:
        return "재검토 필요", detail
    return "지켜보는 중", detail


def how_to_check(check):
    """확인 방법을 사람이 읽을 수 있는 한 줄로."""
    m = (check or {}).get("method")
    if m == "contains":
        s = check.get("string", "")
        if check.get("expect") == "absent":
            return "대상 파일에서 '%s' 문자열이 사라졌으면 완료" % s
        return "대상 파일에 '%s' 문자열이 들어갔으면 완료" % s
    if m == "title_changed":
        return "대상 파일의 <title> 이 이전과 달라졌으면 완료"
    return "자동 판별 불가 — 수동 확인"


# ── 다음 2주 할 일 자동 추출 ─────────────────────────────
def make_todo(title, why, evidence, target_file, check,
              impressions=None, clicks=None, position=None):
    """할 일 1건을 표준 형태로. 노출·클릭·순위와 확인 방법을 함께 기록."""
    return {
        "title": title,                 # 무엇을 해야 하는지
        "target_file": target_file,     # 대상 파일명
        "why": why,                     # 왜 필요한지 (한 줄)
        "evidence": evidence,           # 화면 표시용 근거 문구
        "impressions": impressions,     # 당시 노출수
        "clicks": clicks,               # 당시 클릭수
        "position": position,           # 당시 평균 순위
        "check": check,                 # 확인 방법 (자동 채점용)
        "how_to_check": how_to_check(check),  # 확인 방법 (사람이 읽는 설명)
    }


def build_todos(cur_problems, cur_q, cur_p, prev_p, has_gsc):
    todos = []

    # 우선순위 1: 점검에서 나온 문제
    for no, title, f, detail in cur_problems:
        if no == 1:  # 금지 문구
            m = re.search(r'"([^"]+)"', detail or "")
            phrase = m.group(1) if m else None
            if f and phrase:
                todos.append(make_todo(
                    "%s 에서 금지 문구 '%s' 제거" % (f, phrase),
                    "과장·금지 문구는 신뢰도와 노출에 악영향",
                    "점검 1번 지적", f,
                    {"method": "contains", "string": phrase, "expect": "absent"}))
                continue
        if no == 5:  # 필수 메타 누락
            tag = (detail or "").split(",")[0].strip()
            tagmap = {"title": "<title>", "meta description": 'name="description"',
                      "canonical": 'rel="canonical"', "og:title": 'property="og:title"',
                      "og:description": 'property="og:description"',
                      "og:image": 'property="og:image"'}
            needle = tagmap.get(tag)
            if f and needle:
                todos.append(make_todo(
                    "%s 메타 태그 보완 (%s)" % (f, detail),
                    "필수 메타가 없으면 검색결과 노출·클릭이 떨어짐",
                    "점검 5번 지적", f,
                    {"method": "contains", "string": needle, "expect": "present"}))
                continue
        todos.append(make_todo(
            "%s : %s 처리" % (f, detail),
            "점검에서 발견된 문제 — 방치 시 품질·노출 저하",
            "점검 %d번 지적" % (no or 0), f, {"method": "manual"}))

    # 우선순위 2: 노출 20+ 클릭 0 페이지 → 순위 구간별로 판정
    #   1~10위=제목·설명 문제 / 11~30위=순위 올리기 / 31위+=판단 불가(제외)
    for fn, m in sorted(cur_p.items(), key=lambda kv: -kv[1]["impr"]):
        if m["impr"] >= 20 and m["clicks"] == 0:
            pos = m["pos"]
            if pos <= 10:
                t_title = "%s 제목·설명 개선" % fn
                t_why = "1~10위인데 클릭 0 — 제목/설명이 클릭을 못 만듦 (고치면 바로 효과)"
            elif pos <= 30:
                t_title = "%s 순위 올리기 (콘텐츠 보강)" % fn
                t_why = "노출은 있으나 순위 11~30위라 클릭이 안 나옴 — 순위부터 올려야 함"
            else:
                continue  # 31위 이상은 순위가 낮아 판단 불가 → 제외
            todos.append(make_todo(
                t_title, t_why,
                "노출 %d · 클릭 0 · 순위 %.1f" % (int(m["impr"]), pos), fn,
                {"method": "title_changed", "baseline": page_title(fn) or ""},
                impressions=int(m["impr"]), clicks=int(m["clicks"]),
                position=round(pos, 1)))

    # 우선순위 3: 순위 11~20위 검색어 → 1페이지 진입
    for q, m in sorted(cur_q.items(), key=lambda kv: kv[1]["pos"]):
        if 10 < m["pos"] <= 20:
            todos.append(make_todo(
                "'%s' 검색어 강화" % q,
                "11~20위 — 조금만 개선하면 1페이지(10위 이내) 진입 가능",
                "순위 %.1f, 노출 %d" % (m["pos"], int(m["impr"])), None,
                {"method": "manual"},
                impressions=int(m["impr"]), clicks=int(m["clicks"]),
                position=round(m["pos"], 1)))

    # 우선순위 4: 노출 30% 이상 감소 페이지
    for fn, cm in cur_p.items():
        pm = prev_p.get(fn)
        if pm and pm["impr"] > 0:
            drop = (pm["impr"] - cm["impr"]) / pm["impr"]
            if drop >= 0.30:
                todos.append(make_todo(
                    "%s 노출 급감 원인 점검" % fn,
                    "노출이 크게 줄면 색인·콘텐츠·경쟁 변화 신호",
                    "노출 %d → %d (-%d%%)" % (int(pm["impr"]), int(cm["impr"]), int(drop * 100)),
                    fn, {"method": "title_changed", "baseline": page_title(fn) or ""},
                    impressions=int(cm["impr"]), clicks=int(cm["clicks"]),
                    position=round(cm["pos"], 1)))

    # 데이터가 없어 아무것도 못 뽑은 경우: 데이터 확보를 첫 할 일로
    if not todos and not has_gsc:
        todos.append(make_todo(
            "data/gsc/ 에 서치콘솔 CSV 넣기",
            "순위·클릭 데이터가 있어야 개선 우선순위를 자동으로 뽑을 수 있음",
            "현재 GSC 데이터 0건", None, {"method": "manual"}))

    return todos[:5]


# ── 마크다운 리포트 (기존) ───────────────────────────────
def md_section_checks(rounds):
    out = ["## 1. 점검 결과", ""]
    if not rounds:
        out += ["점검 데이터가 없습니다. 먼저 `python tools/check.py` 를 실행하세요.", ""]
        return "\n".join(out)
    cur_d, cur = rounds[-1]
    cur_total = cur.get("total_problems", 0)
    if len(rounds) < 2:
        out += ["- 이번 회차(%s) 문제: **%d건**" % (cur_d, cur_total),
                "- 비교할 지난 회차 데이터가 아직 없습니다. (다음 실행부터 증감 비교)", ""]
        return "\n".join(out)
    prev_d, prev = rounds[-2]
    diff = cur_total - prev.get("total_problems", 0)
    sign = "±0" if diff == 0 else ("+%d" % diff if diff > 0 else "%d" % diff)
    cur_set = set(problems_of(cur)); prev_set = set(problems_of(prev))
    out += ["- 이번 회차: **%s** — 문제 **%d건**" % (cur_d, cur_total),
            "- 지난 회차: %s — 문제 %d건" % (prev_d, prev.get("total_problems", 0)),
            "- 증감: **%s건**" % sign, ""]
    new = sorted(cur_set - prev_set, key=lambda x: (x[0] or 0, str(x[2])))
    fixed = sorted(prev_set - cur_set, key=lambda x: (x[0] or 0, str(x[2])))
    out.append("### 새로 생긴 문제")
    out += (["- [%s] %s : %s" % (t, f, d) for _, t, f, d in new] or ["- 없음"])
    out.append("")
    out.append("### 해결된 문제")
    out += (["- [%s] %s : %s" % (t, f, d) for _, t, f, d in fixed] or ["- 없음"])
    out.append("")
    return "\n".join(out)


def md_section_commits():
    out = ["## 2. 이번 기간 수정 내역 (최근 %d일)" % PERIOD_DAYS, ""]
    raw = git(["log", "--since=%d days ago" % PERIOD_DAYS, "--date=short", "--reverse",
               "--pretty=format:@@@%h\t%ad\t%s", "--numstat"])
    if raw is None:
        return "\n".join(out + ["git 정보를 읽을 수 없습니다.", ""])
    commits, cur = [], None
    for line in raw.splitlines():
        if line.startswith("@@@"):
            if cur:
                commits.append(cur)
            h, ad, subj = (line[3:].split("\t", 2) + ["", "", ""])[:3]
            cur = {"hash": h, "date": ad, "subject": subj, "files": 0}
        elif line.strip() and cur is not None and "\t" in line:
            cur["files"] += 1
    if cur:
        commits.append(cur)
    if not commits:
        return "\n".join(out + ["최근 %d일간 커밋이 없습니다." % PERIOD_DAYS, ""])
    out.append("| 날짜 | 커밋 | 메시지 | 변경 파일 |")
    out.append("|---|---|---|---|")
    for c in commits:
        out.append("| %s | `%s` | %s | %d개 |" % (c["date"], c["hash"], c["subject"], c["files"]))
    out += ["", "- 총 커밋 수: %d개" % len(commits), ""]
    return "\n".join(out)


def md_section_pages():
    out = ["## 3. 페이지 현황", ""]
    html_files = sorted(os.path.basename(p) for p in glob.glob(os.path.join(BASE_DIR, "*.html")))
    out.append("- 현재 html 파일 수: **%d개**" % len(html_files))
    raw = git(["log", "--since=%d days ago" % PERIOD_DAYS, "--diff-filter=A",
               "--name-only", "--pretty=format:"])
    out += ["", "### 이번 기간에 새로 추가된 페이지"]
    if raw is None:
        return "\n".join(out + ["- git 정보를 읽을 수 없어 확인 불가", ""])
    added = []
    for line in raw.splitlines():
        line = line.strip()
        if line.endswith(".html") and "/" not in line and line not in added:
            added.append(line)
    out += (["- %s" % f for f in sorted(added)] or ["- 없음"])
    out.append("")
    return "\n".join(out)


def md_section_search(q_rounds, p_rounds):
    out = ["## 4. 검색 순위", ""]
    if not q_rounds and not p_rounds:
        out += ["서치콘솔 CSV가 아직 없습니다. 이 섹션은 건너뜁니다.", "",
                "> `data/gsc/` 폴더에 `YYYY-MM-DD-queries.csv`, `YYYY-MM-DD-pages.csv` 를",
                "> 넣으면 다음 리포트부터 자동 정리됩니다.", ""]
        return "\n".join(out)
    if q_rounds:
        cur_d, cur = q_rounds[-1]
        out.append("### 검색어 (기준 %s)" % cur_d)
        out.append("")
        out.append("| 검색어 | 순위 | 노출 | 클릭 |")
        out.append("|---|---|---|---|")
        for q in sorted(cur, key=lambda k: cur[k]["pos"] or 999):
            c = cur[q]
            out.append("| %s | %.1f | %d | %d |" % (q, c["pos"], int(c["impr"]), int(c["clicks"])))
        out.append("")
    if p_rounds:
        cur_d, cur = p_rounds[-1]
        rows = sorted(cur.values(), key=lambda r: (r["impr"], r["clicks"]), reverse=True)
        out += ["### 페이지 노출·클릭 상위 10 (기준 %s)" % cur_d, "",
                "| 페이지 | 노출 | 클릭 |", "|---|---|---|"]
        for r in rows[:10]:
            out.append("| %s | %d | %d |" % (r["url"], int(r["impr"]), int(r["clicks"])))
        out.append("")
    return "\n".join(out)


# ── 프린트용 요약본 HTML ─────────────────────────────────
CSS = """
@page { size: A4 portrait; margin: 12mm 10mm; }
@media print { @page { @top-right { content: "p." counter(page) " / " counter(pages); font-size: 8pt; color: #777; } } }
* { box-sizing: border-box; }
body { font-family: 'Malgun Gothic','맑은 고딕','Apple SD Gothic Neo',sans-serif;
       font-size: 10pt; line-height: 1.25; color: #000; margin: 0; }
h1 { font-size: 14pt; margin: 0 0 1mm; }
h1 .date { font-weight: normal; color: #555; font-size: 10pt; }
.sub { color: #555; font-size: 8pt; margin: 0 0 3mm; }
h2 { font-size: 12pt; margin: 5mm 0 1.5mm; padding-bottom: 1mm; border-bottom: 1.2pt solid #000; break-after: avoid; }
h2:first-of-type { margin-top: 2mm; }
p { margin: 1mm 0; }
ul { margin: 1mm 0 2mm; padding-left: 5mm; }
li { margin: 0.4mm 0; }
.why { color: #444; font-size: 8pt; }
.muted { color: #666; }
.note { color: #555; font-size: 8.5pt; margin: 0.5mm 0; }
table { width: 100%; border-collapse: collapse; margin: 1.5mm 0; font-size: 9pt; }
th, td { padding: 2px 6px; text-align: left; border: none; border-bottom: 0.5pt solid #bbb; vertical-align: top; }
thead th { border-bottom: 1pt solid #000; font-weight: 600; }
tr { break-inside: avoid; }
.num { text-align: right; white-space: nowrap; }
.tag { display: inline-block; padding: 0 3px; font-size: 7.5pt; border: 0.7pt solid #000; }
.tag.strong { font-weight: bold; border-width: 1.4pt; }
.tag.mid { font-style: italic; }
.tag.weak { color: #666; border-color: #999; }
.blank { display: inline-block; min-width: 100px; border-bottom: 0.5pt solid #999; }
.chk { font-size: 11pt; }
small { font-size: 8pt; }
.cols { display: flex; gap: 7mm; align-items: flex-start; }
.cols > .col { flex: 1; min-width: 0; break-inside: avoid; }
.col h3 { font-size: 10pt; margin: 0 0 1mm; padding-bottom: 0.6mm; border-bottom: 0.7pt solid #888; }
.page-break { break-after: page; page-break-after: always; height: 0; overflow: hidden; }
.ref-head { font-size: 8.5pt; color: #555; letter-spacing: .08em; margin: 0 0 2mm; }
.run-header, .run-footer { display: none; }
@media print {
  .run-header, .run-footer { display: block; position: fixed; left: 10mm; right: 10mm; font-size: 8pt; color: #555; }
  .run-header { top: 5mm; }
  .run-header .r { float: right; }
  .run-footer { bottom: 5mm; text-align: right; }
}
"""


def esc(s):
    return html.escape(str(s if s is not None else ""))


def h_prev_actions(prev_todos, cur_p, prev_p):
    parts = ["<h2>지난 회차 조치 결과</h2>"]
    if not prev_todos:
        parts.append('<p class="note">직전 회차 할 일 기록이 없습니다. 이번 회차부터 기록을 시작합니다.</p>')
        return "".join(parts)
    d, doc = prev_todos
    items = doc.get("items", [])
    if not items:
        parts.append('<p class="note">직전 회차(%s)에 등록된 할 일이 없습니다.</p>' % esc(d))
        return "".join(parts)
    parts.append('<p class="note">직전 회차 기준: %s</p>' % esc(d))
    done_rows, undone_rows, manual_rows = [], [], []
    for it in items:
        st = score_todo(it)
        title = esc(it.get("title"))
        if st == "done":
            label, detail = effect_of(it, cur_p)
            cls = {"효과 있음": "tag", "지켜보는 중": "tag mid",
                   "재검토 필요": "tag strong", "데이터 없음": "tag weak"}.get(label, "tag weak")
            done_rows.append(
                "<tr><td>%s</td><td><span class='%s'>%s</span></td><td><small>%s</small></td></tr>"
                % (title, cls, esc(label), esc(detail or "노출 데이터 없음")))
        elif st == "undone":
            undone_rows.append(
                "<tr><td>%s</td><td class='muted'>미처리</td><td>사유: <span class='blank'>&nbsp;</span></td></tr>"
                % title)
        else:
            manual_rows.append(
                "<tr><td>%s</td><td class='muted'>수동 확인 필요</td><td><span class='blank'>&nbsp;</span></td></tr>"
                % title)
    parts.append("<table><tr><th>항목</th><th>상태·효과</th><th>변화 / 메모</th></tr>")
    parts.append("".join(done_rows + undone_rows + manual_rows))
    parts.append("</table>")
    parts.append('<p class="note">효과 기준: 노출 증가=효과 있음, 변화 없음=지켜보는 중, 노출 감소=재검토 필요.</p>')
    return "".join(parts)


def h_this_round(html_count, problem_count, commit_count, cur_q):
    parts = ["<h2>이번 회차 요약</h2><ul>"]
    parts.append("<li>페이지 <b>%d개</b> — 사이트 전체 규모 <span class='why'>(콘텐츠 자산 수)</span></li>" % html_count)
    parts.append("<li>점검 문제 <b>%d건</b> — 지금 손봐야 할 오류 <span class='why'>(0에 가까울수록 좋음)</span></li>" % problem_count)
    parts.append("<li>최근 2주 커밋 <b>%d개</b> — 실제 작업량 <span class='why'>(개선 활동 빈도)</span></li>" % commit_count)
    if cur_q:
        impr = sum(m["impr"] for m in cur_q.values())
        clk = sum(m["clicks"] for m in cur_q.values())
        ctr = (clk / impr * 100) if impr else 0.0
        avgpos = (sum(m["pos"] * m["impr"] for m in cur_q.values()) / impr) if impr else 0.0
        parts.append("<li>검색 노출 <b>%d</b> · 클릭 <b>%d</b> · CTR <b>%.1f%%</b> · 평균순위 <b>%.1f</b> <span class='why'>(이번 회차 GSC 검색어 합계)</span></li>"
                     % (int(impr), int(clk), ctr, avgpos))
        parts.append("<li>순위 잡힌 검색어 <b>%d개</b> <span class='why'>(노출이 한 번이라도 잡힌 쿼리 수)</span></li>" % len(cur_q))
    else:
        parts.append("<li class='muted'>GSC 데이터 없음 — 노출·클릭·CTR·순위 집계 불가</li>")
    parts.append("</ul>")
    return "".join(parts)


def h_rank_change(q_rounds):
    parts = ["<h2>검색 순위 변화</h2>"]
    if len(q_rounds) < 2:
        parts.append('<p class="note">비교할 GSC 회차가 부족합니다. (queries CSV 2회차 이상 필요)</p>')
        return "".join(parts)
    (pd, prev), (cd, cur) = q_rounds[-2], q_rounds[-1]
    ups, downs, news = [], [], []
    for q, m in cur.items():
        if q in prev:
            delta = prev[q]["pos"] - m["pos"]  # +면 상승
            if delta > 0:
                ups.append((q, delta, m["pos"]))
            elif delta < 0:
                downs.append((q, -delta, m["pos"]))
        else:
            news.append((q, m["pos"]))
    ups.sort(key=lambda x: -x[1]); downs.sort(key=lambda x: -x[1])
    if not ups and not downs and not news:
        parts.append("<p class='muted'>해당 없음 (직전 회차 대비 순위 변동 없음)</p>")
        return "".join(parts)
    def line(lst, fmt):
        return ", ".join(fmt(x) for x in lst) if lst else "없음"
    parts.append("<ul>")
    parts.append("<li><b>오른 검색어</b>: %s <span class='why'>(상승세 — 콘텐츠 강화로 굳히기)</span></li>"
                 % esc(line(ups[:3], lambda x: "%s(▲%.0f→%.1f위)" % (x[0], x[1], x[2]))))
    parts.append("<li><b>내린 검색어</b>: %s <span class='why'>(하락 — 원인 점검 대상)</span></li>"
                 % esc(line(downs[:3], lambda x: "%s(▼%.0f→%.1f위)" % (x[0], x[1], x[2]))))
    parts.append("<li><b>새로 진입</b>: %s <span class='why'>(신규 유입 검색어 — 키울지 판단)</span></li>"
                 % esc(line(news, lambda x: "%s(%.1f위)" % (x[0], x[1]))))
    parts.append("</ul>")
    return "".join(parts)


def zeroclick_tier(pos):
    """노출 있는데 클릭 0인 항목을 순위 구간으로 판정.
    반환: (라벨, 설명) 또는 None(31위+ = 판단 불가라 경고에서 제외)."""
    if pos <= 10:
        return ("제목·설명 문제", "고치면 바로 효과 — 1~10위인데 클릭이 없음")
    if pos <= 30:
        return ("순위를 더 올려야 함", "노출은 있으나 11~30위라 클릭이 안 나옴")
    return None


def h_push_now(q_rounds, p_rounds):
    parts = ["<h2>지금 밀어야 할 것</h2>"]
    if not q_rounds and not p_rounds:
        parts.append('<p class="muted">해당 없음 (GSC 데이터가 없어 자동 추출 불가 — data/gsc/ CSV 필요)</p>')
        return "".join(parts)
    cur_q = q_rounds[-1][1] if q_rounds else {}
    cur_p = p_rounds[-1][1] if p_rounds else {}
    prev_p = p_rounds[-2][1] if len(p_rounds) >= 2 else {}

    # A) 브랜드 검색인데 5위 밖 — 별도 강조 (상호 검색은 1~3위가 정상)
    brand_low = sorted([(q, m) for q, m in cur_q.items() if is_brand_query(q) and m["pos"] > 5],
                       key=lambda kv: -kv[1]["impr"])
    if brand_low:
        parts.append("<p class='why'><b>⚠ 브랜드 검색인데 5위 밖</b> — 상호 검색은 1~3위가 정상이므로 최우선 대응 (정보형과 다른 기준)</p><ul>")
        for q, m in brand_low[:15]:
            parts.append("<li><b>%s</b> — 순위 %.1f · 노출 %d · 클릭 %d</li>"
                         % (esc(q), m["pos"], int(m["impr"]), int(m["clicks"])))
        parts.append("</ul>")

    # B) 1페이지 진입 후보(11~20위) + 페이지 이슈(순위 구간별) + 노출 급감
    li = []
    for q, m in sorted([(q, m) for q, m in cur_q.items() if 10 < m["pos"] <= 20],
                       key=lambda kv: kv[1]["pos"]):
        li.append("<li>검색어 <b>%s</b> — 순위 %.1f · 노출 %d <span class='why'>(11~20위, 1페이지 진입 후보)</span></li>"
                  % (esc(q), m["pos"], int(m["impr"])))
    for f, m in sorted([(f, m) for f, m in cur_p.items() if m["impr"] >= 20 and m["clicks"] == 0],
                       key=lambda kv: -kv[1]["impr"]):
        tier = zeroclick_tier(m["pos"])
        if not tier:
            continue  # 31위+ 는 순위가 낮아 판단 불가 → 경고 제외
        li.append("<li>페이지 <b>%s</b> — 노출 %d · 클릭 0 · 순위 %.1f <span class='why'>(%s — %s)</span></li>"
                  % (esc(f), int(m["impr"]), m["pos"], tier[0], tier[1]))
    for f, cm in cur_p.items():
        pm = prev_p.get(f)
        if pm and pm["impr"] > 0 and (pm["impr"] - cm["impr"]) / pm["impr"] >= 0.30:
            li.append("<li>페이지 <b>%s</b> — 노출 %d→%d <span class='why'>(급감 — 원인 점검)</span></li>"
                      % (esc(f), int(pm["impr"]), int(cm["impr"])))
    if li:
        parts.append("<ul>" + "".join(li) + "</ul>")
    else:
        parts.append("<p class='muted'>1페이지 진입 후보·페이지 이슈: 해당 없음</p>")

    # C) 좌우 2단: 클릭 먹히는 검색어 | 노출 있는데 클릭 0 (정보형, 순위 구간별·31위+ 제외)
    clked = sorted([(q, m) for q, m in cur_q.items() if m["clicks"] > 0],
                   key=lambda kv: -kv[1]["clicks"])[:15]
    zcq = sorted([(q, m) for q, m in cur_q.items()
                  if not is_brand_query(q) and m["impr"] >= 10 and m["clicks"] == 0 and m["pos"] <= 30],
                 key=lambda kv: kv[1]["pos"])[:15]

    def col_click(title, items):
        h = "<div class='col'><h3>%s</h3>" % title
        h += ("<ul>" + "".join("<li>✔ <b>%s</b> — 클릭 %d · 노출 %d · 순위 %.1f</li>"
              % (esc(q), int(m["clicks"]), int(m["impr"]), m["pos"]) for q, m in items) + "</ul>") \
            if items else "<p class='muted'>해당 없음</p>"
        return h + "</div>"

    def col_zero(title, items):
        h = "<div class='col'><h3>%s</h3>" % title
        if items:
            h += "<ul>" + "".join("<li><b>%s</b> — 노출 %d · 순위 %.1f <span class='why'>(%s)</span></li>"
                 % (esc(q), int(m["impr"]), m["pos"], zeroclick_tier(m["pos"])[0]) for q, m in items) + "</ul>"
        else:
            h += "<p class='muted'>해당 없음</p>"
        return h + "</div>"

    parts.append("<div class='cols'>")
    parts.append(col_click("클릭이 먹히는 검색어 (실제 유입)", clked))
    parts.append(col_zero("노출 있는데 클릭 0 (정보형 · 31위+ 제외)", zcq))
    parts.append("</div>")
    return "".join(parts)


def h_fix(cur_problems, p_rounds):
    parts = ["<h2>손봐야 할 것</h2><ul>"]
    if cur_problems:
        for no, title, f, detail in cur_problems:
            parts.append("<li><b>%s</b> — %s : %s <span class='why'>(점검 %s번)</span></li>"
                         % (esc(f), esc(title), esc(detail), esc(no)))
    else:
        parts.append("<li>점검 문제 없음 <span class='why'>(현재 오류 0건)</span></li>")
    # 4주 이상 노출 0
    zero4 = []
    if len(p_rounds) >= 2:
        cd = p_rounds[-1][0]
        old = [r for r in p_rounds if days_between(cd, r[0]) >= 28]
        if old:
            base = old[-1][1]
            for f, m in p_rounds[-1][1].items():
                bm = base.get(f)
                if m["impr"] == 0 and bm is not None and bm["impr"] == 0:
                    zero4.append(f)
    if zero4:
        for f in zero4:
            parts.append("<li><b>%s</b> — 4주 이상 노출 0 <span class='why'>(내용 보강 대상)</span></li>" % esc(f))
    else:
        parts.append("<li class='muted'>4주 이상 노출 0 페이지: 해당 없음 또는 이력 부족</li>")
    parts.append("</ul>")
    return "".join(parts)


def h_todos(todos):
    parts = ["<h2>다음 2주 할 일</h2><ul>"]
    if not todos:
        parts.append("<li class='muted'>자동으로 뽑을 항목이 없습니다.</li>")
    for t in todos:
        parts.append("<li><span class='chk'>☐</span> <b>%s</b> <small>(%s)</small><br>"
                     "<span class='why'>%s</span></li>"
                     % (esc(t["title"]), esc(t["evidence"]), esc(t["why"])))
    parts.append("</ul>")
    return "".join(parts)


# 상호(브랜드)가 들어간 검색어 판별용 토큰 — 세 사이트 상호를 모두 포함
BRAND_TOKENS = ["엘리트", "사라있네", "사라 있네", "달토", "달리는토끼", "달리는 토끼",
                "도파민", "유앤미"]


def is_brand_query(q):
    ql = (q or "").replace(" ", "")
    return any(tok.replace(" ", "") in ql for tok in BRAND_TOKENS)


def h_query_types(q_rounds):
    parts = ["<h2>검색어 상세 — 브랜드형 · 정보형</h2>"]
    cur_q = q_rounds[-1][1] if q_rounds else {}
    if not cur_q:
        parts.append('<p class="muted">해당 없음 (GSC 데이터가 없어 분류 불가)</p>')
        return "".join(parts)
    brand = sorted([(q, m) for q, m in cur_q.items() if is_brand_query(q)], key=lambda kv: kv[1]["pos"])
    info = sorted([(q, m) for q, m in cur_q.items() if not is_brand_query(q)], key=lambda kv: -kv[1]["impr"])[:20]
    parts.append("<p class='note'>브랜드형 <b>%d개</b> · 정보형 <b>%d개</b> "
                 "(브랜드형=상호 포함 검색어라 순위 낮으면 문제, 정보형=그 외)</p>" % (len(brand), len(cur_q) - len(brand)))

    def qtable(rows, order):
        h = "<table><thead><tr><th>검색어</th><th class='num'>순위</th><th class='num'>노출</th><th class='num'>클릭</th></tr></thead><tbody>"
        for q, m in rows:
            warn = " <b>⚠</b>" if (order == "brand" and m["pos"] > 5) else ""
            h += "<tr><td>%s%s</td><td class='num'>%.1f</td><td class='num'>%d</td><td class='num'>%d</td></tr>" \
                 % (esc(q), warn, m["pos"], int(m["impr"]), int(m["clicks"]))
        return h + "</tbody></table>"

    parts.append("<div class='cols'>")
    b = "<div class='col'><h3>브랜드형 — 전부 (⚠=순위 5위 밖)</h3>"
    b += qtable(brand, "brand") if brand else "<p class='muted'>해당 없음</p>"
    parts.append(b + "</div>")
    i = "<div class='col'><h3>정보형 — 노출 상위 (최대 20)</h3>"
    i += qtable(info, "info") if info else "<p class='muted'>해당 없음</p>"
    parts.append(i + "</div>")
    parts.append("</div>")
    return "".join(parts)


def build_summary_html(today, prev_todos, cur_p_rounds, cur_q_rounds,
                       html_count, problem_count, commit_count,
                       cur_problems, todos, next_round):
    cur_p = cur_p_rounds[-1][1] if cur_p_rounds else {}
    prev_p = cur_p_rounds[-2][1] if len(cur_p_rounds) >= 2 else {}
    cur_q = cur_q_rounds[-1][1] if cur_q_rounds else {}

    run_header = ("<div class='run-header'>%s · %s 회차<span class='r'>2주 점검 요약</span></div>"
                  % (esc(SITE_NAME), esc(today)))
    run_footer = "<div class='run-footer'>다음 회차 예정일: %s</div>" % esc(next_round)

    # 1장 — 판단과 행동 (반드시 한 장)
    page1 = [
        "<h1>%s <span class='date'>· 2주 점검 요약 %s</span></h1>" % (esc(SITE_NAME), esc(today)),
        "<p class='sub'>1장은 판단·행동용(한 장). 자세한 데이터는 2장 참고. Ctrl+P → A4 세로 인쇄.</p>",
        h_prev_actions(prev_todos, cur_p, prev_p),
        h_this_round(html_count, problem_count, commit_count, cur_q),
        h_push_now(cur_q_rounds, cur_p_rounds),
        h_todos(todos),
    ]
    # 2장 이후 — 참고 데이터
    page2 = [
        "<p class='ref-head'>참고 데이터 — %s · %s 회차 (자세히 볼 때)</p>" % (esc(SITE_NAME), esc(today)),
        h_query_types(cur_q_rounds),
        h_fix(cur_problems, cur_p_rounds),
        h_rank_change(cur_q_rounds),
    ]
    body = (run_header + "\n" + run_footer + "\n"
            + "\n".join(page1)
            + "\n<div class='page-break'></div>\n"
            + "\n".join(page2))
    return ("<!doctype html>\n<html lang='ko'>\n<head>\n<meta charset='utf-8'>\n"
            "<title>%s 2주 요약 %s</title>\n<style>%s</style>\n</head>\n<body>\n%s\n</body>\n</html>\n"
            % (esc(SITE_NAME), esc(today), CSS, body))


# ── main ─────────────────────────────────────────────────
def main():
    today = datetime.date.today().isoformat()

    check_r = checks_rounds()
    q_rounds = gsc_query_rounds()
    p_rounds = gsc_page_rounds()
    todo_r = todos_rounds()
    has_gsc = bool(q_rounds or p_rounds)

    cur_problems = problems_of(check_r[-1][1]) if check_r else []
    cur_q = q_rounds[-1][1] if q_rounds else {}
    cur_p = p_rounds[-1][1] if p_rounds else {}
    prev_p = p_rounds[-2][1] if len(p_rounds) >= 2 else {}

    html_count = len(glob.glob(os.path.join(BASE_DIR, "*.html")))
    problem_count = check_r[-1][1].get("total_problems", 0) if check_r else 0

    commit_count = 0
    raw = git(["log", "--since=%d days ago" % PERIOD_DAYS, "--oneline"])
    if raw:
        commit_count = len([l for l in raw.splitlines() if l.strip()])

    # 직전 회차 할 일 (오늘 날짜 제외한 가장 최근)
    prev_todos = None
    for d, doc in reversed(todo_r):
        if d and d < today:
            prev_todos = (d, doc)
            break

    # 다음 2주 할 일 자동 추출
    todos = build_todos(cur_problems, cur_q, cur_p, prev_p, has_gsc)

    # 1) 마크다운 리포트
    md = "\n".join([
        "# %s 2주 리포트 (%s)" % (SITE_NAME, today), "",
        md_section_checks(check_r),
        md_section_commits(),
        md_section_pages(),
        md_section_search(q_rounds, p_rounds),
        "## 5. 다음 확인 사항", "",
        "자동 판단이 어려운 항목입니다. 아래를 직접 확인하세요.", "",
        "- [ ] 순위 11~20위 검색어 — 1페이지(10위 이내)로 올릴 후보",
        "- [ ] 노출은 있는데 클릭 0인 페이지 — 제목·설명(메타) 점검 대상",
        "- [ ] 4주 이상 노출 0인 페이지 — 내용 보강 대상", "",
    ]).rstrip() + "\n"

    reports_dir = os.path.join(BASE_DIR, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    md_path = os.path.join(reports_dir, "%s-report.md" % today)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)

    # 2) 프린트용 요약본 HTML
    next_round = (datetime.date.fromisoformat(today) + datetime.timedelta(days=PERIOD_DAYS)).isoformat()
    summary = build_summary_html(today, prev_todos, p_rounds, q_rounds,
                                 html_count, problem_count, commit_count,
                                 cur_problems, todos, next_round)
    html_path = os.path.join(reports_dir, "%s-summary.html" % today)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(summary)

    # 3) 다음 2주 할 일 저장 (자동 채점용)
    todos_dir = os.path.join(BASE_DIR, "data", "todos")
    os.makedirs(todos_dir, exist_ok=True)
    todos_doc = {"date": today, "site": SITE_NAME, "items": todos}
    todos_path = os.path.join(todos_dir, "%s.json" % today)
    with open(todos_path, "w", encoding="utf-8") as f:
        json.dump(todos_doc, f, ensure_ascii=False, indent=2)

    # 화면 출력
    print(md)
    print("=" * 50)
    print("요약본(프린트용): %s" % os.path.relpath(html_path, BASE_DIR))
    print("리포트(마크다운): %s" % os.path.relpath(md_path, BASE_DIR))
    print("다음 2주 할 일:   %s  (%d건)" % (os.path.relpath(todos_path, BASE_DIR), len(todos)))
    print("-" * 50)
    print("[다음 2주 할 일]")
    if todos:
        for t in todos:
            print("  □ %s  (%s)" % (t["title"], t["evidence"]))
            print("      → %s" % t["why"])
    else:
        print("  (자동으로 뽑은 항목 없음)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
