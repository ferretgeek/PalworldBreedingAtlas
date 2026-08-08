from __future__ import annotations

import os
import queue
import subprocess
import threading
import traceback
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import save_parser
from .updater import CURRENT_VERSION


DISCLAIMER = """《幻兽帕鲁配种助手》使用声明

· 本工具只读本机 Palworld Steam 存档，不修改游戏文件。
· 存档和拥有列表不会上传；软件默认且永久离线运行。
· 数据版本、来源和校验状态会显示在主界面，请以当前标注为准。
· 本工具是免费、非商用的粉丝作品，与 Pocketpair、Epic、RAD 无关。
· 帕鲁名称、形象和游戏数据相关权利归其各自权利人所有。

点“确定”表示已阅读并同意，随后即可读取存档。"""

BG = "#060d18"
CARD = "#0f1a2c"
CARD_SOFT = "#122136"
HEADER = "#0a1626"
HEADER_SOFT = "#12263c"
TEXT = "#eef5ff"
SUBTEXT = "#92a6c4"
BORDER = "#263950"
BORDER_STRONG = "#3a5578"
GOLD = "#f2b950"
GOLD_STRONG = "#ffd98a"
GOLD_DARK = "#c98f2b"
GOLD_INK = "#271a02"
ACCENT = "#5fd9e8"
ACCENT_DARK = "#2fa8b8"
ACCENT_INK = "#03181d"
SUCCESS = "#6fe3a5"
WARNING = "#ffd98a"
DANGER = "#ff8f8a"
VIOLET = "#a78bfa"
LOG_BG = "#040a13"
LOG_FG = "#bfe9ef"


def game_running() -> bool:
    """检查 Palworld 进程是否正在运行。"""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    for executable in ("Palworld-Win64-Shipping.exe", "Palworld.exe"):
        try:
            result = subprocess.run(
                ["tasklist", "/fi", f"imagename eq {executable}"],
                capture_output=True,
                creationflags=flags,
                check=False,
                timeout=4,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if executable.lower().encode() in result.stdout.lower():
            return True
    return False


class GenerationGate:
    """为后台任务提供 generation 和协作式取消。"""

    def __init__(self) -> None:
        self.generation = 0
        self.cancel_event = threading.Event()
        self.cancel_event.set()

    def start(self) -> tuple[int, threading.Event]:
        self.cancel_event.set()
        self.generation += 1
        self.cancel_event = threading.Event()
        return self.generation, self.cancel_event

    def cancel(self, *, invalidate: bool = True) -> None:
        self.cancel_event.set()
        if invalidate:
            self.generation += 1

    def is_current(self, generation: int) -> bool:
        return generation == self.generation and not self.cancel_event.is_set()


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(f"帕鲁配种助手 v{CURRENT_VERSION}")
        self.root.minsize(760, 610)
        self.root.configure(background=BG)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.bind("<Escape>", self._on_escape)

        icon = save_parser.asset_dir() / "palicon.ico"
        if icon.is_file():
            try:
                self.root.iconbitmap(str(icon))
            except tk.TclError:
                pass

        width, height = 940, 800
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = max((screen_width - width) // 2, 0)
        y = max((screen_height - height) // 2, 0)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

        self.events: queue.Queue[dict] = queue.Queue()
        self.scan_gate = GenerationGate()
        self.analysis_gate = GenerationGate()
        self.poll_after_id: str | None = None
        self.closing = False
        self.state = "idle"

        self.saves: list[dict] = []
        self.selected_index = -1
        self.pending_selection_key = ""
        self.first_scan = True

        self.config_path = save_parser.output_dir() / ".palhelper_cfg.json"
        self.config = self._read_config()
        self.last_save = self._normalized_config_path("last_save")
        self.last_html = self._normalized_config_path("last_html")
        self.web_asset_id = ""
        self.agreed_before = bool(self.config.get("agreed", False))
        self.first_scan = not bool(self.config.get("scanned", False))

        self._configure_style()
        self._build_ui()
        # 先把窗口画出来，再做耗时的初始化，避免首次启动看似没有反应
        self.root.update_idletasks()
        self.root.update()

        save_parser.cleanup_staged_bundles()
        self.web_asset_id = save_parser.web_asset_fingerprint()
        if (
            self.config.get("last_html_version") != CURRENT_VERSION
            or self.config.get("last_html_asset_id") != self.web_asset_id
        ):
            self.last_html = ""
            self.config["last_html"] = ""
            self.config["last_html_version"] = CURRENT_VERSION
            self.config["last_html_asset_id"] = self.web_asset_id
            self._write_config()
            self._update_controls()

        self._update_data_badge()
        self.poll_after_id = self.root.after(50, self._drain_events)
        self.root.after(150, self._deferred_disclaimer)
        self.root.after(320, self._deferred_initial_scan)

    def _deferred_disclaimer(self) -> None:
        if self.closing:
            return
        self._show_disclaimer()

    def _deferred_initial_scan(self) -> None:
        if self.closing or self.state != "idle":
            return
        self.refresh_saves(deep=False)

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        themes = style.theme_names()
        if "clam" in themes:
            style.theme_use("clam")
        style.configure(
            "TButton",
            font=("Microsoft YaHei UI", 9),
            padding=(12, 8),
            background=CARD_SOFT,
            foreground=TEXT,
            bordercolor=BORDER,
            lightcolor=CARD_SOFT,
            darkcolor=BORDER,
            focuscolor=ACCENT,
        )
        style.map(
            "TButton",
            background=[("active", "#1a2c46"), ("pressed", "#101f33")],
            foreground=[("disabled", "#4d617c"), ("!disabled", TEXT)],
            bordercolor=[("focus", ACCENT), ("active", BORDER_STRONG)],
        )
        style.configure(
            "Primary.TButton",
            font=("Microsoft YaHei UI", 12, "bold"),
            padding=(16, 13),
            background=GOLD,
            foreground=GOLD_INK,
            bordercolor=GOLD_DARK,
            lightcolor=GOLD_STRONG,
            darkcolor=GOLD_DARK,
            focuscolor=GOLD_STRONG,
        )
        style.map(
            "Primary.TButton",
            background=[("active", GOLD_STRONG), ("pressed", GOLD_DARK), ("disabled", "#4a3b1e")],
            foreground=[("disabled", "#8a7a55"), ("!disabled", GOLD_INK)],
            bordercolor=[("focus", GOLD_STRONG), ("active", GOLD_STRONG)],
        )
        style.configure(
            "Compact.TButton",
            font=("Microsoft YaHei UI", 9),
            padding=(9, 6),
            background=CARD_SOFT,
            foreground=SUBTEXT,
            bordercolor=BORDER,
            lightcolor=CARD_SOFT,
            darkcolor=BORDER,
        )
        style.map(
            "Compact.TButton",
            background=[("active", "#1a2c46"), ("pressed", "#101f33")],
            foreground=[("active", TEXT), ("disabled", "#4d617c")],
            bordercolor=[("focus", ACCENT), ("active", BORDER_STRONG)],
        )
        style.configure(
            "TCombobox",
            padding=8,
            fieldbackground=CARD_SOFT,
            background=CARD_SOFT,
            foreground=TEXT,
            bordercolor=BORDER,
            lightcolor=CARD_SOFT,
            darkcolor=BORDER,
            arrowcolor=ACCENT,
            selectbackground="#1a2c46",
            selectforeground=TEXT,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", CARD_SOFT), ("disabled", "#0c1523")],
            foreground=[("readonly", TEXT), ("disabled", "#4d617c")],
            bordercolor=[("focus", ACCENT), ("active", BORDER_STRONG)],
        )
        style.configure(
            "Horizontal.TProgressbar",
            troughcolor="#0c1523",
            background=GOLD,
            lightcolor=GOLD_STRONG,
            darkcolor=GOLD_DARK,
            bordercolor=BORDER,
        )
        style.configure(
            "Vertical.TScrollbar",
            background=CARD_SOFT,
            troughcolor=LOG_BG,
            bordercolor=LOG_BG,
            arrowcolor=SUBTEXT,
            lightcolor=CARD_SOFT,
            darkcolor=CARD_SOFT,
        )
        style.map(
            "Vertical.TScrollbar",
            background=[("active", "#22385a")],
        )
        self.root.option_add("*TCombobox*Listbox*Background", CARD_SOFT)
        self.root.option_add("*TCombobox*Listbox*Foreground", TEXT)
        self.root.option_add("*TCombobox*Listbox*selectBackground", "#1a2c46")
        self.root.option_add("*TCombobox*Listbox*selectForeground", GOLD_STRONG)
        self.root.option_add("*TCombobox*Listbox*Font", ("Microsoft YaHei UI", 9))

    def _load_launcher_image(self, name: str) -> tk.PhotoImage | None:
        path = save_parser.asset_dir() / "images" / "launcher" / name
        if not path.is_file():
            return None
        try:
            return tk.PhotoImage(file=str(path))
        except tk.TclError:
            return None

    def _build_ui(self) -> None:
        self._launcher_images: dict[str, tk.PhotoImage] = {}
        header_bg = self._load_launcher_image("header_bg.png")
        mascot_lamball = self._load_launcher_image("mascot_lamball.png")
        mascot_pengullet = self._load_launcher_image("mascot_pengullet.png")
        mascot_jetragon = self._load_launcher_image("mascot_petallia.png")
        for name, image in (
            ("header_bg", header_bg),
            ("lamball", mascot_lamball),
            ("pengullet", mascot_pengullet),
            ("jetragon", mascot_jetragon),
        ):
            if image is not None:
                self._launcher_images[name] = image

        outer = tk.Frame(self.root, bg=BG, padx=22, pady=18)
        outer.pack(fill="both", expand=True)
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_rowconfigure(3, weight=1)

        # ---------- 幻夜横幅 ----------
        header_height = 118
        header = tk.Canvas(
            outer,
            height=header_height,
            bg=HEADER,
            highlightthickness=1,
            highlightbackground=BORDER_STRONG,
            bd=0,
        )
        header.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        if header_bg is not None:
            self._header_bg_item = header.create_image(0, 0, anchor="nw", image=header_bg)
            def _center_header_bg(event: tk.Event) -> None:
                header.coords(
                    self._header_bg_item,
                    (event.width - header_bg.width()) // 2,
                    (event.height - header_bg.height()) // 2,
                )
            header.bind("<Configure>", _center_header_bg)
        header.create_text(
            26, 40, anchor="w", text="帕鲁配种助手",
            fill=GOLD_STRONG, font=("Microsoft YaHei UI", 21, "bold"),
        )
        header.create_text(
            27, 78, anchor="w",
            text="只读解析本机存档，离线生成配种路线。",
            fill=SUBTEXT, font=("Microsoft YaHei UI", 10),
        )
        if mascot_lamball is not None:
            mascot_item = header.create_image(
                0, 0, anchor="ne", image=mascot_lamball
            )
            def _place_mascot(event: tk.Event) -> None:
                header.coords(mascot_item, event.width - 14, 4)
            header.bind("<Configure>", _place_mascot)
        self.data_badge_var = tk.StringVar(value="正在读取数据版本…")
        badge_holder = tk.Frame(
            header, bg=HEADER_SOFT, highlightbackground=BORDER_STRONG, highlightthickness=1
        )
        self.data_badge = tk.Label(
            badge_holder,
            textvariable=self.data_badge_var,
            bg=HEADER_SOFT,
            fg=ACCENT,
            padx=12,
            pady=7,
            font=("Microsoft YaHei UI", 9, "bold"),
        )
        self.data_badge.pack()
        badge_holder.place(relx=1.0, x=-158, y=18, anchor="ne")

        # ---------- 存档卡片 ----------
        save_card = tk.Frame(
            outer,
            bg=CARD,
            highlightbackground=BORDER,
            highlightthickness=1,
            padx=16,
            pady=14,
        )
        save_card.grid(row=1, column=0, sticky="ew")
        save_card.grid_columnconfigure(0, weight=1)

        save_header = tk.Frame(save_card, bg=CARD)
        save_header.grid(row=0, column=0, sticky="ew")
        save_header.grid_columnconfigure(0, weight=1)
        tk.Label(
            save_header,
            text="选择存档",
            bg=CARD,
            fg=GOLD_STRONG,
            font=("Microsoft YaHei UI", 12, "bold"),
        ).grid(row=0, column=0, sticky="w")
        self.save_status_var = tk.StringVar(value="准备扫描")
        self.save_status_label = tk.Label(
            save_header,
            textvariable=self.save_status_var,
            bg=CARD,
            fg=SUBTEXT,
            font=("Microsoft YaHei UI", 9),
        )
        self.save_status_label.grid(row=0, column=1, sticky="e")
        if mascot_pengullet is not None:
            tk.Label(
                save_header, image=mascot_pengullet, bg=CARD, borderwidth=0
            ).grid(row=0, column=2, sticky="e", padx=(10, 0))

        list_frame = tk.Frame(save_card, bg=CARD)
        list_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        list_frame.grid_columnconfigure(0, weight=1)
        self.save_list_canvas = tk.Canvas(
            list_frame, bg=CARD, height=158, highlightthickness=0, bd=0
        )
        self.save_list_canvas.grid(row=0, column=0, sticky="ew")
        save_scroll = ttk.Scrollbar(
            list_frame, orient="vertical", command=self.save_list_canvas.yview
        )
        save_scroll.grid(row=0, column=1, sticky="ns", padx=(6, 0))
        self.save_list_canvas.configure(yscrollcommand=save_scroll.set)
        self.save_list_inner = tk.Frame(self.save_list_canvas, bg=CARD)
        self._save_list_window = self.save_list_canvas.create_window(
            (0, 0), anchor="nw", window=self.save_list_inner
        )
        self.save_list_inner.bind(
            "<Configure>",
            lambda _e: self.save_list_canvas.configure(
                scrollregion=self.save_list_canvas.bbox("all")
            ),
        )
        self.save_list_canvas.bind(
            "<Configure>",
            lambda e: self.save_list_canvas.itemconfigure(
                self._save_list_window, width=e.width
            ),
        )

        def _save_wheel(event: tk.Event) -> None:
            self.save_list_canvas.yview_scroll(int(-event.delta / 120), "units")

        self._save_wheel_handler = _save_wheel
        self.save_list_canvas.bind("<MouseWheel>", _save_wheel)
        self.save_list_inner.bind("<MouseWheel>", _save_wheel)
        self.save_cards: list[tk.Frame] = []

        self.save_detail_var = tk.StringVar(value="尚未选择存档。")
        self.save_detail = tk.Label(
            save_card,
            textvariable=self.save_detail_var,
            bg=CARD,
            fg=SUBTEXT,
            justify="left",
            anchor="w",
            wraplength=760,
            font=("Microsoft YaHei UI", 9),
        )
        self.save_detail.grid(row=2, column=0, sticky="ew", pady=(8, 0))

        actions = tk.Frame(save_card, bg=CARD)
        actions.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self.browse_button = ttk.Button(
            actions, text="手动选择", command=self.browse, style="Compact.TButton"
        )
        self.browse_button.pack(side="left")
        self.refresh_button = ttk.Button(
            actions,
            text="刷新默认位置",
            command=lambda: self.refresh_saves(deep=False),
            style="Compact.TButton",
        )
        self.refresh_button.pack(side="left", padx=(8, 0))
        self.deep_button = ttk.Button(
            actions,
            text="深度搜索",
            command=self._deep_button_action,
            style="Compact.TButton",
        )
        self.deep_button.pack(side="left", padx=(8, 0))
        self.open_dir_button = ttk.Button(
            actions,
            text="存档目录",
            command=self.open_save_dir,
            style="Compact.TButton",
            state="disabled",
        )
        self.open_dir_button.pack(side="left", padx=(8, 0))
        ttk.Button(
            actions,
            text="使用声明",
            command=lambda: self._show_disclaimer(force=True),
            style="Compact.TButton",
        ).pack(side="right")

        # ---------- 操作卡片 ----------
        operation_card = tk.Frame(
            outer,
            bg=CARD,
            highlightbackground=GOLD_DARK,
            highlightthickness=1,
            padx=18,
            pady=15,
        )
        operation_card.grid(row=2, column=0, sticky="ew", pady=12)
        operation_card.grid_columnconfigure(0, weight=1)
        self.run_button = ttk.Button(
            operation_card,
            text="请先选择有效存档",
            command=self._primary_action,
            style="Primary.TButton",
            state="disabled",
        )
        self.run_button.grid(row=0, column=0, sticky="ew")
        self.progress = ttk.Progressbar(operation_card, mode="indeterminate")
        self.progress.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self.operation_status_var = tk.StringVar(value="不会修改或上传任何存档文件。")
        self.operation_status = tk.Label(
            operation_card,
            textvariable=self.operation_status_var,
            bg=CARD,
            fg=SUBTEXT,
            anchor="w",
            font=("Microsoft YaHei UI", 9),
        )
        self.operation_status.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.warn_game_var = tk.BooleanVar(
            value=not bool(self.config.get("skip_game_running_warning"))
        )
        self.warn_game_check = tk.Checkbutton(
            operation_card,
            text="读取存档前提醒我《幻兽帕鲁》正在运行",
            variable=self.warn_game_var,
            command=self._toggle_warn_game,
            bg=CARD,
            fg=SUBTEXT,
            activebackground=CARD,
            activeforeground=TEXT,
            selectcolor=CARD_SOFT,
            anchor="w",
            font=("Microsoft YaHei UI", 8),
        )
        self.warn_game_check.grid(row=3, column=0, sticky="w", pady=(4, 0))

        # ---------- 运行记录 ----------
        log_card = tk.Frame(
            outer,
            bg=CARD,
            highlightbackground=BORDER,
            highlightthickness=1,
            padx=12,
            pady=12,
        )
        log_card.grid(row=3, column=0, sticky="nsew")
        log_card.grid_columnconfigure(0, weight=1)
        log_card.grid_rowconfigure(1, weight=1)

        log_header = tk.Frame(log_card, bg=CARD)
        log_header.grid(row=0, column=0, sticky="ew", pady=(0, 9))
        log_header.grid_columnconfigure(0, weight=1)
        log_title = tk.Frame(log_header, bg=CARD)
        log_title.grid(row=0, column=0, sticky="w")
        if mascot_jetragon is not None:
            tk.Label(log_title, image=mascot_jetragon, bg=CARD, borderwidth=0).pack(
                side="left", padx=(0, 8)
            )
        tk.Label(
            log_title,
            text="运行记录",
            bg=CARD,
            fg=GOLD_STRONG,
            font=("Microsoft YaHei UI", 11, "bold"),
        ).pack(side="left")
        self.reopen_button = ttk.Button(
            log_header,
            text="最近网页",
            command=self.reopen_html,
            style="Compact.TButton",
        )
        self.reopen_button.grid(row=0, column=1, padx=(8, 0))
        ttk.Button(
            log_header,
            text="输出目录",
            command=self.open_output_dir,
            style="Compact.TButton",
        ).grid(row=0, column=2, padx=(8, 0))
        ttk.Button(
            log_header,
            text="复制日志",
            command=self.copy_log,
            style="Compact.TButton",
        ).grid(row=0, column=3, padx=(8, 0))
        ttk.Button(
            log_header,
            text="清空",
            command=self.clear_log,
            style="Compact.TButton",
        ).grid(row=0, column=4, padx=(8, 0))

        log_frame = tk.Frame(log_card, bg=LOG_BG, highlightbackground=BORDER, highlightthickness=1)
        log_frame.grid(row=1, column=0, sticky="nsew")
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(0, weight=1)
        self.log_box = tk.Text(
            log_frame,
            width=1,
            height=8,
            wrap="word",
            background=LOG_BG,
            foreground=LOG_FG,
            insertbackground=GOLD_STRONG,
            selectbackground="#22385a",
            borderwidth=0,
            padx=12,
            pady=10,
            font=("Cascadia Mono", 9),
            state="disabled",
        )
        scrollbar = ttk.Scrollbar(
            log_frame, orient="vertical", command=self.log_box.yview
        )
        self.log_box.configure(yscrollcommand=scrollbar.set)
        self.log_box.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        self._update_controls()

    def _update_data_badge(self) -> None:
        try:
            info = save_parser.data_status()
            verified = info.get("verified")
            version = info.get("version") or "未标注"
            count = info.get("palCount") or 0
            build = info.get("buildId")
            text = (
                f"游戏数据 {version} · {count} 只 · 已核验"
                if verified
                else f"数据待核验 · {count} 只"
            )
            if build:
                text += f" · build {build}"
            self.data_badge_var.set(text)
            if not verified:
                self.data_badge.configure(bg="#3d2f10", fg=GOLD_STRONG)
        except Exception as exc:
            self.data_badge_var.set("数据状态读取失败")
            self.data_badge.configure(bg="#402022", fg=DANGER)
            self._log(f"[数据] 无法读取版本信息：{exc}")

    def _read_config(self) -> dict:
        return save_parser.read_json_object(self.config_path)

    def _normalized_config_path(self, key: str) -> str:
        raw = self.config.get(key)
        if not isinstance(raw, str) or not raw.strip():
            return ""
        normalized = save_parser.normalize_path(raw)
        if normalized != raw:
            self.config[key] = normalized
            self._write_config()
        return normalized

    def _write_config(self) -> None:
        try:
            save_parser.atomic_write_json(self.config_path, self.config)
        except OSError:
            if hasattr(self, "log_box"):
                self._log("[设置] 配置无法保存，本次运行仍可继续。")

    def _save_config(self, **values: object) -> None:
        self.config.update(values)
        self._write_config()

    def _show_disclaimer(self, force: bool = False) -> None:
        if self.agreed_before and not force:
            self._log("欢迎回来，软件将保持离线并只读访问存档。")
            return
        agreed = messagebox.askokcancel("使用声明", DISCLAIMER, parent=self.root)
        if agreed:
            self.agreed_before = True
            self._save_config(agreed=True)
            self._log("已确认使用声明。")
        elif not self.agreed_before:
            self._log("尚未同意使用声明；可以搜索存档，但不能读取。")
        self._update_controls()

    def _set_state(self, state: str, message: str, tone: str = "normal") -> None:
        previous = self.state
        self.state = state
        self.operation_status_var.set(message)
        color = {
            "normal": SUBTEXT,
            "success": SUCCESS,
            "warning": WARNING,
            "error": DANGER,
        }.get(tone, SUBTEXT)
        self.operation_status.configure(fg=color)
        if state in {"scanning", "analyzing"} and previous not in {
            "scanning",
            "analyzing",
        }:
            self.progress.start(12)
        elif state not in {"scanning", "analyzing"}:
            self.progress.stop()
            self.progress.configure(value=0)
        self._update_controls()

    def _selected_candidate(self) -> dict | None:
        if 0 <= self.selected_index < len(self.saves):
            return self.saves[self.selected_index]
        return None

    def _selected_save(self) -> str:
        candidate = self._selected_candidate()
        return str(candidate.get("path", "")) if candidate else ""

    def _valid_selection(self) -> bool:
        path = self._selected_save()
        return bool(path and Path(path).is_file())

    def _card_title(self, candidate: dict) -> str:
        parts: list[str] = []
        if candidate.get("world"):
            parts.append(f"世界 {candidate['world']}")
        if candidate.get("host"):
            parts.append(f"玩家 {candidate['host']}")
        if candidate.get("day") is not None:
            parts.append(f"第 {candidate['day']} 天")
        if parts:
            return " · ".join(parts)
        return str(candidate.get("label", candidate.get("path", "")))

    def _card_subtitle(self, candidate: dict) -> str:
        parts: list[str] = []
        count = candidate.get("count")
        if isinstance(count, int):
            parts.append(f"约 {count} 只")
        has_meta = any(
            candidate.get(field) is not None for field in ("world", "host", "day")
        )
        mtime = candidate.get("mtime")
        if has_meta and isinstance(mtime, (int, float)) and mtime > 0:
            parts.append(datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M"))
        return " · ".join(parts) if parts else "元数据读取中…"

    @staticmethod
    def _shorten_path(path: str, limit: int = 74) -> str:
        if len(path) <= limit:
            return path
        keep = (limit - 1) // 2
        return f"{path[:keep]}…{path[-(limit - keep - 1):]}"

    def _render_save_cards(self) -> None:
        for child in self.save_list_inner.winfo_children():
            child.destroy()
        self.save_cards = []
        last_key = save_parser.path_key(self.last_save) if self.last_save else ""
        for index, candidate in enumerate(self.saves):
            card = tk.Frame(
                self.save_list_inner,
                bg=CARD_SOFT,
                highlightbackground=BORDER,
                highlightthickness=1,
                padx=12,
                pady=8,
            )
            card.pack(fill="x", pady=(0, 8))
            title = self._card_title(candidate)
            if last_key and candidate.get("pathKey") == last_key:
                title = f"★ {title}"
            title_label = tk.Label(
                card,
                text=title,
                bg=CARD_SOFT,
                fg=TEXT,
                anchor="w",
                font=("Microsoft YaHei UI", 10, "bold"),
            )
            title_label.pack(fill="x")
            sub_label = tk.Label(
                card,
                text=self._card_subtitle(candidate),
                bg=CARD_SOFT,
                fg=SUBTEXT,
                anchor="w",
                font=("Microsoft YaHei UI", 8),
            )
            sub_label.pack(fill="x")
            path_label = tk.Label(
                card,
                text=self._shorten_path(str(candidate.get("path", ""))),
                bg=CARD_SOFT,
                fg=SUBTEXT,
                anchor="w",
                font=("Cascadia Mono", 8),
            )
            path_label.pack(fill="x")
            for widget in (card, title_label, sub_label, path_label):
                widget.bind("<Button-1>", lambda _e, i=index: self._card_clicked(i))
                widget.bind("<MouseWheel>", self._save_wheel_handler)
            card._title_label = title_label  # type: ignore[attr-defined]
            self.save_cards.append(card)
        self._refresh_card_highlights()

    def _refresh_card_highlights(self) -> None:
        for index, card in enumerate(self.save_cards):
            selected = index == self.selected_index
            card.configure(
                highlightbackground=GOLD if selected else BORDER,
                highlightthickness=2 if selected else 1,
            )
            title_label = getattr(card, "_title_label", None)
            if title_label is not None:
                title_label.configure(fg=GOLD_STRONG if selected else TEXT)

    def _card_clicked(self, index: int) -> None:
        if self.state in {"scanning", "analyzing"}:
            return
        self._select_save(index)

    def _select_save(self, index: int, *, persist: bool = True) -> None:
        if not (0 <= index < len(self.saves)):
            return
        self.selected_index = index
        self._refresh_card_highlights()
        self._on_save_selected(persist=persist)

    def _update_controls(self) -> None:
        html_ready = bool(self.last_html and Path(self.last_html).is_file())
        self.reopen_button.configure(state="normal" if html_ready else "disabled")
        self.open_dir_button.configure(
            state="normal" if self._valid_selection() else "disabled"
        )

        if self.state == "scanning":
            self.browse_button.configure(state="normal")
            self.refresh_button.configure(state="disabled")
            self.deep_button.configure(text="停止搜索", state="normal")
            self.run_button.configure(text="正在搜索存档…", state="disabled")
            return
        if self.state == "analyzing":
            self.browse_button.configure(state="disabled")
            self.refresh_button.configure(state="disabled")
            self.deep_button.configure(text="深度搜索", state="disabled")
            self.run_button.configure(text="停止读取", state="normal")
            return

        self.browse_button.configure(state="normal")
        self.refresh_button.configure(state="normal")
        self.deep_button.configure(text="深度搜索", state="normal")
        enabled = self.agreed_before and self._valid_selection()
        if not self.agreed_before:
            text = "请先确认使用声明"
        elif not self._valid_selection():
            text = "请先选择有效存档"
        else:
            selected = save_parser.normalize_path(self._selected_save())
            text = (
                "重新读取当前存档并打开工具"
                if self.last_html and selected == self.last_save
                else "读取存档并打开配种工具"
            )
        self.run_button.configure(text=text, state="normal" if enabled else "disabled")

    def _deep_button_action(self) -> None:
        if self.state == "scanning":
            self.cancel_scan()
        elif self.state == "idle":
            self.refresh_saves(deep=True)

    def refresh_saves(self, deep: bool = False) -> None:
        if self.state == "analyzing":
            return
        selected = self._selected_save()
        self.pending_selection_key = save_parser.path_key(selected) if selected else ""
        generation, cancel_event = self.scan_gate.start()
        mode = "深度搜索" if deep else "扫描默认位置"
        self.save_status_var.set(f"{mode}中…")
        self.save_status_label.configure(fg=ACCENT)
        self._set_state("scanning", f"{mode}，可随时停止。")
        self._log(f"[搜索] {mode}…")
        threading.Thread(
            target=self._scan_worker,
            args=(generation, cancel_event, deep),
            daemon=True,
            name=f"save-scan-{generation}",
        ).start()

    def _scan_worker(
        self,
        generation: int,
        cancel_event: threading.Event,
        deep: bool,
    ) -> None:
        try:
            def progress(drive: str) -> None:
                self.events.put(
                    {"kind": "scan_progress", "generation": generation, "drive": drive}
                )

            saves = save_parser.list_saves(
                deep=deep, progress=progress, cancel_event=cancel_event
            )
            self.events.put(
                {"kind": "scan_done", "generation": generation, "saves": saves}
            )
        except save_parser.OperationCancelled:
            self.events.put({"kind": "scan_cancelled", "generation": generation})
        except Exception as exc:
            self.events.put(
                {
                    "kind": "scan_error",
                    "generation": generation,
                    "error": str(exc),
                    "details": traceback.format_exc(),
                }
            )

    def cancel_scan(self) -> None:
        if self.state != "scanning":
            return
        self.scan_gate.cancel(invalidate=True)
        self.save_status_var.set("搜索已停止")
        self.save_status_label.configure(fg=WARNING)
        self._set_state("idle", "搜索已停止；现有列表仍可使用。", "warning")
        self._log("[搜索] 已请求停止。")

    def _apply_saves(self, saves: list[dict]) -> None:
        if self.last_save and Path(self.last_save).is_file():
            last_identity = save_parser.path_key(self.last_save)
            if all(item.get("pathKey") != last_identity for item in saves):
                last_path = Path(self.last_save)
                try:
                    stat = last_path.stat()
                except OSError:
                    stat = None
                if stat is not None:
                    saves.append(
                        {
                            "mtime": stat.st_mtime,
                            "mtimeNs": stat.st_mtime_ns,
                            "size": stat.st_size,
                            "path": save_parser.normalize_path(last_path),
                            "pathKey": last_identity,
                            "guid": last_path.parent.name,
                            "world": None,
                            "host": None,
                            "day": None,
                            "label": f"{last_path.parent.name}（上次手动选择）",
                        }
                    )
        self.saves = saves
        if not saves:
            self.selected_index = -1
            self._render_save_cards()
            xbox_detected = bool(save_parser.xbox_wgs_roots())
            self.save_detail_var.set(
                "检测到 Xbox / Game Pass 原生 WGS 存档；该容器需先导出为 Level.sav。"
                if xbox_detected
                else "已快速检查 Steam、多库和专用服务器默认位置；可以手动选择 Level.sav，或按需使用深度搜索。"
            )
            self.save_status_var.set("未找到存档")
            self.save_status_label.configure(fg=WARNING)
            self._set_state(
                "idle",
                "发现 Xbox WGS 容器，但暂不能直接读取；请先导出 Level.sav。"
                if xbox_detected
                else "默认位置未找到存档，请手动选择或使用深度搜索。",
                "warning",
            )
            return

        selected = next(
            (
                index
                for index, candidate in enumerate(saves)
                if candidate.get("pathKey") == self.pending_selection_key
            ),
            0,
        )
        self._render_save_cards()
        self._select_save(selected)
        self.save_status_var.set(f"找到 {len(saves)} 个存档")
        self.save_status_label.configure(fg=SUCCESS)
        self._set_state("idle", "存档列表已更新，可以开始读取。", "success")
        self._log(f"[搜索] 找到 {len(saves)} 个存档。")

    def _start_counting(
        self, generation: int, cancel_event: threading.Event, saves: list[dict]
    ) -> None:
        paths = [str(item["path"]) for item in saves]
        threading.Thread(
            target=self._count_worker,
            args=(generation, cancel_event, paths),
            daemon=True,
            name=f"save-count-{generation}",
        ).start()

    def _count_worker(
        self,
        generation: int,
        cancel_event: threading.Event,
        paths: list[str],
    ) -> None:
        try:
            dll = save_parser.find_oodle_dll(cancel_event)
            storage_cache: dict = {}
            for path in paths:
                if cancel_event.is_set():
                    raise save_parser.OperationCancelled("操作已取消。")
                count = save_parser.quick_count(
                    path, dll, cancel_event, storage_cache=storage_cache
                )
                if count is not None:
                    self.events.put(
                        {
                            "kind": "scan_count",
                            "generation": generation,
                            "pathKey": save_parser.path_key(path),
                            "count": count,
                        }
                    )
        except save_parser.OperationCancelled:
            return

    def _set_count(self, identity: str, count: int) -> None:
        changed = False
        for candidate in self.saves:
            if candidate.get("pathKey") == identity:
                candidate["count"] = count
                changed = True
                break
        if not changed:
            return
        self._render_save_cards()
        self._on_save_selected(persist=False)

    def _on_save_selected(self, *, persist: bool = True) -> None:
        candidate = self._selected_candidate()
        if not candidate:
            self.save_detail_var.set("尚未选择存档。")
            self._update_controls()
            return
        path = str(candidate.get("path", ""))
        details: list[str] = []
        if candidate.get("world"):
            details.append(f"世界：{candidate['world']}")
        if candidate.get("host"):
            details.append(f"玩家：{candidate['host']}")
        if candidate.get("day") is not None:
            details.append(f"游戏日：{candidate['day']}")
        if isinstance(candidate.get("count"), int):
            details.append(f"约 {candidate['count']} 只")
        self.save_detail_var.set(
            " · ".join(details) if details else "存档元数据不可用"
        )
        self.last_save = save_parser.normalize_path(path)
        if persist:
            self._save_config(last_save=self.last_save)
        self._update_controls()

    def browse(self) -> None:
        if self.state == "analyzing":
            return
        if self.state == "scanning":
            self.cancel_scan()
        default_root = save_parser.default_save_root()
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="选择 Level.sav",
            initialdir=str(default_root if default_root.is_dir() else Path.home()),
            filetypes=(("Palworld 存档", "Level.sav"), ("所有文件", "*.*")),
        )
        if not selected:
            return
        path = Path(selected)
        if not path.is_file():
            messagebox.showwarning("无效文件", "选择的文件不存在。", parent=self.root)
            return
        normalized = save_parser.normalize_path(path)
        identity = save_parser.path_key(normalized)
        save_parser.remember_save_path(normalized)
        existing = next(
            (
                index
                for index, candidate in enumerate(self.saves)
                if candidate.get("pathKey") == identity
            ),
            None,
        )
        if existing is None:
            candidate = {
                "path": normalized,
                "pathKey": identity,
                "label": f"{path.parent.name}（手动选择）",
                "guid": path.parent.name,
                "mtime": path.stat().st_mtime,
            }
            self.saves.append(candidate)
            existing = len(self.saves) - 1
        self._render_save_cards()
        self._select_save(existing)
        self.save_status_var.set("已手动选择")
        self.save_status_label.configure(fg=SUCCESS)
        self._set_state("idle", "手动存档已就绪。", "success")

    def open_save_dir(self) -> None:
        path = self._selected_save()
        if not path or not Path(path).is_file():
            return
        try:
            os.startfile(str(Path(path).parent))
        except OSError as exc:
            messagebox.showerror("无法打开目录", str(exc), parent=self.root)

    def _toggle_warn_game(self) -> None:
        self._save_config(
            skip_game_running_warning=not self.warn_game_var.get()
        )

    def _confirm_game_running(self) -> bool:
        if self.config.get("skip_game_running_warning"):
            return True
        result = {"ok": False}
        remember_var = tk.BooleanVar(value=False)
        dialog = tk.Toplevel(self.root)
        dialog.title("建议先退出游戏")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.configure(bg=CARD, padx=22, pady=18)

        def finish(ok: bool) -> None:
            result["ok"] = ok
            dialog.destroy()

        tk.Label(
            dialog,
            text="检测到《幻兽帕鲁》正在运行",
            bg=CARD,
            fg=GOLD_STRONG,
            font=("Microsoft YaHei UI", 12, "bold"),
        ).pack(anchor="w")
        tk.Label(
            dialog,
            text="程序会重试读取稳定快照，但存档可能不是最新。仍要继续吗？",
            bg=CARD,
            fg=TEXT,
            wraplength=400,
            justify="left",
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w", pady=(9, 4))
        tk.Checkbutton(
            dialog,
            text="以后不再提醒（直接继续）",
            variable=remember_var,
            bg=CARD,
            fg=SUBTEXT,
            activebackground=CARD,
            activeforeground=TEXT,
            selectcolor=CARD_SOFT,
            anchor="w",
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w")
        buttons = tk.Frame(dialog, bg=CARD)
        buttons.pack(fill="x", pady=(16, 0))
        ttk.Button(
            buttons, text="取消", command=lambda: finish(False)
        ).pack(side="right")
        ttk.Button(
            buttons,
            text="仍要继续",
            style="Primary.TButton",
            command=lambda: finish(True),
        ).pack(side="right", padx=(0, 8))
        dialog.protocol("WM_DELETE_WINDOW", lambda: finish(False))
        dialog.update_idletasks()
        root_x = self.root.winfo_rootx()
        root_y = self.root.winfo_rooty()
        root_w = self.root.winfo_width()
        root_h = self.root.winfo_height()
        dialog.geometry(
            f"+{root_x + max((root_w - dialog.winfo_width()) // 2, 0)}"
            f"+{root_y + max((root_h - dialog.winfo_height()) // 3, 0)}"
        )
        dialog.grab_set()
        self.root.wait_window(dialog)
        if result["ok"] and remember_var.get():
            self.warn_game_var.set(False)
            self._save_config(skip_game_running_warning=True)
        return result["ok"]

    def _primary_action(self) -> None:
        if self.state == "analyzing":
            self.cancel_analysis()
        elif self.state == "idle":
            self.run()

    def run(self) -> None:
        save = self._selected_save()
        if not save or not Path(save).is_file():
            messagebox.showwarning("提示", "请先选择有效的 Level.sav。", parent=self.root)
            return
        if game_running() and not self._confirm_game_running():
            self._log("[读取] 已取消，请退出游戏后重试。")
            return
        if self.closing:
            return

        self.scan_gate.cancel(invalidate=True)
        generation, cancel_event = self.analysis_gate.start()
        self.last_save = save_parser.normalize_path(save)
        self._save_config(last_save=self.last_save)
        self.clear_log()
        self._log(f"帕鲁配种助手 v{CURRENT_VERSION}")
        self._log(self.data_badge_var.get())
        self._set_state("analyzing", "正在读取稳定存档快照并整理拥有列表。")
        threading.Thread(
            target=self._analysis_worker,
            args=(generation, cancel_event, self.last_save),
            daemon=True,
            name=f"save-analysis-{generation}",
        ).start()

    def _analysis_worker(
        self, generation: int, cancel_event: threading.Event, save: str
    ) -> None:
        staging_dir = ""
        try:
            result = save_parser.analyze_save(
                save,
                log=lambda message: self.events.put(
                    {
                        "kind": "analysis_log",
                        "generation": generation,
                        "message": message,
                    }
                ),
                cancel_event=cancel_event,
            )
            if cancel_event.is_set():
                raise save_parser.OperationCancelled("操作已取消。")
            bundle = save_parser.stage_generated_bundle(result, cancel_event)
            staging_dir = str(bundle["stagingDir"])
            if cancel_event.is_set():
                raise save_parser.OperationCancelled("操作已取消。")
            self.events.put(
                {
                    "kind": "analysis_ready",
                    "generation": generation,
                    "result": result,
                    "stagingDir": staging_dir,
                }
            )
            staging_dir = ""
        except save_parser.OperationCancelled:
            if staging_dir:
                save_parser.discard_generated_bundle(staging_dir)
            self.events.put({"kind": "analysis_cancelled", "generation": generation})
        except Exception as exc:
            if staging_dir:
                save_parser.discard_generated_bundle(staging_dir)
            self.events.put(
                {
                    "kind": "analysis_error",
                    "generation": generation,
                    "error": str(exc),
                    "details": traceback.format_exc(),
                }
            )

    def cancel_analysis(self) -> None:
        if self.state != "analyzing":
            return
        self.analysis_gate.cancel(invalidate=True)
        self._set_state("idle", "已停止读取；存档没有被修改。", "warning")
        self._log("[读取] 已请求停止。")

    def _show_analysis_result(self, event: dict) -> None:
        result = event["result"]
        world_count = sum(int(item.get("count") or 0) for item in result["owned"])
        world_species = len(result["owned"])
        cross_world_genes = result.get("crossWorldGenes", [])
        gene_count = sum(int(item.get("count") or 0) for item in cross_world_genes)
        gene_species = len(cross_world_genes)
        current_counts = {
            str(item["key"]): int(item.get("count") or 0)
            for item in result["owned"]
        }
        previous_counts = self.config.get("last_inventory_counts")
        if isinstance(previous_counts, dict) and previous_counts:
            all_keys = set(previous_counts) | set(current_counts)
            added = sum(
                max(0, current_counts.get(key, 0) - int(previous_counts.get(key, 0)))
                for key in all_keys
            )
            removed = sum(
                max(0, int(previous_counts.get(key, 0)) - current_counts.get(key, 0))
                for key in all_keys
            )
            changed_species = sum(
                current_counts.get(key, 0) != int(previous_counts.get(key, 0))
                for key in all_keys
            )
            self._log(
                f"[本次变化] {changed_species} 种数量变化 · 增加 {added} 只 · 减少 {removed} 只"
            )
        self._log(f"[本世界] 已识别 {world_species} 种 / {world_count} 只")
        storage_status = str(result.get("globalStorageStatus") or "missing")
        if storage_status == "ok":
            self._log(
                f"[跨界基因] 已识别 {gene_species} 种 / {gene_count} 条，默认不计入本世界库存"
            )
        elif storage_status == "error":
            self._log("[跨界基因] 读取失败；本世界库存不受影响。")
        else:
            self._log("[跨界基因] 未找到 GlobalPalStorage.sav。")

        excluded = result.get("excluded", [])
        if excluded:
            grouped: dict[str, int] = {}
            for item in excluded:
                category = str(item.get("category", "special"))
                grouped[category] = grouped.get(category, 0) + int(item.get("count", 0))
            summary = "、".join(f"{key} {value} 只" for key, value in grouped.items())
            self._log(f"[已排除] {summary}")

        unknown = result.get("unknownData", [])
        if unknown:
            total = sum(int(item.get("count", 0)) for item in unknown)
            self._log(f"[数据警告] {len(unknown)} 个未知内部代号，共 {total} 只：")
            for item in unknown[:20]:
                self._log(f"  - {item['code']} × {item['count']}")

        gene_unknown = result.get("crossWorldGeneUnknownData", [])
        if gene_unknown:
            total = sum(int(item.get("count", 0)) for item in gene_unknown)
            self._log(
                f"[跨界基因警告] {len(gene_unknown)} 个未知内部代号，共 {total} 条；未加入可选基因列表。"
            )

        self.last_html = save_parser.normalize_path(event["html"])
        self._save_config(
            last_html=self.last_html,
            last_html_version=CURRENT_VERSION,
            last_html_asset_id=self.web_asset_id,
            last_save=self.last_save,
            last_inventory_counts=current_counts,
        )
        partial = storage_status == "error"
        self._set_state(
            "idle",
            (
                "读取完成，但有数据未识别；请核对数据版本。"
                if unknown
                else "当前世界读取成功，但跨界基因读取失败。"
                if partial
                else "读取完成，正在打开离线配种工具。"
            ),
            "warning" if unknown or partial else "success",
        )
        self._log(f"[输出] 拥有列表：{event['jsonPath']}")
        self._log(f"[输出] 配种网页：{self.last_html}")

        try:
            os.startfile(self.last_html)
            self._log("[完成] 浏览器已打开。")
        except OSError as exc:
            self._log(f"[打开失败] {exc}")
            messagebox.showerror(
                "无法打开网页",
                f"文件已经生成，但系统无法打开：\n{self.last_html}\n\n{exc}",
                parent=self.root,
            )
            return

        if unknown:
            preview = "\n".join(
                f"{item['code']} × {item['count']}" for item in unknown[:8]
            )
            messagebox.showwarning(
                "部分数据未识别",
                "存档已读取并打开，但以下内部代号不在当前权威数据中：\n\n"
                + preview
                + ("\n…" if len(unknown) > 8 else "")
                + "\n\n这些单位未加入拥有列表，请查看运行记录。",
                parent=self.root,
            )
        elif partial:
            messagebox.showwarning(
                "跨界基因未能读取",
                "当前世界已成功读取并打开，但跨界基因文件读取失败。\n\n"
                "右上角的跨界基因显示功能暂不可用，请查看运行记录后重试。",
                parent=self.root,
            )

    def _drain_events(self) -> None:
        if self.closing:
            return
        for _ in range(200):
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            try:
                self._handle_event(event)
            except Exception as exc:
                self._log(f"[界面事件失败] {exc}")
        self.poll_after_id = self.root.after(50, self._drain_events)

    def _handle_event(self, event: dict) -> None:
        kind = event.get("kind")
        generation = int(event.get("generation", -1))
        if str(kind).startswith("scan_"):
            if not self.scan_gate.is_current(generation):
                return
            if kind == "scan_progress":
                drive = event.get("drive", "")
                self.save_status_var.set(f"正在搜索 {drive}")
                self.operation_status_var.set(f"深度搜索 {drive}，可随时停止。")
            elif kind == "scan_log":
                self._log(str(event.get("message", "")))
            elif kind == "scan_count":
                self._set_count(str(event["pathKey"]), int(event["count"]))
            elif kind == "scan_done":
                self.first_scan = False
                self._save_config(scanned=True)
                saves = list(event.get("saves", []))
                self._apply_saves(saves)
                self._start_counting(
                    generation, self.scan_gate.cancel_event, list(self.saves)
                )
            elif kind == "scan_cancelled":
                self.cancel_scan()
            elif kind == "scan_error":
                self.save_status_var.set("搜索失败")
                self.save_status_label.configure(fg=DANGER)
                self._set_state("idle", "搜索失败，请查看运行记录。", "error")
                self._log(f"[搜索失败] {event.get('error', '')}")
                self._log(str(event.get("details", "")))
            return

        if str(kind).startswith("analysis_"):
            if not self.analysis_gate.is_current(generation):
                staging_dir = event.get("stagingDir")
                if staging_dir:
                    save_parser.discard_generated_bundle(str(staging_dir))
                return
            if kind == "analysis_log":
                self._log(str(event.get("message", "")))
            elif kind == "analysis_ready":
                try:
                    published = save_parser.publish_generated_bundle(
                        str(event["stagingDir"])
                    )
                except Exception as exc:
                    save_parser.discard_generated_bundle(
                        str(event.get("stagingDir", ""))
                    )
                    self._set_state("idle", "输出发布失败，请查看运行记录。", "error")
                    self._log(f"[输出失败] {exc}")
                    messagebox.showerror("输出失败", str(exc), parent=self.root)
                else:
                    event.update(published)
                    self._show_analysis_result(event)
            elif kind == "analysis_cancelled":
                self.cancel_analysis()
            elif kind == "analysis_error":
                self._set_state("idle", "读取失败，存档没有被修改。", "error")
                self._log(f"[读取失败] {event.get('error', '')}")
                self._log(str(event.get("details", "")))
                messagebox.showerror(
                    "读取失败", str(event.get("error", "未知错误")), parent=self.root
                )

    def reopen_html(self) -> None:
        if self.last_html and Path(self.last_html).is_file():
            try:
                os.startfile(self.last_html)
                self._log("[网页] 已重新打开最近生成的配种工具。")
                return
            except OSError as exc:
                messagebox.showerror("无法打开网页", str(exc), parent=self.root)
                return
        self.last_html = ""
        self._save_config(
            last_html="",
            last_html_version=CURRENT_VERSION,
            last_html_asset_id=self.web_asset_id,
        )
        self._update_controls()
        messagebox.showinfo(
            "没有最近网页", "请先成功读取一次存档。", parent=self.root
        )

    def open_output_dir(self) -> None:
        try:
            os.startfile(save_parser.output_dir())
        except OSError as exc:
            messagebox.showerror("无法打开目录", str(exc), parent=self.root)

    def clear_log(self) -> None:
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def copy_log(self) -> None:
        text = self.log_box.get("1.0", "end-1c")
        if not text:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.operation_status_var.set("运行记录已复制到剪贴板。")

    def _log(self, message: str) -> None:
        if not hasattr(self, "log_box"):
            return
        text = str(message)
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + ("" if text.endswith("\n") else "\n"))
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _on_escape(self, _event: object | None = None) -> None:
        if self.state == "scanning":
            self.cancel_scan()
        elif self.state == "analyzing":
            self.cancel_analysis()

    def _on_close(self) -> None:
        if self.closing:
            return
        self.closing = True
        self.scan_gate.cancel(invalidate=True)
        self.analysis_gate.cancel(invalidate=True)
        if self.poll_after_id is not None:
            try:
                self.root.after_cancel(self.poll_after_id)
            except tk.TclError:
                pass
        self.root.destroy()


def _enable_dpi_awareness() -> None:
    try:
        ctypes = __import__("ctypes")
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes = __import__("ctypes")
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _write_crash_log(exc: BaseException) -> Path | None:
    message = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    try:
        path = save_parser.output_dir() / "崩溃日志.txt"
        save_parser.atomic_write_text(path, message)
        return path
    except OSError:
        return None


def main() -> None:
    _enable_dpi_awareness()
    try:
        root = tk.Tk()
        App(root)
        root.mainloop()
    except Exception as exc:
        log_path = _write_crash_log(exc)
        try:
            fallback = tk.Tk()
            fallback.withdraw()
            suffix = f"\n\n日志：{log_path}" if log_path else ""
            messagebox.showerror("帕鲁配种助手 启动失败", f"{exc}{suffix}")
            fallback.destroy()
        except Exception:
            pass
        raise
