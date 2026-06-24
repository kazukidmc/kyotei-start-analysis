"""
Excel出力モジュール（Android版・Pillow描画）
PC版 kyotei_race_analysis.py と同一の5シート構成の .xlsx を出力する。
グラフ・配置図・船足評価は matplotlib の代わりに Pillow で描画する
（numpy 非依存・Android ビルド安定）。
日本語フォントは同梱の NotoSansJP.ttf を使用する。
"""

import io
import os
import tempfile

from PIL import Image, ImageDraw, ImageFont

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.drawing.image import Image as XLImage

# ── 定数 ──────────────────────────────────────────────
BOAT_BG = {
    1: "CCCCCC", 2: "222222", 3: "E83030",
    4: "1A7ACC", 5: "E8C000", 6: "30A040",
}
BOAT_FG = {
    1: "000000", 2: "FFFFFF", 3: "FFFFFF",
    4: "FFFFFF", 5: "000000", 6: "FFFFFF",
}
BOAT_RGB = {
    1: (0xCC, 0xCC, 0xCC), 2: (0x22, 0x22, 0x22), 3: (0xE8, 0x30, 0x30),
    4: (0x1A, 0x7A, 0xCC), 5: (0xE8, 0xC0, 0x00), 6: (0x30, 0xA0, 0x40),
}
BOAT_TEXT_RGB = {
    1: (0, 0, 0), 2: (255, 255, 255), 3: (255, 255, 255),
    4: (255, 255, 255), 5: (0, 0, 0), 6: (255, 255, 255),
}

_ST_MAX  = 0.40
_SPEED   = 22.0   # m/s
_BOAT_L  = 2.9    # 船体長 [m]
_BOAT_H  = 1.6    # 船体高 [m]
_LANE_H  = 2.8    # レーン中心間距離 [m]
_BG_DISP_W = 1400
_BG_DISP_H = 560
_NOBIASHI_STEP = 0.3

RATING_RGB = {1: (0xB2, 0x22, 0x22), 2: (0xD0, 0x60, 0x00),
              3: (0xC8, 0xA8, 0x00), 4: (0x3E, 0x9B, 0x3E),
              5: (0x00, 0x64, 0x00)}
RATING_EMPTY = (0xE0, 0xE0, 0xE0)


# ── フォント ──────────────────────────────────────────
_FONT_PATH = os.path.join(os.path.dirname(__file__), "NotoSansJP.ttf")
_font_cache = {}


def _font(size):
    size = int(size)
    if size not in _font_cache:
        try:
            _font_cache[size] = ImageFont.truetype(_FONT_PATH, size)
        except Exception:
            _font_cache[size] = ImageFont.load_default()
    return _font_cache[size]


def _hex_rgb(h):
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _dashed_v(d, x, y0, y1, fill, width, dash=10, gap=7):
    y = y0
    while y < y1:
        d.line([(x, y), (x, min(y + dash, y1))], fill=fill, width=width)
        y += dash + gap


# ── ST解析 ────────────────────────────────────────────
def _parse_st(val):
    v = str(val).strip()
    if not v or v in ("F", "S0", "S1", "K", "欠", "-"):
        return None
    v = v.lstrip("+")
    try:
        return float(v)
    except ValueError:
        return None


def _course_y(c):
    return -(c - 1) * _LANE_H


# ── 配置図データ計算（pure python）──────────────────────
def _collect_boat_info(players_data):
    result = []
    for pd in players_data:
        course = pd["course"]
        name   = pd["name"]
        races  = pd["races"]
        subset = [r for r in races if str(r.get("コース", "")).strip() == str(course)]
        st_vals = [_parse_st(r.get("スタートタイム", "")) for r in subset]
        valid   = [v for v in st_vals if v is not None]
        avg_st  = sum(valid) / len(valid) if valid else 0.99
        f_count = sum(1 for r in subset
                      if str(r.get("スタートタイム", "")).strip() in ("F", "S0", "S1"))
        f_rate  = f_count / len(subset) if subset else 0.0
        result.append({
            "course":   course,
            "boat_no":  int(pd.get("boat_no", course)),
            "name":     name,
            "avg_st":   avg_st,
            "f_rate":   f_rate,
            "n":        len(subset),
            "valid_n":  len(valid),
            "bow_x":    -avg_st * _SPEED,
            "stern_x":  -avg_st * _SPEED - _BOAT_L,
            "y_center": _course_y(course),
            "de_ashi":  int(pd.get("de_ashi", 3)),
            "nobiashi": int(pd.get("nobiashi", 3)),
        })
    return result


def _apply_boat_corrections(boat_info, manual_offsets=None):
    corrected = []
    for info in boat_info:
        c = dict(info)
        nobiashi = info.get("nobiashi", 1)
        auto_shift = (nobiashi - 1) * _NOBIASHI_STEP
        manual_shift = (manual_offsets or {}).get(info["course"], 0.0)
        total = auto_shift + manual_shift
        c["bow_x"]   = info["bow_x"] + total
        c["stern_x"] = info["stern_x"] + total
        corrected.append(c)
    return corrected


def _formation_axes_bounds(boat_info):
    MARGIN_LEFT = 1.0
    MARGIN_RIGHT = 2.0
    min_stern = min(info["stern_x"] for info in boat_info)
    max_bow   = max(info["bow_x"] for info in boat_info)
    x_min = min_stern - MARGIN_LEFT
    x_max = max(max_bow + MARGIN_RIGHT, MARGIN_RIGHT)
    y_max =  _LANE_H * 0.6
    y_min = -5 * _LANE_H - _LANE_H * 0.6
    return x_min, x_max, y_min, y_max


# ── Pillow描画: 配置図 ────────────────────────────────
def _render_formation_png(players_data, show_start_line, show_labels,
                          manual_offsets=None) -> bytes:
    boat_info = _apply_boat_corrections(
        _collect_boat_info(players_data), manual_offsets)
    x_min, x_max, y_min, y_max = _formation_axes_bounds(boat_info)

    W, H = _BG_DISP_W, _BG_DISP_H
    img = Image.new("RGB", (W, H), (75, 168, 208))  # 水面 #4BA8D0
    d = ImageDraw.Draw(img)

    def px(mx):
        return (mx - x_min) / (x_max - x_min) * W

    def py(my):
        return (1.0 - (my - y_min) / (y_max - y_min)) * H

    # レーン線
    for c in range(1, 8):
        yy = py(_course_y(c) + _LANE_H / 2)
        d.line([(0, yy), (W, yy)], fill=(255, 255, 255), width=1)

    # スタートライン
    if show_start_line:
        sx = px(0)
        _dashed_v(d, sx, 0, H, (255, 34, 34), 3)
        d.text((sx + 6, py(y_max * 0.8)), "START",
               font=_font(16), fill=(255, 51, 51), anchor="lm")

    # 各艇
    for b in boat_info:
        bn = b.get("boat_no", b["course"])
        bg = BOAT_RGB.get(bn, (170, 170, 170))
        fg = BOAT_TEXT_RGB.get(bn, (0, 0, 0))
        left  = px(b["stern_x"])
        right = px(b["bow_x"])
        top   = py(b["y_center"] + _BOAT_H / 2)
        bot   = py(b["y_center"] - _BOAT_H / 2)
        d.rounded_rectangle([left, top, right, bot], radius=8,
                            fill=bg, outline=(255, 255, 255), width=2)
        cx, cy = (left + right) / 2, (top + bot) / 2
        d.text((cx, cy), str(bn), font=_font(28), fill=fg, anchor="mm")

        if show_labels:
            name = b["name"][:4] if len(b["name"]) > 4 else b["name"]
            d.text((cx, top - 6), name, font=_font(18),
                   fill=(255, 255, 255), anchor="mb")
            avg = b.get("avg_st", 0)
            if avg > 0 and b.get("valid_n", 0) > 0:
                f_str = f"  F{b['f_rate']:.0%}" if b.get("f_rate", 0) >= 0.05 else ""
                d.text((right + 6, cy), f"ST.{round(avg * 1000):03d}{f_str}",
                       font=_font(16), fill=(255, 255, 170), anchor="lm")

    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


# ── Pillow描画: 分析グラフ（ヒストグラム＋ST順位）────────
def _draw_hist_cell(d, ox, oy, w, h, st_vals, title, color):
    pad_l, pad_r, pad_t, pad_b = 50, 12, 34, 46
    px0, py0 = ox + pad_l, oy + pad_t
    px1, py1 = ox + w - pad_r, oy + h - pad_b
    d.rectangle([px0, py0, px1, py1], fill=(248, 249, 250))

    valid = [v for v in st_vals if v is not None]
    invalid = len(st_vals) - len(valid)
    steps = round(_ST_MAX / 0.01)
    bins = [0] * steps
    overflow = 0
    for v in valid:
        idx = round(v * 100)
        if 0 <= idx < steps:
            bins[idx] += 1
        else:
            overflow += 1
    counts = [invalid] + bins
    if overflow:
        counts[-1] += overflow
    n = len(counts)
    maxc = max(counts) if any(counts) else 1
    bw = (px1 - px0) / n
    for i, c in enumerate(counts):
        if c <= 0:
            continue
        bh = (c / maxc) * (py1 - py0 - 14)
        x0 = px0 + i * bw + 1
        x1 = px0 + (i + 1) * bw - 1
        d.rectangle([x0, py1 - bh, x1, py1], fill=color)
        d.text(((x0 + x1) / 2, py1 - bh - 2), str(c),
               font=_font(8), fill=(60, 60, 60), anchor="mb")

    labels = ["F/S"] + [f".{i:02d}" if i % 5 == 0 else "" for i in range(steps)]
    for i, lab in enumerate(labels):
        if lab:
            d.text((px0 + (i + 0.5) * bw, py1 + 3), lab,
                   font=_font(9), fill=(80, 80, 80), anchor="ma")

    d.text((ox + w / 2, oy + 4), title, font=_font(13),
           fill=(31, 78, 121), anchor="ma")
    mean = (sum(valid) / len(valid)) if valid else None
    xl = f"STタイム (n={len(st_vals)}" + (f", 平均={mean:.3f}" if mean else "") + ")"
    d.text((ox + w / 2, py1 + 22), xl, font=_font(10),
           fill=(80, 80, 80), anchor="ma")


def _draw_rank_cell(d, ox, oy, w, h, subset, title, color):
    pad_l, pad_r, pad_t, pad_b = 50, 12, 34, 46
    px0, py0 = ox + pad_l, oy + pad_t
    px1, py1 = ox + w - pad_r, oy + h - pad_b
    d.rectangle([px0, py0, px1, py1], fill=(248, 249, 250))

    rank_data = {r: {"n": 0, "win": 0, "top3": 0} for r in range(1, 7)}
    for rec in subset:
        rk = str(rec.get("スタート順位", "")).strip()
        if not (rk.isdigit() and 1 <= int(rk) <= 6):
            continue
        rk = int(rk)
        res = str(rec.get("結果", "")).strip()
        rank_data[rk]["n"] += 1
        if res == "1":
            rank_data[rk]["win"] += 1
        if res in ("1", "2", "3"):
            rank_data[rk]["top3"] += 1

    counts = [rank_data[r]["n"] for r in range(1, 7)]
    maxc = max(counts) if any(counts) else 1
    bw = (px1 - px0) / 6
    is_dark = (0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]) < 128
    txt_col = (255, 255, 255) if is_dark else (51, 51, 51)

    for i, rk in enumerate(range(1, 7)):
        nrec = rank_data[rk]["n"]
        x0 = px0 + i * bw + 4
        x1 = px0 + (i + 1) * bw - 4
        bh = (nrec / maxc) * (py1 - py0 - 16) if nrec else 0
        d.rectangle([x0, py1 - bh, x1, py1], fill=color)
        d.text(((x0 + x1) / 2, py1 - bh - 2), str(nrec),
               font=_font(10), fill=(60, 60, 60), anchor="mb")
        if nrec and bh >= (py1 - py0) * 0.22:
            win_r = rank_data[rk]["win"] / nrec * 100
            top3_r = rank_data[rk]["top3"] / nrec * 100
            cy = py1 - bh / 2
            d.text(((x0 + x1) / 2, cy - 7), f"勝率{win_r:.0f}%",
                   font=_font(10), fill=txt_col, anchor="mm")
            d.text(((x0 + x1) / 2, cy + 7), f"3連{top3_r:.0f}%",
                   font=_font(10), fill=txt_col, anchor="mm")
        # x軸ラベル（ST順位）
        d.text(((x0 + x1) / 2, py1 + 3), str(rk),
               font=_font(10), fill=(80, 80, 80), anchor="ma")

    d.text((ox + w / 2, oy + 4), title, font=_font(13),
           fill=(31, 78, 121), anchor="ma")
    d.text((ox + w / 2, py1 + 22), f"ST順位 (n={sum(counts)})",
           font=_font(10), fill=(80, 80, 80), anchor="ma")


def _render_comparison_png(players_data) -> bytes:
    CELL_W, CELL_H = 560, 340
    TITLE_H = 44
    W = CELL_W * 2
    H = TITLE_H + CELL_H * 6
    img = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((W / 2, 10), "6艇 スタート分析グラフ（コース別）",
           font=_font(20), fill=(31, 78, 121), anchor="ma")

    for row, pd in enumerate(players_data):
        course = pd["course"]
        boat_no = int(pd.get("boat_no", course))
        name = pd["name"]
        races = pd["races"]
        color = BOAT_RGB.get(boat_no, (68, 114, 196))
        subset = [r for r in races if str(r.get("コース", "")).strip() == str(course)]
        st_all = [_parse_st(r.get("スタートタイム", "")) for r in subset]

        oy = TITLE_H + row * CELL_H
        label = f"{course}コース {name} (対象{len(subset)}R)"
        _draw_hist_cell(d, 0, oy, CELL_W, CELL_H, st_all,
                        f"{label} STタイム分布", color)
        _draw_rank_cell(d, CELL_W, oy, CELL_W, CELL_H, subset,
                        f"{label} ST順位分布", color)

    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


# ── Pillow描画: 船足評価サマリー ──────────────────────
def _draw_rating_pips(d, cx, cy, rating, bar_len=200, bar_h=26):
    seg = 5
    sw = bar_len / seg
    for i in range(seg):
        filled = i < rating
        col = RATING_RGB.get(rating, (136, 136, 136)) if filled else RATING_EMPTY
        x0 = cx - bar_len / 2 + i * sw + 2
        x1 = cx - bar_len / 2 + (i + 1) * sw - 2
        d.rectangle([x0, cy - bar_h / 2, x1, cy + bar_h / 2],
                    fill=col, outline=(255, 255, 255), width=1)
    d.text((cx + bar_len / 2 + 12, cy), str(rating),
           font=_font(18), fill=RATING_RGB.get(rating, (136, 136, 136)),
           anchor="lm")


def _render_performance_png(players_data) -> bytes:
    n = len(players_data)
    ROW_H = 56
    TITLE_H = 50
    HDR_H = 40
    W = 880
    H = TITLE_H + HDR_H + ROW_H * n + 16
    img = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)

    d.text((W / 2, 12), "船足評価サマリー", font=_font(22),
           fill=(31, 78, 121), anchor="ma")

    cols = [(48, "艇"), (170, "選手名"), (380, "出足評価"),
            (620, "伸足評価"), (820, "平均ST")]
    hdr_y = TITLE_H
    d.rectangle([0, hdr_y, W, hdr_y + HDR_H], fill=(31, 78, 121))
    for cx, ct in cols:
        d.text((cx, hdr_y + HDR_H / 2), ct, font=_font(13),
               fill=(255, 255, 255), anchor="mm")

    for i, pd in enumerate(players_data):
        course = pd["course"]
        boat_no = int(pd.get("boat_no", course))
        name = pd["name"]
        races = pd["races"]
        de_ashi = int(pd.get("de_ashi", 3))
        nobiashi = int(pd.get("nobiashi", 3))
        subset = [r for r in races if str(r.get("コース", "")).strip() == str(course)]
        st_vals = [_parse_st(r.get("スタートタイム", "")) for r in subset]
        valid = [v for v in st_vals if v is not None]
        avg_st = sum(valid) / len(valid) if valid else None

        ry = hdr_y + HDR_H + i * ROW_H
        row_bg = (240, 246, 255) if i % 2 == 0 else (255, 255, 255)
        d.rectangle([0, ry, W, ry + ROW_H], fill=row_bg, outline=(221, 221, 221))
        cy = ry + ROW_H / 2

        bg = BOAT_RGB.get(boat_no, (170, 170, 170))
        fg = BOAT_TEXT_RGB.get(boat_no, (0, 0, 0))
        d.rectangle([8, ry + 6, 88, ry + ROW_H - 6], fill=bg)
        d.text((48, cy), str(boat_no), font=_font(24), fill=fg, anchor="mm")

        short = name[:6] if len(name) > 6 else name
        d.text((170, cy), short, font=_font(15), fill=(34, 34, 34), anchor="mm")

        _draw_rating_pips(d, 380, cy, de_ashi)
        _draw_rating_pips(d, 620, cy, nobiashi)

        st_txt = f".{round(avg_st * 1000):03d}" if avg_st is not None else "―"
        d.text((820, cy), st_txt, font=_font(16), fill=(51, 51, 51), anchor="mm")

    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


# ── PNGをExcelに埋め込むヘルパー ──────────────────────
def _png_to_tmp(png_bytes):
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.write(png_bytes)
    tmp.close()
    return tmp.name


# ── Excel出力 ─────────────────────────────────────────
def write_analysis_excel(players_data, output_path):
    wb = openpyxl.Workbook()
    _write_data_sheet(wb, players_data)
    _write_chart_sheet(wb, players_data)
    _write_formation_sheet(wb, players_data)
    _write_clean_formation_sheet(wb, players_data)
    _write_performance_sheet(wb, players_data)
    wb.save(output_path)


def _write_data_sheet(wb, players_data):
    ws = wb.active
    ws.title = "出走データ"
    ws.sheet_view.showGridLines = True

    center = Alignment(horizontal="center", vertical="center")
    thin = Side(style="thin", color="CCCCCC")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", size=10)

    row = 1
    ws.merge_cells(f"A{row}:H{row}")
    tc = ws[f"A{row}"]
    tc.value = "6艇 出走データ（コース別）"
    tc.font = Font(bold=True, size=13, color="1F4E79")
    tc.alignment = center
    ws.row_dimensions[row].height = 28
    row += 1

    for pd in players_data:
        course  = pd["course"]
        boat_no = int(pd.get("boat_no", course))
        name    = pd["name"]
        races   = pd["races"]
        subset  = [r for r in races if str(r.get("コース", "")).strip() == str(course)]
        if not subset:
            continue

        bg = BOAT_BG.get(boat_no, "AAAAAA")
        fg = BOAT_FG.get(boat_no, "000000")

        ws.merge_cells(f"A{row}:H{row}")
        hc = ws[f"A{row}"]
        hc.value = f"【{course}コース / {boat_no}号艇】  {name}  （対象レース数: {len(subset)}）"
        hc.font = Font(bold=True, size=11, color=fg)
        hc.fill = PatternFill(start_color=bg, end_color=bg, fill_type="solid")
        hc.alignment = Alignment(horizontal="left", vertical="center", indent=1)
        ws.row_dimensions[row].height = 22
        row += 1

        cols = ["競艇場", "開催日時", "開催レース", "艇番", "コース",
                "スタートタイム", "スタート順位", "結果(着)"]
        widths = [12, 13, 11, 6, 6, 14, 12, 9]
        for ci, (cn, cw) in enumerate(zip(cols, widths), 1):
            cell = ws.cell(row=row, column=ci, value=cn)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = center
            cell.border = border
            ws.column_dimensions[get_column_letter(ci)].width = max(
                ws.column_dimensions[get_column_letter(ci)].width or 0, cw)
        ws.row_dimensions[row].height = 20
        row += 1

        zebra = PatternFill(start_color="EEF3FB", end_color="EEF3FB", fill_type="solid")
        result_fill_map = {"1": "FFD700", "2": "C0C0C0", "3": "CD7F32"}

        for i, race in enumerate(subset):
            vals = [
                race.get("競艇場", ""), race.get("開催日時", ""),
                race.get("開催レース", ""), race.get("艇番", ""),
                race.get("コース", ""), race.get("スタートタイム", ""),
                race.get("スタート順位", ""), race.get("結果", ""),
            ]
            for ci, val in enumerate(vals, 1):
                cell = ws.cell(row=row, column=ci, value=val)
                cell.alignment = center
                cell.border = border
                if i % 2 == 0:
                    cell.fill = zebra

            bn = str(race.get("艇番", "")).strip()
            if bn in [str(x) for x in range(1, 7)]:
                b = int(bn)
                bbg = BOAT_BG.get(b, "AAAAAA")
                bfg = BOAT_FG.get(b, "000000")
                for ci in [4, 5]:
                    bc = ws.cell(row=row, column=ci)
                    bc.fill = PatternFill(start_color=bbg, end_color=bbg, fill_type="solid")
                    bc.font = Font(bold=True, color=bfg)

            rs = str(race.get("結果", "")).strip()
            if rs in result_fill_map:
                rc = ws.cell(row=row, column=8)
                rc.fill = PatternFill(start_color=result_fill_map[rs],
                                      end_color=result_fill_map[rs], fill_type="solid")
                rc.font = Font(bold=True)

            ws.row_dimensions[row].height = 17
            row += 1

        row += 1


def _write_chart_sheet(wb, players_data):
    ws = wb.create_sheet("スタート分析グラフ")
    ws.sheet_view.showGridLines = False
    ws.merge_cells("A1:B1")
    tc = ws["A1"]
    tc.value = "6艇 スタート分析グラフ（コース別）"
    tc.font = Font(bold=True, size=13, color="1F4E79")
    tc.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    png = _render_comparison_png(players_data)
    img = XLImage(_png_to_tmp(png))
    ratio = (img.height / img.width) if img.width else (1900 / 1100)
    img.width = 1100
    img.height = int(1100 * ratio)
    ws.add_image(img, "A2")
    ws.column_dimensions["A"].width = 150


def _write_formation_sheet(wb, players_data):
    ws = wb.create_sheet("スタート予想図")
    ws.sheet_view.showGridLines = False
    ws.merge_cells("A1:F1")
    tc = ws["A1"]
    tc.value = "スタート予想図"
    tc.font = Font(bold=True, size=13, color="1F4E79")
    tc.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    center = Alignment(horizontal="center", vertical="center")
    thin = Side(style="thin", color="CCCCCC")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    headers = ["コース", "選手名", "対象R数", "平均ST", "F率", "ST1位率"]
    widths = [8, 12, 10, 10, 8, 10]
    for ci, (h, w) in enumerate(zip(headers, widths), 1):
        cell = ws.cell(row=2, column=ci, value=h)
        cell.fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
        cell.font = Font(bold=True, color="FFFFFF", size=10)
        cell.alignment = center
        cell.border = border
        ws.column_dimensions[get_column_letter(ci)].width = w
    ws.row_dimensions[2].height = 20

    for i, pd in enumerate(players_data):
        course  = pd["course"]
        boat_no = int(pd.get("boat_no", course))
        name    = pd["name"]
        races   = pd["races"]
        subset  = [r for r in races if str(r.get("コース", "")).strip() == str(course)]
        st_vals = [_parse_st(r.get("スタートタイム", "")) for r in subset]
        valid = [v for v in st_vals if v is not None]
        avg_st = sum(valid) / len(valid) if valid else None
        f_count = sum(1 for r in subset
                      if str(r.get("スタートタイム", "")).strip() in ("F", "S0", "S1"))
        f_rate = f_count / len(subset) if subset else 0.0
        st1_count = sum(1 for r in subset if str(r.get("スタート順位", "")).strip() == "1")
        st1_rate = st1_count / len(subset) if subset else 0.0

        r = i + 3
        bg = BOAT_BG.get(boat_no, "AAAAAA")
        fg = BOAT_FG.get(boat_no, "000000")
        values = [
            f"{course}コース/{boat_no}号艇" if boat_no != course else str(course),
            name, len(subset),
            f"{avg_st:.3f}" if avg_st is not None else "—",
            f"{f_rate:.1%}", f"{st1_rate:.1%}",
        ]
        for ci, val in enumerate(values, 1):
            cell = ws.cell(row=r, column=ci, value=val)
            cell.alignment = center
            cell.border = border
            if ci == 1:
                cell.fill = PatternFill(start_color=bg, end_color=bg, fill_type="solid")
                cell.font = Font(bold=True, color=fg)
        ws.row_dimensions[r].height = 18

    png = _render_formation_png(players_data, show_start_line=True, show_labels=True)
    img = XLImage(_png_to_tmp(png))
    img.width = 1100
    img.height = int(1100 * _BG_DISP_H / _BG_DISP_W)
    ws.add_image(img, "A11")


def _write_clean_formation_sheet(wb, players_data, manual_offsets=None):
    ws = wb.create_sheet("スタート配置図")
    ws.sheet_view.showGridLines = False
    ws.merge_cells("A1:F1")
    tc = ws["A1"]
    tc.value = "スタート配置図（伸足補正適用）"
    tc.font = Font(bold=True, size=13, color="1F4E79")
    tc.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    png = _render_formation_png(players_data, show_start_line=False,
                                show_labels=False, manual_offsets=manual_offsets)
    img = XLImage(_png_to_tmp(png))
    img.width = 1100
    img.height = int(1100 * _BG_DISP_H / _BG_DISP_W)
    ws.add_image(img, "A3")
    ws.column_dimensions["A"].width = 10


def _write_performance_sheet(wb, players_data):
    ws = wb.create_sheet("船足評価")
    ws.sheet_view.showGridLines = False
    png = _render_performance_png(players_data)
    img = XLImage(_png_to_tmp(png))
    ratio = (img.height / img.width) if img.width else 0.42
    img.width = 1000
    img.height = int(1000 * ratio)
    ws.add_image(img, "A1")
    ws.column_dimensions["A"].width = 130
