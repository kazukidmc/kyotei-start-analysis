"""
6艇スタート分析 — Android版 (Kivy)
"""
__version__ = "1.0"

import threading
from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, Screen, SlideTransition
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.spinner import Spinner
from kivy.uix.progressbar import ProgressBar
from kivy.uix.widget import Widget
from kivy.uix.popup import Popup
from kivy.graphics import Color, Rectangle, Line, RoundedRectangle
from kivy.clock import Clock
from kivy.metrics import dp, sp
from kivy.core.window import Window

import backend as bk

# ── カラー定数 ────────────────────────────────────────
BG_DARK   = (0.035, 0.165, 0.29, 1)   # #091A49
BG_CARD   = (0.07, 0.22, 0.38, 1)
ACCENT    = (0.18, 0.55, 0.87, 1)
ACCENT_D  = (0.10, 0.40, 0.70, 1)
WHITE     = (1, 1, 1, 1)
TEXT_MUTED= (0.65, 0.76, 0.87, 1)
RED       = (0.91, 0.188, 0.188, 1)
GREEN     = (0.188, 0.627, 0.251, 1)

BOAT_HEX = {
    1: "#CCCCCC", 2: "#222222", 3: "#E83030",
    4: "#1A7ACC", 5: "#E8C000", 6: "#30A040",
}

def _hex_to_rgba(h):
    h = h.lstrip("#")
    r, g, b = int(h[0:2],16)/255, int(h[2:4],16)/255, int(h[4:6],16)/255
    return (r, g, b, 1)

def _boat_rgba(bn):
    return _hex_to_rgba(BOAT_HEX.get(bn, "#AAAAAA"))

def _boat_text_rgba(bn):
    dark = {1, 5}
    return (0, 0, 0, 1) if bn in dark else (1, 1, 1, 1)

# ── ウィジェット部品 ──────────────────────────────────

class RectBg(Widget):
    """背景色を塗るだけのヘルパー"""
    def __init__(self, color, **kw):
        super().__init__(**kw)
        self._color = color
        self.bind(pos=self._redraw, size=self._redraw)
    def _redraw(self, *_):
        self.canvas.before.clear()
        with self.canvas.before:
            Color(*self._color)
            Rectangle(pos=self.pos, size=self.size)

def flat_btn(text, bg=ACCENT, fg=WHITE, font_size=sp(14), height=dp(44), **kw):
    btn = Button(
        text=text,
        size_hint_y=None,
        height=height,
        font_size=font_size,
        background_normal="",
        background_color=bg,
        color=fg,
        **kw,
    )
    return btn

def lbl(text, font_size=sp(13), color=WHITE, bold=False, **kw):
    return Label(text=text, font_size=font_size, color=color, bold=bold,
                 size_hint_y=None, height=dp(32), **kw)

def spinner_widget(values, default, width=dp(64)):
    sp_w = Spinner(
        text=default,
        values=values,
        size_hint=(None, None),
        size=(width, dp(36)),
        font_size=sp(13),
        background_normal="",
        background_color=BG_CARD,
        color=WHITE,
    )
    return sp_w

# ── コース行ウィジェット ──────────────────────────────

class CourseRow(BoxLayout):
    def __init__(self, course: int, **kw):
        super().__init__(orientation="vertical", size_hint_y=None, spacing=dp(4), **kw)
        self.course = course
        self.regno  = None
        self._candidates = []
        self.height = dp(120)

        boat_rgba = _boat_rgba(course)
        boat_text = _boat_text_rgba(course)

        # ── 上段: コースラベル + 選手名検索 ──
        row1 = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(6))

        # コースラベル
        self._course_lbl = Label(
            text=f"{course}コース",
            size_hint=(None, 1), width=dp(68),
            font_size=sp(13), bold=True,
            color=boat_text,
        )
        with self._course_lbl.canvas.before:
            Color(*boat_rgba)
            self._lbl_rect = Rectangle(pos=self._course_lbl.pos,
                                        size=self._course_lbl.size)
        self._course_lbl.bind(pos=self._update_lbl_rect, size=self._update_lbl_rect)

        self.query_input = TextInput(
            hint_text="選手名 or 登録番号",
            multiline=False,
            font_size=sp(13),
            size_hint=(1, 1),
            background_color=BG_CARD,
            foreground_color=WHITE,
            cursor_color=WHITE,
            hint_text_color=(0.5,0.6,0.7,1),
            padding=[dp(8), dp(8)],
        )
        self.search_btn = flat_btn("検索", width=dp(56), size_hint=(None,1),
                                    height=dp(40), font_size=sp(12))
        self.search_btn.bind(on_press=self._on_search)

        row1.add_widget(self._course_lbl)
        row1.add_widget(self.query_input)
        row1.add_widget(self.search_btn)

        # ── 中段: 候補選択 ──
        self.candidate_spinner = Spinner(
            text="← 検索して選択",
            values=[],
            size_hint=(1, None),
            height=dp(36),
            font_size=sp(12),
            background_normal="",
            background_color=(0.1, 0.28, 0.48, 1),
            color=TEXT_MUTED,
        )
        self.candidate_spinner.bind(text=self._on_select)

        # ── 下段: 艇番 / 出足 / 伸足 ──
        row3 = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(8))
        row3.add_widget(lbl("艇番:", font_size=sp(11), color=TEXT_MUTED,
                             size_hint=(None,1), width=dp(36)))
        self.boat_no_sp = spinner_widget([str(i) for i in range(1,7)],
                                          str(course), width=dp(52))
        row3.add_widget(self.boat_no_sp)

        row3.add_widget(lbl("出足:", font_size=sp(11), color=TEXT_MUTED,
                             size_hint=(None,1), width=dp(36)))
        self.de_ashi_sp = spinner_widget([str(i) for i in range(1,6)], "3", width=dp(52))
        row3.add_widget(self.de_ashi_sp)

        row3.add_widget(lbl("伸足:", font_size=sp(11), color=TEXT_MUTED,
                             size_hint=(None,1), width=dp(36)))
        self.nobiashi_sp = spinner_widget([str(i) for i in range(1,6)], "3", width=dp(52))
        row3.add_widget(self.nobiashi_sp)

        self.add_widget(row1)
        self.add_widget(self.candidate_spinner)
        self.add_widget(row3)

        # 背景
        with self.canvas.before:
            Color(*BG_CARD)
            self._bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(6)])
        self.bind(pos=self._upd_bg, size=self._upd_bg)

    def _update_lbl_rect(self, inst, _):
        self._lbl_rect.pos  = inst.pos
        self._lbl_rect.size = inst.size

    def _upd_bg(self, *_):
        self._bg.pos  = self.pos
        self._bg.size = self.size

    def _on_search(self, _):
        query = self.query_input.text.strip()
        if not query:
            return
        import re
        if re.match(r"^\d{4}$", query):
            self.regno = query
            self.candidate_spinner.text = f"{query}（登録番号直接指定）"
            self.candidate_spinner.color = WHITE
            return
        self.search_btn.disabled = True
        self.search_btn.text = "..."

        def task():
            try:
                players = bk.search_player(query)
                Clock.schedule_once(lambda dt: self._show_candidates(players))
            except Exception as e:
                Clock.schedule_once(lambda dt: self._show_error(str(e)))
            finally:
                Clock.schedule_once(lambda dt: self._search_done())

        threading.Thread(target=task, daemon=True).start()

    def _show_candidates(self, players):
        if not players:
            self.candidate_spinner.values = ["見つかりません"]
            self.candidate_spinner.text   = "見つかりません"
            return
        self._candidates = players
        self.candidate_spinner.values = [f"{p['regno']} {p['name']}" for p in players]
        self.candidate_spinner.text   = self.candidate_spinner.values[0]
        self._on_select(None, self.candidate_spinner.text)

    def _show_error(self, msg):
        self.candidate_spinner.text = f"エラー: {msg[:30]}"

    def _search_done(self):
        self.search_btn.disabled = False
        self.search_btn.text = "検索"

    def _on_select(self, _, text):
        import re
        m = re.match(r"^(\d{4})", text)
        if m:
            self.regno = m.group(1)
            self.candidate_spinner.color = WHITE

    def get_data(self):
        return {
            "course":   self.course,
            "regno":    self.regno,
            "boat_no":  int(self.boat_no_sp.text),
            "de_ashi":  int(self.de_ashi_sp.text),
            "nobiashi": int(self.nobiashi_sp.text),
        }

    def is_ready(self):
        return self.regno is not None

# ── 入力スクリーン ────────────────────────────────────

class InputScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        with self.canvas.before:
            Color(*BG_DARK)
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=lambda *_: setattr(self._bg, 'pos', self.pos),
                  size=lambda *_: setattr(self._bg, 'size', self.size))

        root = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(6))

        # ヘッダー
        hdr = Label(
            text="[b]6艇 スタート分析[/b]",
            markup=True,
            font_size=sp(18),
            size_hint_y=None,
            height=dp(48),
            color=WHITE,
        )
        root.add_widget(hdr)

        # 取得件数
        cnt_row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        cnt_row.add_widget(lbl("取得データ数:", font_size=sp(13), color=TEXT_MUTED,
                                size_hint=(None,1), width=dp(96)))
        self.count_input = TextInput(
            text="100",
            input_filter="int",
            multiline=False,
            font_size=sp(14),
            background_color=BG_CARD,
            foreground_color=WHITE,
            cursor_color=WHITE,
            size_hint=(None, 1),
            width=dp(72),
            padding=[dp(8), dp(8)],
        )
        cnt_row.add_widget(self.count_input)
        cnt_row.add_widget(Label())
        root.add_widget(cnt_row)

        # コース行スクロール
        sv = ScrollView(size_hint=(1, 1))
        grid = BoxLayout(orientation="vertical", spacing=dp(8),
                          size_hint_y=None, padding=[0, dp(4)])
        grid.bind(minimum_height=grid.setter("height"))

        self._rows = []
        for c in range(1, 7):
            row = CourseRow(course=c)
            self._rows.append(row)
            grid.add_widget(row)

        sv.add_widget(grid)
        root.add_widget(sv)

        # 実行ボタン
        self.run_btn = flat_btn(
            "スタート分析を実行",
            bg=ACCENT, height=dp(52), font_size=sp(15),
        )
        self.run_btn.bind(on_press=self._on_run)
        root.add_widget(self.run_btn)

        self.add_widget(root)

    def _on_run(self, _):
        missing = [str(r.course) for r in self._rows if not r.is_ready()]
        if missing:
            popup = Popup(
                title="入力不足",
                content=Label(text=f"{', '.join(missing)}コースが未設定です"),
                size_hint=(0.8, 0.3),
            )
            popup.open()
            return

        boat_nos = [r.get_data()["boat_no"] for r in self._rows]
        if len(set(boat_nos)) != 6:
            popup = Popup(
                title="艇番重複",
                content=Label(text="艇番が重複しています"),
                size_hint=(0.8, 0.3),
            )
            popup.open()
            return

        try:
            target = int(self.count_input.text)
        except ValueError:
            target = 100

        players_input = [r.get_data() for r in self._rows]
        app = App.get_running_app()
        app.root.current = "progress"
        progress_screen = app.root.get_screen("progress")
        progress_screen.start_analysis(players_input, target)

# ── 進捗スクリーン ─────────────────────────────────────

class ProgressScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        with self.canvas.before:
            Color(*BG_DARK)
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=lambda *_: setattr(self._bg, 'pos', self.pos),
                  size=lambda *_: setattr(self._bg, 'size', self.size))

        root = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(10))

        root.add_widget(Label(
            text="[b]データ取得中...[/b]", markup=True,
            font_size=sp(16), size_hint_y=None, height=dp(44), color=WHITE,
        ))

        self.pb = ProgressBar(max=100, value=0, size_hint_y=None, height=dp(16))
        root.add_widget(self.pb)

        self.pb_label = Label(
            text="0 / 100", font_size=sp(12), color=TEXT_MUTED,
            size_hint_y=None, height=dp(24),
        )
        root.add_widget(self.pb_label)

        sv = ScrollView(size_hint=(1, 1))
        self.log_label = Label(
            text="",
            font_size=sp(11),
            color=TEXT_MUTED,
            size_hint_y=None,
            halign="left",
            valign="top",
            text_size=(Window.width - dp(24), None),
        )
        self.log_label.bind(texture_size=self.log_label.setter("size"))
        sv.add_widget(self.log_label)
        root.add_widget(sv)

        self.add_widget(root)
        self._log_lines = []

    def start_analysis(self, players_input: list, target: int):
        self._log_lines = []
        self.log_label.text = ""
        self.pb.value = 0
        self.pb_label.text = f"0 / {target}"
        self._players_data = []
        self._target = target
        self._players_input = players_input
        self._total = len(players_input)
        self._done  = 0

        threading.Thread(target=self._run, daemon=True).start()

    def _log(self, msg):
        self._log_lines.append(msg)
        Clock.schedule_once(lambda dt: setattr(
            self.log_label, "text", "\n".join(self._log_lines[-60:])
        ))

    def _progress(self, cur, tot):
        pct = min(100, int(cur / max(tot, 1) * 100))
        Clock.schedule_once(lambda dt: self._update_pb(pct, cur, tot))

    def _update_pb(self, pct, cur, tot):
        self.pb.value = pct
        self.pb_label.text = f"{cur} / {tot}"

    def _run(self):
        try:
            for p in self._players_input:
                course  = p["course"]
                regno   = p["regno"]
                boat_no = p["boat_no"]
                de_ashi = p["de_ashi"]
                nobiashi= p["nobiashi"]

                races, name = bk.collect_recent_races(
                    regno, self._target, course,
                    log_cb=self._log,
                    progress_cb=self._progress,
                )
                self._players_data.append({
                    "course":   course,
                    "boat_no":  boat_no,
                    "name":     name,
                    "regno":    regno,
                    "races":    races,
                    "de_ashi":  de_ashi,
                    "nobiashi": nobiashi,
                })
                self._done += 1
                pct = int(self._done / self._total * 100)
                Clock.schedule_once(lambda dt, p=pct: setattr(self.pb, "value", p))

            self._log("✓ 分析完了！")
            Clock.schedule_once(lambda dt: self._go_result())
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            self._log(f"エラー: {e}\n{tb}")

    def _go_result(self):
        boat_info = bk.collect_boat_info(self._players_data)
        app = App.get_running_app()
        result_screen = app.root.get_screen("result")
        result_screen.load(self._players_data, boat_info)
        app.root.current = "result"

# ── 成形図ウィジェット ────────────────────────────────

class FormationWidget(Widget):
    WATER_COLOR  = (0.29, 0.66, 0.82, 1)
    LINE_COLOR   = (1, 1, 1, 0.45)
    START_COLOR  = (1, 0.13, 0.13, 0.9)

    def __init__(self, **kw):
        super().__init__(**kw)
        self._boat_info = []
        self.bind(pos=self._redraw, size=self._redraw)

    def set_data(self, boat_info):
        self._boat_info = boat_info
        self._redraw()

    def _redraw(self, *_):
        self.canvas.clear()
        if not self._boat_info or self.width < 10:
            return

        info = self._boat_info
        _BOAT_L = 2.9
        _LANE_H = 2.8

        # データ座標範囲
        sterns = [b["stern_x"] for b in info]
        bows   = [b["bow_x"]   for b in info]
        x_min = min(sterns) - 1.0
        x_max = max(max(bows) + 2.0, 2.0)
        y_max =  _LANE_H * 0.6
        y_min = -5 * _LANE_H - _LANE_H * 0.6

        W, H = self.width, self.height

        def dx(mx):
            return self.x + (mx - x_min) / (x_max - x_min) * W

        def dy(my):
            return self.y + (1.0 - (my - y_min) / (y_max - y_min)) * H

        with self.canvas:
            # 水面背景
            Color(*self.WATER_COLOR)
            Rectangle(pos=self.pos, size=self.size)

            # レーン区切り線
            Color(*self.LINE_COLOR)
            for c in range(1, 8):
                yb = bk._course_y(c) + _LANE_H / 2
                Line(points=[self.x, dy(yb), self.x + W, dy(yb)], width=dp(0.8))

            # スタートライン
            Color(*self.START_COLOR)
            sx = dx(0)
            Line(points=[sx, self.y, sx, self.y + H], width=dp(2))

            # 艇を描画
            for b in info:
                boat_no  = b.get("boat_no", b["course"])
                stern_x  = b["stern_x"]
                bow_x    = b["bow_x"]
                y_center = b["y_center"]

                px_left  = dx(stern_x)
                px_right = dx(bow_x)
                px_top   = dy(y_center + 0.7)
                px_bot   = dy(y_center - 0.7)
                bw = max(px_right - px_left, dp(20))
                bh = max(px_top - px_bot, dp(12))

                # 船体 (角丸長方形)
                Color(*_boat_rgba(boat_no))
                RoundedRectangle(
                    pos=(px_left, px_bot),
                    size=(bw, bh),
                    radius=[dp(4)],
                )

                # 艇番テキスト
                Color(*_boat_text_rgba(boat_no))
                from kivy.core.text import Label as CoreLabel
                cl = CoreLabel(text=str(boat_no), font_size=sp(14), bold=True)
                cl.refresh()
                tx = cl.texture
                if tx:
                    Rectangle(
                        texture=tx,
                        pos=(px_left + bw/2 - tx.width/2,
                             px_bot  + bh/2 - tx.height/2),
                        size=tx.size,
                    )

                # 平均ST表示
                avg_st = b.get("avg_st", 0)
                if avg_st < 0.98:
                    Color(1, 1, 1, 0.9)
                    st_cl = CoreLabel(
                        text=f".{round(avg_st * 1000):03d}",
                        font_size=sp(9),
                    )
                    st_cl.refresh()
                    st_tx = st_cl.texture
                    if st_tx:
                        Rectangle(
                            texture=st_tx,
                            pos=(px_right - st_tx.width - dp(2),
                                 px_bot + dp(2)),
                            size=st_tx.size,
                        )

# ── 結果スクリーン ─────────────────────────────────────

class ResultScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        with self.canvas.before:
            Color(*BG_DARK)
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=lambda *_: setattr(self._bg, 'pos', self.pos),
                  size=lambda *_: setattr(self._bg, 'size', self.size))

        root = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(6))

        hdr = BoxLayout(size_hint_y=None, height=dp(44))
        back_btn = flat_btn("← 戻る", bg=ACCENT_D, size_hint=(None,1), width=dp(80))
        back_btn.bind(on_press=lambda _: setattr(App.get_running_app().root, "current", "input"))
        hdr.add_widget(back_btn)
        hdr.add_widget(Label(text="[b]分析結果[/b]", markup=True,
                              font_size=sp(16), color=WHITE))
        root.add_widget(hdr)

        # 成形図
        self.formation = FormationWidget(size_hint=(1, None), height=dp(200))
        with self.formation.canvas.before:
            Color(0, 0, 0, 0.3)
            self._form_border = RoundedRectangle(
                pos=self.formation.pos, size=self.formation.size, radius=[dp(6)])
        self.formation.bind(
            pos=lambda *_: setattr(self._form_border, 'pos', self.formation.pos),
            size=lambda *_: setattr(self._form_border, 'size', self.formation.size),
        )
        root.add_widget(self.formation)

        # 統計テーブルスクロール
        sv = ScrollView(size_hint=(1, 1))
        self.stats_grid = GridLayout(
            cols=7, size_hint_y=None, spacing=dp(2), padding=[0, dp(4)],
        )
        self.stats_grid.bind(minimum_height=self.stats_grid.setter("height"))
        sv.add_widget(self.stats_grid)
        root.add_widget(sv)

        self.add_widget(root)

    def load(self, players_data, boat_info):
        self.formation.set_data(boat_info)
        self._build_stats(boat_info)

    def _stat_cell(self, text, bg=BG_CARD, fg=WHITE, bold=False, font_size=None):
        lbl = Label(
            text=f"[b]{text}[/b]" if bold else text,
            markup=True,
            font_size=font_size or sp(11),
            color=fg,
            size_hint_y=None,
            height=dp(32),
            halign="center",
            valign="middle",
        )
        lbl.text_size = (None, dp(32))
        with lbl.canvas.before:
            Color(*bg)
            lbl._bg_rect = Rectangle(pos=lbl.pos, size=lbl.size)
        lbl.bind(
            pos=lambda inst, _: setattr(inst._bg_rect, 'pos', inst.pos),
            size=lambda inst, _: setattr(inst._bg_rect, 'size', inst.size),
        )
        return lbl

    def _build_stats(self, boat_info):
        self.stats_grid.clear_widgets()

        headers = ["艇", "選手名", "平均ST", "F率", "ST1位率", "1着率", "N"]
        for h in headers:
            self.stats_grid.add_widget(
                self._stat_cell(h, bg=(0.1,0.2,0.35,1), bold=True)
            )

        for b in boat_info:
            boat_no = b.get("boat_no", b["course"])
            bg = _boat_rgba(boat_no)
            fg = _boat_text_rgba(boat_no)

            self.stats_grid.add_widget(self._stat_cell(str(boat_no), bg=bg, fg=fg, bold=True))
            short = b["name"][:5] if len(b["name"]) > 5 else b["name"]
            self.stats_grid.add_widget(self._stat_cell(short, bg=BG_CARD))

            avg_st = b["avg_st"]
            st_txt = f".{round(avg_st*1000):03d}" if b["valid_n"] > 0 else "―"
            self.stats_grid.add_widget(self._stat_cell(st_txt, bg=BG_CARD))

            f_rate = b["f_rate"]
            f_color = (RED[0], RED[1], RED[2], 1) if f_rate >= 0.05 else WHITE
            self.stats_grid.add_widget(self._stat_cell(f"{f_rate:.1%}", bg=BG_CARD, fg=f_color))

            self.stats_grid.add_widget(
                self._stat_cell(f"{b['st1_rate']:.1%}", bg=BG_CARD))
            self.stats_grid.add_widget(
                self._stat_cell(f"{b['win_rate']:.1%}", bg=BG_CARD))
            self.stats_grid.add_widget(
                self._stat_cell(str(b["n"]), bg=BG_CARD, fg=TEXT_MUTED))


# ── アプリ本体 ────────────────────────────────────────

class KyoteiApp(App):
    def build(self):
        Window.clearcolor = BG_DARK

        sm = ScreenManager(transition=SlideTransition())
        sm.add_widget(InputScreen(name="input"))
        sm.add_widget(ProgressScreen(name="progress"))
        sm.add_widget(ResultScreen(name="result"))
        return sm


if __name__ == "__main__":
    KyoteiApp().run()
