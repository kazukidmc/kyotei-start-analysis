"""
艇国データバンク スクレイピング・分析バックエンド
Kivy/Android 環境用（tkinter・matplotlib・openpyxl 不使用）
"""
import re
import socket
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime

BASE_URL = "https://boatrace-db.net"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
    "Referer": "https://boatrace-db.net/",
}

# DNS fallback: NameResolutionError 対策
_BOATRACE_IP = "133.125.54.127"
_orig_getaddrinfo = socket.getaddrinfo
def _patched_getaddrinfo(host, port, *args, **kwargs):
    if host == "boatrace-db.net":
        host = _BOATRACE_IP
    return _orig_getaddrinfo(host, port, *args, **kwargs)
socket.getaddrinfo = _patched_getaddrinfo

# 艇色 (Kivy RGBA 0-1)
BOAT_RGBA = {
    1: (0.80, 0.80, 0.80, 1),
    2: (0.133, 0.133, 0.133, 1),
    3: (0.91, 0.188, 0.188, 1),
    4: (0.102, 0.478, 0.800, 1),
    5: (0.91, 0.753, 0.0, 1),
    6: (0.188, 0.627, 0.251, 1),
}
BOAT_TEXT_RGBA = {
    1: (0, 0, 0, 1),
    2: (1, 1, 1, 1),
    3: (1, 1, 1, 1),
    4: (1, 1, 1, 1),
    5: (0, 0, 0, 1),
    6: (1, 1, 1, 1),
}

_SPEED   = 22.0   # m/s
_BOAT_L  = 2.9    # m
_LANE_H  = 2.8    # m
_NOBIASHI_STEP = 0.3

def _make_session():
    s = requests.Session()
    s.headers.update(HEADERS)
    try:
        s.get(BASE_URL + "/", timeout=10)
    except Exception:
        pass
    time.sleep(3.5)
    return s

def search_player(query: str) -> list:
    s = _make_session()
    resp = s.get(f"{BASE_URL}/racer/search/", params={"name": query}, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    players, seen = [], set()
    for a in soup.select("a[href*='/racer/index2/regno/']"):
        m = re.search(r"/racer/index2/regno/(\d+)/", a["href"])
        if m:
            regno = m.group(1)
            if regno not in seen:
                seen.add(regno)
                players.append({"regno": regno, "name": a.get_text(strip=True)})
    return players

def _parse_st(st_str: str):
    s = str(st_str).strip()
    if s in ("F", "S0", "S1", ""):
        return None
    m = re.match(r"([0-9]+(?:\.[0-9]+)?)", s)
    return float(m.group(1)) if m else None

def _extract_name(soup, regno: str) -> str:
    for t in [soup.title.string if soup.title else "", *[x.get_text() for x in soup.select("h1,h2,.racer-name")]]:
        m = re.match(r"^([^\s　|｜（(の]+)", t)
        if m:
            name = re.sub(r"^[【\[]?\d{4}[】\]]?\s*", "", m.group(1)).strip()
            if len(name) >= 2 and name not in ("艇国", "ボートレース"):
                return name
    return f"選手{regno}"

VENUE_NAMES = [
    "住之江", "尼崎", "鳴門", "丸亀", "児島", "宮島", "徳山", "下関",
    "若松", "芦屋", "福岡", "唐津", "大村", "浜名湖", "蒲郡", "常滑",
    "津", "三国", "びわこ", "平和島", "多摩川", "江戸川", "戸田",
    "桐生", "太田",
]


def _parse_date(cell_text: str, year: int) -> str:
    trans = str.maketrans("０１２３４５６７８９", "0123456789")
    t = cell_text.translate(trans)
    m = re.search(r"(\d{1,2})月\s*(\d{1,2})日", t)
    if m:
        mo, da = int(m.group(1)), int(m.group(2))
        return f"{year}/{mo:02d}/{da:02d}"
    return cell_text.strip()


def _extract_venue(p_text: str) -> str:
    for v in VENUE_NAMES:
        if v in p_text:
            return v
    m = re.search(r"ボートレース(.{2,4})", p_text)
    return m.group(1) if m else ""


def _extract_grade(p_text: str) -> str:
    for g in ["SG", "G1", "G2", "G3"]:
        if g in p_text:
            return g
    return "一般"


def _parse_page(html: str, year: int) -> list:
    """
    艇国データバンクの年間成績ページ（tAllresults テーブル）をパースする。
    各テーブルは日付が横方向に並ぶワイドレイアウト:
      rows[0]=日付, rows[1]=レース番号, rows[2]=艇番/コース,
      rows[3]=ST, rows[4]=ST順位, rows[5]=結果
    各日付は2レース分（slot 0/1）の列に対応する。
    """
    soup = BeautifulSoup(html, "html.parser")
    races = []
    for table in soup.find_all("table", class_="tAllresults"):
        venue = ""
        prev_p = table.find_previous_sibling("p")
        if prev_p:
            p_text = prev_p.get_text(strip=True)
            venue = _extract_venue(p_text)

        rows = table.find_all("tr")
        if len(rows) < 6:
            continue

        def get_row_texts(r_idx):
            cells = rows[r_idx].find_all(["td", "th"])
            texts = [c.get_text(strip=True) for c in cells]
            while len(texts) < 14:
                texts.append("")
            return texts[:14]

        def get_boat_cells(r_idx):
            cells = rows[r_idx].find_all(["td", "th"])
            res = []
            for c in cells:
                boat = ""
                for klass in c.get("class", []):
                    mm = re.match(r"bgBoat(\d)", klass)
                    if mm:
                        boat = mm.group(1)
                        break
                res.append((boat, c.get_text(strip=True)))
            while len(res) < 14:
                res.append(("", ""))
            return res[:14]

        date_cells = rows[0].find_all(["td", "th"])
        date_texts = [c.get_text(strip=True) for c in date_cells]
        while len(date_texts) < 8:
            date_texts.append("")

        race_row    = get_row_texts(1)
        boat_course = get_boat_cells(2)
        st_row      = get_row_texts(3)
        rank_row    = get_row_texts(4)
        result_row  = get_row_texts(5)

        for k in range(1, 8):
            date_str = date_texts[k] if k < len(date_texts) else ""
            if not date_str:
                continue
            date_fmt = _parse_date(date_str, year)
            for slot in range(2):
                col = (k - 1) * 2 + slot
                if col >= 14:
                    break
                race_no_raw = race_row[col]
                if not race_no_raw:
                    continue
                race_no = re.sub(r"[^\d]", "", race_no_raw)
                boat_no, course = boat_course[col]
                races.append({
                    "競艇場": venue,
                    "開催日時": date_fmt,
                    "開催レース": f"{race_no}R" if race_no else race_no_raw,
                    "艇番": boat_no,
                    "コース": course,
                    "スタートタイム": st_row[col].strip(),
                    "スタート順位": re.sub(r"[()（）\[\]]", "", rank_row[col]).strip(),
                    "結果": result_row[col].strip(),
                })
    return races

def collect_recent_races(regno: str, target: int, course: int, log_cb, progress_cb):
    def _cc(races):
        return sum(1 for r in races if str(r.get("コース","")).strip() == str(course))

    log_cb(f"登録番号 {regno} 取得中（{course}コース目標: {target}件）...")
    s = _make_session()
    base_url = f"{BASE_URL}/racer/yall/regno/{regno}/"
    resp = s.get(base_url, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    player_name = _extract_name(soup, regno)

    current_year = datetime.now().year
    years = {current_year}
    for opt in soup.select("form.selector_form option, select option"):
        val = opt.get("value", "").strip()
        if re.match(r"^\d{4}$", val):
            y = int(val)
            if 2000 <= y <= current_year:
                years.add(y)
    years = sorted(years, reverse=True)

    all_races = _parse_page(resp.text, current_year)
    cc = _cc(all_races)
    log_cb(f"  {current_year}年: {len(all_races)}件 ({course}コース: {cc}件)")
    progress_cb(cc, target)

    if cc < target:
        for year in years:
            if year == current_year:
                continue
            try:
                time.sleep(3.5)
                r = s.get(f"{BASE_URL}/racer/yall/regno/{regno}/year/{year}/", timeout=15)
                r.raise_for_status()
                yr = _parse_page(r.text, year)
                all_races.extend(yr)
                cc = _cc(all_races)
                log_cb(f"  {year}年: {len(yr)}件 ({course}コース累計: {cc}/{target}件)")
                progress_cb(cc, target)
                if cc >= target:
                    break
            except Exception as e:
                log_cb(f"  {year}年: 取得失敗 {e}")

    course_races = [r for r in all_races if str(r.get("コース","")).strip() == str(course)]
    course_races.sort(key=lambda r: r.get("開催日時",""), reverse=True)
    result = course_races[:target]
    log_cb(f"  → {course}コース確定: {len(result)}件")
    return result, player_name

def _course_y(course: int) -> float:
    return -(course - 1) * _LANE_H

def collect_boat_info(players_data: list) -> list:
    result = []
    for pd in players_data:
        course   = pd["course"]
        boat_no  = int(pd.get("boat_no", course))
        name     = pd["name"]
        races    = pd["races"]
        subset   = [r for r in races if str(r.get("コース","")).strip() == str(course)]
        st_vals  = [_parse_st(r.get("スタートタイム","")) for r in subset]
        valid    = [v for v in st_vals if v is not None]
        avg_st   = sum(valid)/len(valid) if valid else 0.99
        f_count  = sum(1 for r in subset
                       if str(r.get("スタートタイム","")).strip() in ("F","S0","S1"))
        f_rate   = f_count/len(subset) if subset else 0.0

        rank_vals  = [r.get("スタート順位","") for r in subset]
        st1_count  = sum(1 for v in rank_vals if str(v).strip() == "1")
        st1_rate   = st1_count/len(subset) if subset else 0.0

        result_vals = [r.get("結果","") for r in subset]
        win_count   = sum(1 for v in result_vals if str(v).strip() == "1")
        win_rate    = win_count/len(subset) if subset else 0.0

        nobiashi = int(pd.get("nobiashi", 3))
        nobi_shift = (nobiashi - 1) * _NOBIASHI_STEP

        result.append({
            "course":   course,
            "boat_no":  boat_no,
            "name":     name,
            "avg_st":   avg_st,
            "f_rate":   f_rate,
            "f_count":  f_count,
            "st1_rate": st1_rate,
            "win_rate": win_rate,
            "n":        len(subset),
            "valid_n":  len(valid),
            "bow_x":    -avg_st * _SPEED + nobi_shift,
            "stern_x":  -avg_st * _SPEED - _BOAT_L + nobi_shift,
            "y_center": _course_y(course),
            "de_ashi":  int(pd.get("de_ashi", 3)),
            "nobiashi": nobiashi,
        })
    return result
