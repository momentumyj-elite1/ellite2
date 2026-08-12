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


def effect_of(target_file, cur_pages, prev_pages):
    """완료 항목의 효과 판정 (노출 기준)."""
    if not target_file or not cur_pages or not prev_pages:
        return "데이터 없음", None
    cm = cur_pages.get(target_file)
    pm = prev_pages.get(target_file)
    if not cm or not pm:
        return "데이터 없음", None
    delta = cm["impr"] - pm["impr"]
    detail = "노출 %d → %d, 클릭 %d → %d, 순위 %.1f → %.1f" % (
        int(pm["impr"]), int(cm["impr"]), int(pm["clicks"]), int(cm["clicks"]),
        pm["pos"], cm["pos"])
    if delta > 0:
        return "효과 있음", detail
    if delta < 0:
        return "재검토 필요", detail
    return "지켜보는 중", detail


# ── 다음 2주 할 일 자동 추출 ─────────────────────────────
def build_todos(cur_problems, cur_q, cur_p, prev_p, has_gsc):
    todos = []

    # 우선순위 1: 점검에서 나온 문제
    for no, title, f, detail in cur_problems:
        if no == 1:  # 금지 문구
            m = re.search(r'"([^"]+)"', detail or "")
            phrase = m.group(1) if m else None
            if f and phrase:
                todos.append({
                    "title": "%s 에서 금지 문구 '%s' 제거" % (f, phrase),
                    "why": "과장·금지 문구는 신뢰도와 노출에 악영향",
                    "evidence": "점검 1번 지적",
                    "target_file": f,
                    "check": {"method": "contains", "string": phrase, "expect": "absent"},
                })
                continue
        if no == 5:  # 필수 메타 누락
            tag = (detail or "").split(",")[0].strip()
            tagmap = {"title": "<title>", "meta description": 'name="description"',
                      "canonical": 'rel="canonical"', "og:title": 'property="og:title"',
                      "og:description": 'property="og:description"',
                      "og:image": 'property="og:image"'}
            needle = tagmap.get(tag)
            if f and needle:
                todos.append({
                    "title": "%s 메타 태그 보완 (%s)" % (f, detail),
                    "why": "필수 메타가 없으면 검색결과 노출·클릭이 떨어짐",
                    "evidence": "점검 5번 지적",
                    "target_file": f,
                    "check": {"method": "contains", "string": needle, "expect": "present"},
                })
                continue
        todos.append({
            "title": "%s : %s 처리" % (f, detail),
            "why": "점검에서 발견된 문제 — 방치 시 품질·노출 저하",
            "evidence": "점검 %d번 지적" % (no or 0),
            "target_file": f,
            "check": {"method": "manual"},
        })

    # 우선순위 2: 노출 20+ 인데 클릭 0 페이지 → 제목·설명 개선
    for fn, m in sorted(cur_p.items(), key=lambda kv: -kv[1]["impr"]):
        if m["impr"] >= 20 and m["clicks"] == 0:
            todos.append({
                "title": "%s 제목·설명 개선" % fn,
                "why": "노출은 있는데 클릭이 없음 — 제목/메타가 검색 의도와 안 맞을 가능성",
                "evidence": "노출 %d, 클릭 0" % int(m["impr"]),
                "target_file": fn,
                "check": {"method": "title_changed", "baseline": page_title(fn) or ""},
            })

    # 우선순위 3: 순위 11~20위 검색어 → 1페이지 진입
    for q, m in sorted(cur_q.items(), key=lambda kv: kv[1]["pos"]):
        if 10 < m["pos"] <= 20:
            todos.append({
                "title": "'%s' 검색어 강화" % q,
                "why": "11~20위 — 조금만 개선하면 1페이지(10위 이내) 진입 가능",
                "evidence": "순위 %.1f, 노출 %d" % (m["pos"], int(m["impr"])),
                "target_file": None,
                "check": {"method": "manual"},
            })

    # 우선순위 4: 노출 30% 이상 감소 페이지
    for fn, cm in cur_p.items():
        pm = prev_p.get(fn)
        if pm and pm["impr"] > 0:
            drop = (pm["impr"] - cm["impr"]) / pm["impr"]
            if drop >= 0.30:
                todos.append({
                    "title": "%s 노출 급감 원인 점검" % fn,
                    "why": "노출이 크게 줄면 색인·콘텐츠·경쟁 변화 신호",
                    "evidence": "노출 %d → %d (-%d%%)" % (int(pm["impr"]), int(cm["impr"]), int(drop * 100)),
                    "target_file": fn,
                    "check": {"method": "title_changed", "baseline": page_title(fn) or ""},
                })

    # 데이터가 없어 아무것도 못 뽑은 경우: 데이터 확보를 첫 할 일로
    if not todos and not has_gsc:
        todos.append({
            "title": "data/gsc/ 에 서치콘솔 CSV 넣기",
            "why": "순위·클릭 데이터가 있어야 개선 우선순위를 자동으로 뽑을 수 있음",
            "evidence": "현재 GSC 데이터 0건",
            "target_file": None,
            "check": {"method": "manual"},
        })

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
@page { size: A4; margin: 11mm; }
* { box-sizing: border-box; }
body { font-family: 'Malgun Gothic','맑은 고딕','Apple SD Gothic Neo',sans-serif;
       font-size: 10px; line-height: 1.4; color: #000; margin: 0; }
h1 { font-size: 15px; margin: 0 0 2px; }
h1 .date { font-weight: normal; color: #555; font-size: 11px; }
.sub { color: #555; font-size: 9px; margin-bottom: 6px; }
h2 { font-size: 11px; margin: 9px 0 3px; padding-bottom: 2px;
     border-bottom: 1.5px solid #000; }
p { margin: 2px 0; }
ul { margin: 2px 0 4px; padding-left: 15px; }
li { margin: 1px 0; }
.why { color: #444; font-size: 9px; }
table { width: 100%; border-collapse: collapse; margin: 2px 0 4px; }
th, td { border: 1px solid #999; padding: 2px 4px; text-align: left; vertical-align: top; }
th { background: #e6e6e6; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
.num { text-align: right; white-space: nowrap; }
.tag { display: inline-block; padding: 0 4px; font-size: 8.5px; border: 1px solid #000; }
.tag.strong { font-weight: bold; border-width: 2px; }
.tag.mid { font-style: italic; }
.tag.weak { color: #555; border-color: #999; }
.blank { display: inline-block; min-width: 120px; border-bottom: 1px solid #999; }
.chk { font-size: 12px; }
.muted { color: #666; }
.note { color: #555; font-size: 9px; }
.two { display: flex; gap: 12px; }
.two > div { flex: 1; }
small { font-size: 8.5px; }
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
            label, detail = effect_of(it.get("target_file"), cur_p, prev_p)
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


def h_this_round(html_count, problem_count, commit_count):
    return ("<h2>이번 회차 요약</h2>"
            "<ul>"
            "<li>페이지 <b>%d개</b> — 사이트 전체 규모 <span class='why'>(콘텐츠 자산 수)</span></li>"
            "<li>점검 문제 <b>%d건</b> — 지금 손봐야 할 오류 <span class='why'>(0에 가까울수록 좋음)</span></li>"
            "<li>최근 2주 커밋 <b>%d개</b> — 실제 작업량 <span class='why'>(개선 활동 빈도)</span></li>"
            "</ul>" % (html_count, problem_count, commit_count))


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


def h_push_now(q_rounds, p_rounds):
    parts = ["<h2>지금 밀어야 할 것</h2>"]
    if not q_rounds and not p_rounds:
        parts.append('<p class="note">GSC 데이터가 없어 자동 추출 불가. (data/gsc/ CSV 필요)</p>')
        return "".join(parts)
    cur_q = q_rounds[-1][1] if q_rounds else {}
    cur_p = p_rounds[-1][1] if p_rounds else {}
    prev_p = p_rounds[-2][1] if len(p_rounds) >= 2 else {}
    parts.append("<ul>")
    # 11~20위
    band = sorted([(q, m) for q, m in cur_q.items() if 10 < m["pos"] <= 20],
                  key=lambda kv: kv[1]["pos"])
    if band:
        for q, m in band:
            parts.append("<li>검색어 <b>%s</b> — 순위 %.1f, 노출 %d <span class='why'>(1페이지 진입 후보)</span></li>"
                         % (esc(q), m["pos"], int(m["impr"])))
    else:
        parts.append("<li class='muted'>11~20위 검색어 없음</li>")
    # 노출 20+ 클릭 0
    zc = sorted([(f, m) for f, m in cur_p.items() if m["impr"] >= 20 and m["clicks"] == 0],
                key=lambda kv: -kv[1]["impr"])
    for f, m in zc:
        parts.append("<li>페이지 <b>%s</b> — 노출 %d, 클릭 0 <span class='why'>(제목·설명이 클릭을 못 만들고 있음)</span></li>"
                     % (esc(f), int(m["impr"])))
    # 노출 30%+ 감소
    for f, cm in cur_p.items():
        pm = prev_p.get(f)
        if pm and pm["impr"] > 0 and (pm["impr"] - cm["impr"]) / pm["impr"] >= 0.30:
            parts.append("<li>페이지 <b>%s</b> — 노출 %d→%d <span class='why'>(급감 — 원인 점검)</span></li>"
                         % (esc(f), int(pm["impr"]), int(cm["impr"])))
    parts.append("</ul>")
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


def build_summary_html(today, prev_todos, cur_p_rounds, cur_q_rounds,
                       html_count, problem_count, commit_count,
                       cur_problems, todos):
    cur_p = cur_p_rounds[-1][1] if cur_p_rounds else {}
    prev_p = cur_p_rounds[-2][1] if len(cur_p_rounds) >= 2 else {}
    body = [
        "<h1>%s <span class='date'>· 2주 점검 요약 %s</span></h1>" % (esc(SITE_NAME), esc(today)),
        "<p class='sub'>브라우저에서 Ctrl+P → A4 세로로 인쇄하세요. 흑백 인쇄 기준으로 만들었습니다.</p>",
        h_prev_actions(prev_todos, cur_p, prev_p),
        h_this_round(html_count, problem_count, commit_count),
        h_rank_change(cur_q_rounds),
        h_push_now(cur_q_rounds, cur_p_rounds),
        h_fix(cur_problems, cur_p_rounds),
        h_todos(todos),
    ]
    return ("<!doctype html>\n<html lang='ko'>\n<head>\n<meta charset='utf-8'>\n"
            "<title>%s 2주 요약 %s</title>\n<style>%s</style>\n</head>\n<body>\n%s\n</body>\n</html>\n"
            % (esc(SITE_NAME), esc(today), CSS, "\n".join(body)))


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
    summary = build_summary_html(today, prev_todos, p_rounds, q_rounds,
                                 html_count, problem_count, commit_count,
                                 cur_problems, todos)
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
