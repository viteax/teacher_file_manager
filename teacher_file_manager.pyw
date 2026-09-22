"""
Преподаватель кафедры связи Щерба Антон Иванович
====================================

Простое приложение для организации учебных материалов по структуре:
    Дисциплина -> Тема/Занятие -> Файлы

Особенности:
- Работает на Windows 7 (используется только стандартная библиотека Python,
  без сторонних пакетов). Рекомендуется Python 3.8 (последняя версия,
  официально поддерживающая Windows 7).
- При добавлении файла в занятие программа копирует его в свою папку
  "Материалы" рядом с программой (своя подпапка на каждую пару дисциплина/
  занятие) — оригинал остаётся на месте нетронутым. Это защищает от
  ситуации, когда исходный файл потом переместили/переименовали/удалили:
  внутри программы всегда остаётся собственная рабочая копия.
- При переименовании дисциплины/занятия в программе соответствующая папка
  в "Материалы" переименовывается вслед за ней (и все ссылки на файлы
  внутри обновляются) — структура на диске всегда соответствует тому, что
  видно в программе, можно ориентироваться и там, и там.
- Старые записи (сделанные до этой версии) остаются ссылками на исходные
  файлы как раньше — они не копируются задним числом.
- Все данные (структура дисциплин/тем/занятий/файлов) сохраняются в файл data.json
  рядом с программой, поэтому при следующем запуске всё восстанавливается.
- Двойной клик по файлу (или кнопка "Открыть") открывает его в программе,
  назначенной в Windows по умолчанию (Word, PDF-читалка, плеер и т.д.)

Запуск:
    - Двойной клик по файлу teacher_file_manager.pyw (если установлен Python)
    - Либо: python teacher_file_manager.pyw в командной строке

Для превращения в отдельный .exe (чтобы не требовался Python на компьютере
преподавателя) можно воспользоваться утилитой PyInstaller, запустив на
самой Windows 7 (или Windows, поддерживающей сборку под Win7):
    pip install pyinstaller
    pyinstaller --onefile --noconsole --name "Файловый менеджер" teacher_file_manager.pyw

Разработано: Viktor Iptyshev (aka Viteax, iptvik)
"""

import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tkinter as tk
from collections import deque
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter import font as tkfont

APP_TITLE = "Преподаватель кафедры связи Щерба Антон Иванович"
DATA_FILENAME = "data.json"
MATERIALS_DIRNAME = "Материалы"
TRASH_DIRNAME = "Корзина"
ASSETS_DIRNAME = "assets"
DEFAULT_FONT_SIZE = 12
MIN_FONT_SIZE = 8
MAX_FONT_SIZE = 18
TITLE_FONT_SIZE = 18  # заголовок и девиз в шапке — не меняются кнопками A-/A+
IGNORED_FILENAMES = {"thumbs.db", "desktop.ini"}  # системный мусор Windows-проводника
MOTTO_FONT_SIZE = 16
MAX_UNDO_STEPS = 20  # чтобы история отмены не росла бесконечно за долгую сессию
_INVALID_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Обе темы используют один и тот же движок отрисовки ttk — "clam"
# (кросс-платформенный, не зависит от ОС, работает одинаково на Windows
# 7/10/11). Это важно: если менять движок (например vista <-> clam) вместе
# с переключением темы, у виджетов меняются внутренние отступы/рамки и весь
# интерфейс "съезжает". А так меняются только цвета, геометрия не трогается.
THEMES = {
    "light": {
        "ttk_theme": "clam",
        "bg": "#f0f0f0",
        "fg": "#000000",
        "btn_bg": "#f0f0f0",
        "entry_bg": "#ffffff",
        "listbox_bg": "#ffffff",
        "listbox_fg": "#000000",
        "select_bg": "#0078d7",
        "select_fg": "#ffffff",
        "muted_fg": "#555555",
        "accent_fg": "#d76800",
        "missing_fg": "#b00020",
    },
    "dark": {
        "ttk_theme": "clam",
        "bg": "#2b2b2b",
        "fg": "#e8e8e8",
        "btn_bg": "#3c3c3c",
        "entry_bg": "#3c3c3c",
        "listbox_bg": "#1e1e1e",
        "listbox_fg": "#e8e8e8",
        "select_bg": "#3a6ea5",
        "select_fg": "#ffffff",
        "muted_fg": "#aaaaaa",
        "accent_fg": "#6ea8ff",
        "missing_fg": "#ff6b6b",
    },
}


def get_app_dir():
    """Папка, где лежит сама программа (или .exe), туда же кладём data.json."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


DATA_PATH = os.path.join(get_app_dir(), DATA_FILENAME)
MATERIALS_PATH = os.path.join(get_app_dir(), MATERIALS_DIRNAME)
TRASH_PATH = os.path.join(get_app_dir(), TRASH_DIRNAME)


def sanitize_name_for_path(name):
    """Убирает символы, недопустимые в именах папок/файлов Windows, и
    обрезает длину — чтобы название дисциплины/занятия можно было
    безопасно использовать как имя папки на диске."""
    cleaned = _INVALID_NAME_CHARS.sub("_", name).strip(" .")
    cleaned = cleaned[:50].strip()
    return cleaned or "без_названия"


def _is_managed_copy(path):
    """True, если path лежит внутри управляемой папки "Материалы" (то есть
    это копия, сделанная самой программой), а не старая внешняя ссылка на
    файл преподавателя где-то ещё на диске — такие ссылки в "Корзина" не
    перемещаем, программа ими не владеет."""
    materials = os.path.normcase(os.path.abspath(MATERIALS_PATH)) + os.sep
    return os.path.normcase(os.path.abspath(path)).startswith(materials)


def format_size(num_bytes):
    """Человекочитаемый размер файла: 512 Б, 3.4 КБ, 12.0 МБ, 1.1 ГБ."""
    size = float(num_bytes)
    for unit in ("Б", "КБ", "МБ"):
        if size < 1024:
            return f"{int(size)} {unit}" if unit == "Б" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} ГБ"


def unique_dest_path(target_dir, filename):
    """Возвращает путь в target_dir с таким же именем файла, либо, если
    файл с таким именем уже есть, добавляет суффикс " (2)", " (3)" и т.д."""
    base, ext = os.path.splitext(filename)
    candidate = os.path.join(target_dir, filename)
    n = 2
    while os.path.exists(candidate):
        candidate = os.path.join(target_dir, f"{base} ({n}){ext}")
        n += 1
    return candidate


def load_data():
    if os.path.exists(DATA_PATH):
        try:
            with open(DATA_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (ValueError, OSError):
            messagebox.showwarning(
                APP_TITLE,
                "Не удалось прочитать data.json. Будет создана новая база.",
            )
    return {"subjects": []}


def save_data(data):
    if os.path.exists(DATA_PATH):
        try:
            shutil.copyfile(DATA_PATH, DATA_PATH + ".bak")
        except OSError:
            pass  # резервная копия не критична — не мешаем основному сохранению
    try:
        with open(DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        messagebox.showerror(APP_TITLE, f"Не удалось сохранить данные:\n{e}")


def open_file_external(path):
    """Открыть файл в программе по умолчанию (Windows/Mac/Linux)."""
    if not os.path.exists(path):
        messagebox.showerror(
            APP_TITLE,
            f"Файл не найден по пути:\n{path}\n\n"
            "Возможно, он был перемещён или удалён.",
        )
        return
    try:
        if os.name == "nt":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except OSError as e:
        messagebox.showerror(APP_TITLE, f"Не удалось открыть файл:\n{e}")


class TeacherFileManager(tk.Tk):
    def __init__(self):
        super().__init__()

        if os.name == "nt":
            # Подгоняем масштаб Tk под реальный DPI экрана — иначе на
            # экранах с масштабированием >100% шрифт выглядит размытым
            # (Windows растягивает готовую картинку окна как битмап).
            try:
                self.tk.call("tk", "scaling", self.winfo_fpixels("1i") / 72.0)
            except tk.TclError:
                pass

        self.title(APP_TITLE)
        try:
            self.iconbitmap(os.path.join(get_app_dir(), ASSETS_DIRNAME, "vuc_tsu.ico"))
        except tk.TclError:
            pass

        is_first_run = not os.path.exists(DATA_PATH)
        self.data = load_data()
        self.data.setdefault("settings", {})
        self.selected_subject_idx = None
        self.selected_lesson_idx = None
        self._subject_display_indices = []
        self._lesson_display_indices = []
        self._file_display_indices = []
        self._undo_stack = deque(maxlen=MAX_UNDO_STEPS)
        self._trash_count = 0
        self._trash_size = 0

        self.font_size = self.data["settings"].get("font_size", DEFAULT_FONT_SIZE)
        if not (MIN_FONT_SIZE <= self.font_size <= MAX_FONT_SIZE):
            self.font_size = DEFAULT_FONT_SIZE
        self.theme_name = self.data["settings"].get("theme", "light")
        if self.theme_name not in THEMES:
            self.theme_name = "light"
        self.lesson_sort_mode = self.data["settings"].get("lesson_sort_mode", "custom")
        if self.lesson_sort_mode not in ("custom", "alpha"):
            self.lesson_sort_mode = "custom"
        self.ui_font = tkfont.Font(family="Segoe UI", size=self.font_size)
        self.ui_font_bold = tkfont.Font(
            family="Segoe UI", size=self.font_size, weight="bold"
        )
        # Заголовок и девиз — фиксированного размера, не зависят от A-/A+.
        self.title_font = tkfont.Font(
            family="Segoe UI", size=TITLE_FONT_SIZE, weight="bold"
        )
        self.motto_font = tkfont.Font(
            family="Segoe UI", size=MOTTO_FONT_SIZE, weight="bold"
        )

        self._build_ui()
        relocated_fixed = self._repair_relocated_managed_paths()
        new_subjects, new_lessons = self._discover_new_subjects_and_lessons()
        added_total, added_details = self._scan_all_lessons_for_new_files()
        if relocated_fixed or new_subjects or new_lessons or added_total:
            save_data(
                self.data
            )  # находки автоскана не должны попадать в историю отмены
            lines = []
            if relocated_fixed:
                lines.append(
                    f"Обновлены ссылки на файлы после переноса программы: "
                    f"{relocated_fixed}."
                )
            if new_subjects:
                lines.append(
                    "Новые дисциплины из папок: "
                    + ", ".join(f"«{n}»" for n in new_subjects)
                )
            if new_lessons:
                lines.append(
                    "Новые занятия из папок: "
                    + ", ".join(f"«{s}» → «{l}»" for s, l in new_lessons)
                )
            if added_total:
                lines.append(
                    f"Найдено и добавлено новых файлов из папок: {added_total}."
                )
                for subj_name, lesson_name, count in added_details:
                    lines.append(f"«{subj_name}» → «{lesson_name}»: {count}")
            self._startup_scan_message = "\n".join(lines)
        else:
            self._startup_scan_message = None
        self._compute_trash_stats()
        self._refresh_subjects()
        self._fit_initial_size_to_screen()
        self._apply_dynamic_min_size()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind_all("<Control-z>", self._undo)
        self.bind_all("<Control-Z>", self._undo)
        self.bind_all("<Control-f>", self._focus_search)
        self.bind_all("<Control-F>", self._focus_search)
        if is_first_run:
            self.after(100, self._show_welcome_message)
        elif self._startup_scan_message:
            self.after(
                100, lambda: messagebox.showinfo(APP_TITLE, self._startup_scan_message)
            )

    def _show_welcome_message(self):
        messagebox.showinfo(
            APP_TITLE,
            "Добро пожаловать!\n\n"
            "Материалы здесь хранятся по схеме:\n"
            "    Дисциплина  →  Тема/Занятие  →  Файлы\n\n"
            "Начните с кнопки «Добавить» под левым списком — так создаётся "
            "первая дисциплина. Внутри неё точно так же добавляются занятия, "
            "а внутри занятия — сами файлы.\n\n"
            "Если что-то будет непонятно — кнопка «Справка» на верхней "
            "панели открывает подробную инструкцию.",
        )

    def _on_close(self):
        """Сохраняем настройки (шрифт, тема) при любом закрытии окна —
        крестиком, Alt+F4 и т.д."""
        settings = self.data.setdefault("settings", {})
        settings["font_size"] = self.font_size
        settings["theme"] = self.theme_name
        settings["lesson_sort_mode"] = self.lesson_sort_mode
        save_data(self.data)
        self.destroy()

    def _shrink_font(self):
        """Уменьшает шрифт на 1 пункт напрямую (без сохранения/пересчёта
        окна) — вспомогательный метод для автоподгонки под маленький экран."""
        self.font_size -= 1
        self.ui_font.configure(size=self.font_size)
        self.ui_font_bold.configure(size=self.font_size)
        self.title_font.configure(size=self.font_size + 8)
        self.motto_font.configure(size=self.font_size + 4)

    def _fit_initial_size_to_screen(self):
        """На маленьких мониторах (нередко на старых компьютерах с Windows 7)
        интерфейс с шрифтом по умолчанию может не влезать на экран целиком.
        Автоматически уменьшаем шрифт, пока всё не поместится, или пока не
        дойдём до минимально допустимого размера."""
        self.update_idletasks()
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight() - 60  # запас под панель задач
        while (
            self.winfo_reqwidth() > screen_w or self.winfo_reqheight() > screen_h
        ) and self.font_size > MIN_FONT_SIZE:
            self._shrink_font()
            self.update_idletasks()

    def _apply_dynamic_min_size(self):
        """Подгоняет мин. размер окна под реально требуемый (зависит от
        масштаба DPI и размера шрифта), чтобы кнопки никогда не обрезались.
        Дополнительно ограничивает его размером экрана: minsize в Tk — это
        жёсткий пол для geometry(), поэтому если его не подрезать, окно на
        маленьком экране не смогло бы уменьшиться до видимых границ."""
        self.update_idletasks()
        req_w = self.winfo_reqwidth() + 20
        req_h = self.winfo_reqheight() + 20
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight() - 60  # запас под панель задач
        min_w = min(req_w, screen_w)
        min_h = min(req_h, screen_h)
        self.minsize(min_w, min_h)
        if self.winfo_width() < min_w or self.winfo_height() < min_h:
            self.geometry(f"{min_w}x{min_h}")

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        # Тема (движок ttk + цвета) применяется один раз в конце метода,
        # через self._apply_theme() — см. там же и в _toggle_theme().
        toolbar = ttk.Frame(self, padding=6)
        toolbar.pack(side=tk.TOP, fill=tk.X)

        try:
            self.logo_image = tk.PhotoImage(
                file=os.path.join(get_app_dir(), ASSETS_DIRNAME, "vuc_tsu_logo.png")
            )
            ttk.Label(toolbar, image=self.logo_image).pack(side=tk.LEFT, padx=(0, 10))
        except tk.TclError:
            pass

        title_box = ttk.Frame(toolbar)
        title_box.pack(side=tk.LEFT)
        ttk.Label(
            title_box, text="Преподаватель кафедры связи", font=self.title_font
        ).pack(anchor="w")
        ttk.Label(title_box, text="Щерба Антон Иванович", font=self.title_font).pack(
            anchor="w"
        )
        self.motto_label = ttk.Label(
            title_box, text="Мы учим побеждать", font=self.motto_font
        )
        self.motto_label.pack(anchor="w")

        font_btns = ttk.Frame(toolbar)
        font_btns.pack(side=tk.RIGHT)
        self.theme_btn = ttk.Button(
            font_btns, text="Тема", width=10, command=self._toggle_theme
        )
        self.theme_btn.pack(side=tk.LEFT, padx=(2, 10))
        ttk.Label(font_btns, text="Шрифт:").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(
            font_btns, text="A-", width=3, command=lambda: self._change_font_size(-1)
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            font_btns, text="A+", width=3, command=lambda: self._change_font_size(1)
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(font_btns, text="Сброс", command=self._reset_font_size).pack(
            side=tk.LEFT, padx=(6, 2)
        )

        tools_bar = ttk.Frame(self, padding=(6, 0, 6, 6))
        tools_bar.pack(side=tk.TOP, fill=tk.X)
        ttk.Button(tools_bar, text="Справка", command=self._open_help).pack(
            side=tk.LEFT, padx=(0, 4)
        )
        ttk.Button(
            tools_bar, text="Проверить файлы", command=self._check_all_files
        ).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(tools_bar, text="Экспорт плана...", command=self._export_plan).pack(
            side=tk.LEFT, padx=4
        )

        main = ttk.Frame(self, padding=6)
        main.pack(fill=tk.BOTH, expand=True)
        main.columnconfigure(0, weight=1)
        main.columnconfigure(1, weight=1)
        main.columnconfigure(2, weight=2)
        main.rowconfigure(2, weight=1)

        # --- Column 1: Subjects -------------------------------------------------
        ttk.Label(main, text="Дисциплина", font=self.ui_font_bold).grid(
            row=0, column=0, sticky="w"
        )
        self.subject_filter_var = tk.StringVar()
        self.subject_filter_var.trace_add("write", lambda *_a: self._refresh_subjects())
        subject_search_row = ttk.Frame(main)
        subject_search_row.grid(row=1, column=0, sticky="ew", padx=(0, 6), pady=(2, 2))
        self.subject_filter_entry = ttk.Entry(
            subject_search_row, textvariable=self.subject_filter_var
        )
        self.subject_filter_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.subject_list = tk.Listbox(
            main, exportselection=False, activestyle="dotbox", font=self.ui_font
        )
        self.subject_list.grid(row=2, column=0, sticky="nsew", padx=(0, 6))
        self.subject_list.bind("<<ListboxSelect>>", self._on_select_subject)
        self.subject_list.bind("<Delete>", lambda e: self._delete_subject())
        self.subject_list.bind("<Button-3>", self._on_subject_right_click)
        self.subject_list.bind("<Double-Button-1>", lambda e: self._rename_subject())

        subject_btns = ttk.Frame(main)
        subject_btns.grid(row=3, column=0, sticky="ew", pady=4)
        ttk.Button(subject_btns, text="Добавить", command=self._add_subject).pack(
            side=tk.LEFT, expand=True, fill=tk.X, padx=2
        )
        ttk.Button(
            subject_btns, text="Переименовать", command=self._rename_subject
        ).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
        ttk.Button(subject_btns, text="Удалить", command=self._delete_subject).pack(
            side=tk.LEFT, expand=True, fill=tk.X, padx=2
        )

        # --- Column 2: Lessons -------------------------------------------------
        ttk.Label(main, text="Тема/Занятие", font=self.ui_font_bold).grid(
            row=0, column=1, sticky="w"
        )
        self.lesson_filter_var = tk.StringVar()
        self.lesson_filter_var.trace_add("write", lambda *_a: self._refresh_lessons())
        lesson_search_row = ttk.Frame(main)
        lesson_search_row.grid(row=1, column=1, sticky="ew", padx=6, pady=(2, 2))
        self.lesson_filter_entry = ttk.Entry(
            lesson_search_row, textvariable=self.lesson_filter_var
        )
        self.lesson_filter_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.lesson_sort_btn = ttk.Button(
            lesson_search_row, text="А-Я", width=6, command=self._toggle_lesson_sort
        )
        self.lesson_sort_btn.pack(side=tk.LEFT, padx=(4, 0))
        self.lesson_list = tk.Listbox(
            main, exportselection=False, activestyle="dotbox", font=self.ui_font
        )
        self.lesson_list.grid(row=2, column=1, sticky="nsew", padx=6)
        self.lesson_list.bind("<<ListboxSelect>>", self._on_select_lesson)
        self.lesson_list.bind("<Delete>", lambda e: self._delete_lesson())
        self.lesson_list.bind("<Button-3>", self._on_lesson_right_click)
        self.lesson_list.bind("<Double-Button-1>", lambda e: self._rename_lesson())

        lesson_btns = ttk.Frame(main)
        lesson_btns.grid(row=3, column=1, sticky="ew", pady=4)
        ttk.Button(lesson_btns, text="Добавить", command=self._add_lesson).pack(
            side=tk.LEFT, expand=True, fill=tk.X, padx=2
        )
        ttk.Button(lesson_btns, text="Переименовать", command=self._rename_lesson).pack(
            side=tk.LEFT, expand=True, fill=tk.X, padx=2
        )
        ttk.Button(lesson_btns, text="Удалить", command=self._delete_lesson).pack(
            side=tk.LEFT, expand=True, fill=tk.X, padx=2
        )
        self.lesson_up_btn = ttk.Button(
            lesson_btns, text="▲", width=3, command=lambda: self._move_lesson(-1)
        )
        self.lesson_up_btn.pack(side=tk.LEFT, padx=2)
        self.lesson_down_btn = ttk.Button(
            lesson_btns, text="▼", width=3, command=lambda: self._move_lesson(1)
        )
        self.lesson_down_btn.pack(side=tk.LEFT, padx=2)

        # --- Column 3: Files -----------------------------------------------
        ttk.Label(main, text="Файлы занятия", font=self.ui_font_bold).grid(
            row=0, column=2, sticky="w"
        )
        self.file_filter_var = tk.StringVar()
        self.file_filter_var.trace_add("write", lambda *_a: self._refresh_files())
        ttk.Entry(main, textvariable=self.file_filter_var).grid(
            row=1, column=2, sticky="ew", padx=(6, 0), pady=(2, 2)
        )
        self.file_list = tk.Listbox(
            main,
            exportselection=False,
            activestyle="dotbox",
            selectmode=tk.EXTENDED,
            font=self.ui_font,
        )
        self.file_list.grid(row=2, column=2, sticky="nsew", padx=(6, 0))
        self.file_list.bind("<Double-Button-1>", lambda e: self._open_selected_file())
        self.file_list.bind("<Return>", lambda e: self._open_selected_file())
        self.file_list.bind("<Delete>", lambda e: self._remove_file())
        self.file_list.bind("<Button-3>", self._on_file_right_click)

        file_btns = ttk.Frame(main)
        file_btns.grid(row=3, column=2, sticky="ew", pady=4)
        ttk.Button(file_btns, text="Добавить файл...", command=self._add_file).pack(
            side=tk.LEFT, expand=True, fill=tk.X, padx=2
        )
        ttk.Button(file_btns, text="Открыть", command=self._open_selected_file).pack(
            side=tk.LEFT, expand=True, fill=tk.X, padx=2
        )
        ttk.Button(
            file_btns, text="Показать в папке", command=self._reveal_selected_file
        ).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
        ttk.Button(file_btns, text="Убрать", command=self._remove_file).pack(
            side=tk.LEFT, expand=True, fill=tk.X, padx=2
        )

        status = ttk.Frame(self, padding=(6, 2))
        status.pack(side=tk.BOTTOM, fill=tk.X)
        self.status_var = tk.StringVar(value=f"Данные хранятся в: {DATA_PATH}")
        self.status_label = ttk.Label(status, textvariable=self.status_var)
        self.status_label.pack(side=tk.LEFT)
        self.undo_btn = ttk.Button(status, text="Отменить (Ctrl+Z)", command=self._undo)
        self.undo_btn.pack(side=tk.RIGHT)
        self.undo_btn.state(["disabled"])

        self._update_lesson_sort_ui()
        self._apply_theme(self.theme_name)

    def _toggle_lesson_sort(self):
        self.lesson_sort_mode = (
            "alpha" if self.lesson_sort_mode == "custom" else "custom"
        )
        self.data["settings"]["lesson_sort_mode"] = self.lesson_sort_mode
        save_data(self.data)
        self._update_lesson_sort_ui()
        self._refresh_lessons()

    def _update_lesson_sort_ui(self):
        alpha = self.lesson_sort_mode == "alpha"
        self.lesson_sort_btn.configure(text="Свой" if alpha else "А-Я")
        state = ["disabled"] if alpha else ["!disabled"]
        self.lesson_up_btn.state(state)
        self.lesson_down_btn.state(state)

    def _toggle_theme(self):
        new_theme = "dark" if self.theme_name == "light" else "light"
        self._apply_theme(new_theme)
        self.data["settings"]["theme"] = new_theme
        save_data(self.data)

    def _apply_theme(self, theme_name):
        if theme_name not in THEMES:
            theme_name = "light"
        self.theme_name = theme_name
        c = THEMES[theme_name]

        style = ttk.Style(self)
        try:
            style.theme_use(c["ttk_theme"])
        except tk.TclError:
            style.theme_use("clam")

        style.configure("TFrame", background=c["bg"])
        style.configure(
            "TLabel", background=c["bg"], foreground=c["fg"], font=self.ui_font
        )
        style.configure(
            "TButton", background=c["btn_bg"], foreground=c["fg"], font=self.ui_font
        )
        style.map("TButton", background=[("active", c["select_bg"])])
        style.configure(
            "TEntry",
            fieldbackground=c["entry_bg"],
            foreground=c["fg"],
            font=self.ui_font,
        )

        self.configure(bg=c["bg"])

        for lb in (self.subject_list, self.lesson_list, self.file_list):
            lb.configure(
                bg=c["listbox_bg"],
                fg=c["listbox_fg"],
                selectbackground=c["select_bg"],
                selectforeground=c["select_fg"],
            )

        self.motto_label.configure(foreground=c["accent_fg"])
        self.status_label.configure(foreground=c["muted_fg"])

        self.missing_file_color = c["missing_fg"]
        self._refresh_files()  # перекрасить метку "[не найден]" под новую тему

        self.theme_btn.configure(
            text="☀ Светлая" if theme_name == "dark" else "🌙 Тёмная"
        )

    # --------------------------------------------------------- Служебное --
    def _push_undo(self):
        """Снимает копию self.data ДО текущего изменения и кладёт на стек
        отмены (звать в начале мутирующего действия, пока self.data ещё не
        тронута). Возвращает сам добавленный шаг — вызывающий может
        дозаполнить его folder_renames/created_paths/trash_restores, если
        действию есть что откатывать ещё и на диске, а не только в JSON.
        Стек ограничен MAX_UNDO_STEPS — самые старые шаги просто забываются,
        отдельно чистить его не нужно (в отличие от прежней однослотовой
        отмены, новое действие больше не обнуляет предыдущую историю)."""
        step = {
            "data": copy.deepcopy(self.data),
            "folder_renames": [],  # [(текущая_папка, куда_вернуть)] — os.rename при отмене
            "created_paths": [],  # файлы, созданные этим действием — удалить при отмене
            "trash_restores": [],  # [(было, уехало_в_корзину)] — вернуть shutil.move при отмене
        }
        self._undo_stack.append(step)
        self._update_undo_button()
        return step

    def _update_undo_button(self):
        if self._undo_stack:
            self.undo_btn.state(["!disabled"])
        else:
            self.undo_btn.state(["disabled"])

    def _undo(self, event=None):
        if not self._undo_stack:
            return
        step = self._undo_stack.pop()
        errors = []
        for current_dir, revert_dir in step["folder_renames"]:
            try:
                if os.path.isdir(current_dir):
                    os.makedirs(os.path.dirname(revert_dir), exist_ok=True)
                    os.rename(current_dir, revert_dir)
            except OSError:
                errors.append(os.path.basename(current_dir))
        touched_dirs = set()
        for path in step["created_paths"]:
            try:
                if os.path.isfile(path):
                    os.remove(path)
                    touched_dirs.add(os.path.dirname(path))
            except OSError:
                errors.append(os.path.basename(path))
        for d in touched_dirs:
            try:
                if os.path.isdir(d) and not os.listdir(d):
                    os.rmdir(d)
            except OSError:
                pass  # не пусто или занято — не страшно, просто не убираем
        for old_path, trashed_path in step["trash_restores"]:
            try:
                os.makedirs(os.path.dirname(old_path), exist_ok=True)
                shutil.move(trashed_path, old_path)
            except OSError:
                errors.append(os.path.basename(trashed_path))
        self.data = step["data"]
        save_data(self.data)
        self._compute_trash_stats()
        self._refresh_subjects()
        self._update_undo_button()
        if errors:
            messagebox.showwarning(
                APP_TITLE,
                "Отменено, но не всё удалось откатить на диске:\n" + "\n".join(errors),
            )

    def _focus_search(self, event=None):
        self.subject_filter_entry.focus_set()
        return "break"

    def _compute_trash_stats(self):
        """Пересчитывает (файлов, суммарный размер в байтах) в "Корзина".
        Вызывается только там, где туда что-то реально попадает или уходит
        (удаление/отмена) — не на каждое обновление списков, иначе это был
        бы обход всей "Корзина" на каждое нажатие клавиши в поиске."""
        count = 0
        total_size = 0
        if os.path.isdir(TRASH_PATH):
            for root, _dirs, files in os.walk(TRASH_PATH):
                for name in files:
                    count += 1
                    try:
                        total_size += os.path.getsize(os.path.join(root, name))
                    except OSError:
                        pass
        self._trash_count = count
        self._trash_size = total_size

    def _update_status(self):
        subjects = self.data["subjects"]
        lessons_count = sum(len(s["lessons"]) for s in subjects)
        files_count = sum(len(l["files"]) for s in subjects for l in s["lessons"])
        trash_part = ""
        if self._trash_count:
            trash_part = f"  •  в «Корзина»: {self._trash_count} ({format_size(self._trash_size)})"
        self.status_var.set(
            f"Дисциплин: {len(subjects)}  •  занятий: {lessons_count}  •  "
            f"файлов: {files_count}{trash_part}   |   Данные хранятся в: {DATA_PATH}"
        )

    # ------------------------------------------------------ Контекстное меню --
    def _make_context_menu(self):
        c = THEMES[self.theme_name]
        return tk.Menu(
            self,
            tearoff=0,
            font=self.ui_font,
            bg=c["listbox_bg"],
            fg=c["listbox_fg"],
            activebackground=c["select_bg"],
            activeforeground=c["select_fg"],
        )

    def _item_under_cursor(self, listbox, event):
        """Индекс пункта под курсором, либо None, если клик пришёлся в
        пустую область списка (ниже последнего пункта)."""
        idx = listbox.nearest(event.y)
        if idx < 0:
            return None
        bbox = listbox.bbox(idx)
        if bbox and bbox[1] <= event.y <= bbox[1] + bbox[3]:
            return idx
        return None

    def _popup_menu(self, menu, event):
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _on_subject_right_click(self, event):
        idx = self._item_under_cursor(self.subject_list, event)
        if idx is not None:
            self.subject_list.selection_clear(0, tk.END)
            self.subject_list.selection_set(idx)
            self._on_select_subject()

        menu = self._make_context_menu()
        menu.add_command(label="Добавить дисциплину", command=self._add_subject)
        if idx is not None:
            menu.add_command(label="Переименовать", command=self._rename_subject)
            menu.add_command(label="Удалить", command=self._delete_subject)
        self._popup_menu(menu, event)

    def _on_lesson_right_click(self, event):
        if self._current_subject() is None:
            return  # ещё не выбрана дисциплина — меню бессмысленно
        idx = self._item_under_cursor(self.lesson_list, event)
        if idx is not None:
            self.lesson_list.selection_clear(0, tk.END)
            self.lesson_list.selection_set(idx)
            self._on_select_lesson()

        menu = self._make_context_menu()
        menu.add_command(label="Добавить занятие", command=self._add_lesson)
        if idx is not None:
            menu.add_command(label="Переименовать", command=self._rename_lesson)
            menu.add_command(label="Удалить", command=self._delete_lesson)
            menu.add_separator()
            move_state = tk.DISABLED if self.lesson_sort_mode == "alpha" else tk.NORMAL
            menu.add_command(
                label="Переместить вверх",
                command=lambda: self._move_lesson(-1),
                state=move_state,
            )
            menu.add_command(
                label="Переместить вниз",
                command=lambda: self._move_lesson(1),
                state=move_state,
            )
        self._popup_menu(menu, event)

    def _on_file_right_click(self, event):
        if self._current_lesson() is None:
            return  # ещё не выбрано занятие — меню бессмысленно
        idx = self._item_under_cursor(self.file_list, event)
        if idx is not None and idx not in self.file_list.curselection():
            self.file_list.selection_clear(0, tk.END)
            self.file_list.selection_set(idx)

        menu = self._make_context_menu()
        menu.add_command(label="Добавить файл...", command=self._add_file)
        if idx is not None:
            menu.add_command(label="Открыть", command=self._open_selected_file)
            menu.add_command(
                label="Показать в папке", command=self._reveal_selected_file
            )
            menu.add_separator()
            menu.add_command(label="Убрать", command=self._remove_file)
        self._popup_menu(menu, event)

    def _change_font_size(self, delta):
        new_size = max(MIN_FONT_SIZE, min(MAX_FONT_SIZE, self.font_size + delta))
        self._set_font_size(new_size)

    def _reset_font_size(self):
        self._set_font_size(DEFAULT_FONT_SIZE)

    def _set_font_size(self, new_size):
        if new_size == self.font_size:
            return
        self.font_size = new_size
        self.ui_font.configure(size=self.font_size)
        self.ui_font_bold.configure(size=self.font_size)
        self.data["settings"]["font_size"] = self.font_size
        save_data(self.data)
        self._apply_dynamic_min_size()

    # ------------------------------------------------------------ Subjects --
    def _refresh_subjects(self):
        filter_text = self.subject_filter_var.get().strip().lower()
        self.subject_list.delete(0, tk.END)
        self._subject_display_indices = []
        entries = list(enumerate(self.data["subjects"]))
        entries.sort(key=lambda pair: pair[1]["name"].lower())
        for idx, subject in entries:
            if filter_text and filter_text not in subject["name"].lower():
                continue
            label = subject["name"]
            has_missing = any(
                not os.path.exists(p)
                for lesson in subject["lessons"]
                for p in lesson["files"]
            )
            if has_missing:
                label += "  ⚠"
            self.subject_list.insert(tk.END, label)
            self._subject_display_indices.append(idx)
            if has_missing:
                self.subject_list.itemconfig(
                    self.subject_list.size() - 1, foreground=self.missing_file_color
                )
        self.lesson_list.delete(0, tk.END)
        self.file_list.delete(0, tk.END)
        self.selected_subject_idx = None
        self.selected_lesson_idx = None
        self._update_status()

    def _refresh_subjects_keep_selection(self):
        idx = self.selected_subject_idx
        self._refresh_subjects()
        if idx is not None and idx in self._subject_display_indices:
            pos = self._subject_display_indices.index(idx)
            self.subject_list.selection_set(pos)
            self.subject_list.see(pos)
            self.selected_subject_idx = idx
            self._refresh_lessons()

    def _on_select_subject(self, _event=None):
        sel = self.subject_list.curselection()
        if not sel:
            return
        self.selected_subject_idx = self._subject_display_indices[sel[0]]
        self._refresh_lessons()

    def _subject_name_exists(self, name, exclude_idx=None):
        return any(
            i != exclude_idx and s["name"].lower() == name.lower()
            for i, s in enumerate(self.data["subjects"])
        )

    def _add_subject(self):
        name = simpledialog.askstring(
            APP_TITLE, "Название новой дисциплины:", parent=self
        )
        if not name:
            return
        name = name.strip()
        if self._subject_name_exists(name):
            messagebox.showerror(APP_TITLE, f"Дисциплина «{name}» уже есть в списке.")
            return
        self._push_undo()
        self.data["subjects"].append({"name": name, "lessons": []})
        save_data(self.data)
        self.subject_filter_var.set("")
        self._refresh_subjects()
        # Список всегда по алфавиту — новая дисциплина не обязательно
        # окажется последней в отображении, поэтому ищем её позицию, а не
        # просто прыгаем в конец списка.
        new_idx = len(self.data["subjects"]) - 1
        if new_idx in self._subject_display_indices:
            pos = self._subject_display_indices.index(new_idx)
            self.subject_list.selection_set(pos)
            self.subject_list.see(pos)
            self._on_select_subject()

    def _rename_subject(self):
        if self.selected_subject_idx is None:
            messagebox.showinfo(APP_TITLE, "Сначала выберите тему.")
            return
        subject = self.data["subjects"][self.selected_subject_idx]
        name = simpledialog.askstring(
            APP_TITLE, "Новое название темы:", initialvalue=subject["name"], parent=self
        )
        if not name:
            return
        name = name.strip()
        if self._subject_name_exists(name, exclude_idx=self.selected_subject_idx):
            messagebox.showerror(APP_TITLE, f"Дисциплина «{name}» уже есть в списке.")
            return
        old_dir = self._subject_materials_dir(subject)
        step = self._push_undo()
        subject["name"] = name
        new_dir = self._subject_materials_dir(subject)
        if self._rename_materials_folder(old_dir, new_dir):
            step["folder_renames"].append((new_dir, old_dir))
        save_data(self.data)
        self._refresh_subjects_keep_selection()

    def _delete_subject(self):
        if self.selected_subject_idx is None:
            messagebox.showinfo(APP_TITLE, "Сначала выберите дисциплину.")
            return
        subject = self.data["subjects"][self.selected_subject_idx]
        if not messagebox.askyesno(
            APP_TITLE,
            "Удалить тему «{}» вместе со всеми занятиями внутри неё?\n"
            "(управляемые копии файлов переместятся в папку «Корзина»; "
            "действие можно отменить — Ctrl+Z)".format(subject["name"]),
        ):
            return
        step = self._push_undo()
        subject_lesson_ids = {id(l) for l in subject["lessons"]}
        moves = []
        trash_errors = []
        for lesson in subject["lessons"]:
            lesson_moves, lesson_errors = self._move_lesson_files_to_trash(
                subject, lesson, excluded_lesson_ids=subject_lesson_ids
            )
            moves.extend(lesson_moves)
            trash_errors.extend(lesson_errors)
        step["trash_restores"] = moves
        subject_dir = self._subject_materials_dir(subject)
        try:
            if os.path.isdir(subject_dir) and not os.listdir(subject_dir):
                os.rmdir(subject_dir)
        except OSError:
            pass
        del self.data["subjects"][self.selected_subject_idx]
        save_data(self.data)
        self._compute_trash_stats()
        self._update_undo_button()
        self._refresh_subjects()
        if trash_errors:
            messagebox.showwarning(
                APP_TITLE,
                "Тема удалена, но часть файлов не удалось переместить в «Корзина» "
                "(остались в «Материалы»):\n"
                + "\n".join(os.path.basename(p) for p in trash_errors),
            )

    # ----------------------------------------------------------- Lessons --
    def _current_subject(self):
        if self.selected_subject_idx is None:
            return None
        return self.data["subjects"][self.selected_subject_idx]

    def _refresh_lessons(self):
        filter_text = self.lesson_filter_var.get().strip().lower()
        self.lesson_list.delete(0, tk.END)
        self.file_list.delete(0, tk.END)
        self.selected_lesson_idx = None
        self._lesson_display_indices = []
        subject = self._current_subject()
        if subject is None:
            return
        entries = list(enumerate(subject["lessons"]))
        if self.lesson_sort_mode == "alpha":
            entries.sort(key=lambda pair: pair[1]["name"].lower())
        for idx, lesson in entries:
            if filter_text and filter_text not in lesson["name"].lower():
                continue
            label = lesson["name"]
            has_missing = any(not os.path.exists(p) for p in lesson["files"])
            if has_missing:
                label += "  ⚠"
            self.lesson_list.insert(tk.END, label)
            self._lesson_display_indices.append(idx)
            if has_missing:
                self.lesson_list.itemconfig(
                    self.lesson_list.size() - 1, foreground=self.missing_file_color
                )
        self._update_status()

    def _on_select_lesson(self, _event=None):
        sel = self.lesson_list.curselection()
        if not sel:
            return
        self.selected_lesson_idx = self._lesson_display_indices[sel[0]]
        self._refresh_files()

    def _lesson_name_exists(self, subject, name, exclude_idx=None):
        return any(
            i != exclude_idx and l["name"].lower() == name.lower()
            for i, l in enumerate(subject["lessons"])
        )

    def _add_lesson(self):
        subject = self._current_subject()
        if subject is None:
            messagebox.showinfo(APP_TITLE, "Сначала выберите тему.")
            return
        name = simpledialog.askstring(APP_TITLE, "Название занятия:", parent=self)
        if not name:
            return
        name = name.strip()
        if self._lesson_name_exists(subject, name):
            messagebox.showerror(
                APP_TITLE, f"Занятие «{name}» уже есть в этой дисциплине."
            )
            return
        self._push_undo()
        subject["lessons"].append({"name": name, "files": []})
        save_data(self.data)
        self.lesson_filter_var.set("")
        self._refresh_lessons()
        # При сортировке "А-Я" новое занятие тоже не обязательно окажется
        # последним в отображении — та же логика, что и для дисциплин.
        new_idx = len(subject["lessons"]) - 1
        if new_idx in self._lesson_display_indices:
            pos = self._lesson_display_indices.index(new_idx)
            self.lesson_list.selection_set(pos)
            self.lesson_list.see(pos)
            self._on_select_lesson()

    def _rename_lesson(self):
        subject = self._current_subject()
        lesson = self._current_lesson()
        if lesson is None:
            messagebox.showinfo(APP_TITLE, "Сначала выберите занятие.")
            return
        name = simpledialog.askstring(
            APP_TITLE,
            "Новое название занятия:",
            initialvalue=lesson["name"],
            parent=self,
        )
        if not name:
            return
        name = name.strip()
        if self._lesson_name_exists(
            subject, name, exclude_idx=self.selected_lesson_idx
        ):
            messagebox.showerror(
                APP_TITLE, f"Занятие «{name}» уже есть в этой дисциплине."
            )
            return
        old_dir = self._lesson_materials_dir(subject, lesson)
        step = self._push_undo()
        lesson["name"] = name
        new_dir = self._lesson_materials_dir(subject, lesson)
        if self._rename_materials_folder(old_dir, new_dir):
            step["folder_renames"].append((new_dir, old_dir))
        save_data(self.data)
        idx = self.selected_lesson_idx
        self._refresh_lessons()
        if idx is not None and idx in self._lesson_display_indices:
            pos = self._lesson_display_indices.index(idx)
            self.lesson_list.selection_set(pos)
            self.lesson_list.see(pos)
            self.selected_lesson_idx = idx
            self._refresh_files()

    def _move_lesson(self, delta):
        if self.lesson_sort_mode == "alpha":
            return  # ручная перестановка не имеет смысла в алфавитном виде
        subject = self._current_subject()
        idx = self.selected_lesson_idx
        if subject is None or idx is None:
            messagebox.showinfo(APP_TITLE, "Сначала выберите занятие.")
            return
        lessons = subject["lessons"]
        new_idx = idx + delta
        if new_idx < 0 or new_idx >= len(lessons):
            return
        self._push_undo()
        lessons[idx], lessons[new_idx] = lessons[new_idx], lessons[idx]
        save_data(self.data)
        self._refresh_lessons()
        if new_idx in self._lesson_display_indices:
            pos = self._lesson_display_indices.index(new_idx)
            self.lesson_list.selection_set(pos)
            self.lesson_list.see(pos)
            self.selected_lesson_idx = new_idx
            self._refresh_files()

    def _delete_lesson(self):
        subject = self._current_subject()
        lesson = self._current_lesson()
        if subject is None or lesson is None:
            messagebox.showinfo(APP_TITLE, "Сначала выберите занятие.")
            return
        if not messagebox.askyesno(
            APP_TITLE,
            "Удалить занятие «{}» со списком прикреплённых файлов?\n"
            "(управляемые копии файлов переместятся в папку «Корзина»; "
            "действие можно отменить — Ctrl+Z)".format(lesson["name"]),
        ):
            return
        step = self._push_undo()
        step["trash_restores"], trash_errors = self._move_lesson_files_to_trash(
            subject, lesson
        )
        del subject["lessons"][self.selected_lesson_idx]
        save_data(self.data)
        self._compute_trash_stats()
        self._update_undo_button()
        self._refresh_lessons()
        if trash_errors:
            messagebox.showwarning(
                APP_TITLE,
                "Занятие удалено, но часть файлов не удалось переместить в «Корзина» "
                "(остались в «Материалы»):\n"
                + "\n".join(os.path.basename(p) for p in trash_errors),
            )

    # ------------------------------------------------------------- Files --
    def _current_lesson(self):
        subject = self._current_subject()
        if subject is None or self.selected_lesson_idx is None:
            return None
        return subject["lessons"][self.selected_lesson_idx]

    def _refresh_files(self):
        filter_text = self.file_filter_var.get().strip().lower()
        self.file_list.delete(0, tk.END)
        self._file_display_indices = []
        lesson = self._current_lesson()
        if lesson is None:
            self._update_status()
            return
        for idx, file_path in enumerate(lesson["files"]):
            label = os.path.basename(file_path)
            if filter_text and filter_text not in label.lower():
                continue
            missing = not os.path.exists(file_path)
            if missing:
                label += "  [не найден]"
            self.file_list.insert(tk.END, label)
            self._file_display_indices.append(idx)
            if missing:
                self.file_list.itemconfig(
                    self.file_list.size() - 1, foreground=self.missing_file_color
                )
        self._update_status()

    def _subject_materials_dir(self, subject):
        """Папка дисциплины на диске (внутри неё лежат папки её занятий).
        Название дисциплин гарантированно уникально (программа не даёт
        создать/переименовать в уже существующее), поэтому папка называется
        просто по имени — без скрытых id."""
        return os.path.join(MATERIALS_PATH, sanitize_name_for_path(subject["name"]))

    def _lesson_materials_dir(self, subject, lesson):
        """Папка на диске, куда копируются файлы этого занятия. Название
        занятий уникально в пределах своей дисциплины, так что и тут
        достаточно просто имени."""
        return os.path.join(
            self._subject_materials_dir(subject), sanitize_name_for_path(lesson["name"])
        )

    def _subject_trash_dir(self, subject):
        return os.path.join(TRASH_PATH, sanitize_name_for_path(subject["name"]))

    def _lesson_trash_dir(self, subject, lesson):
        return os.path.join(
            self._subject_trash_dir(subject), sanitize_name_for_path(lesson["name"])
        )

    def _path_referenced_elsewhere(self, path, excluded_lesson_ids):
        """Есть ли этот путь ещё у какого-то занятия в базе, кроме тех, чьи
        id() в excluded_lesson_ids? На случай, если один физический файл
        всё же используется больше чем одним занятием (например, в старых
        базах, сохранённых ещё когда существовала функция "Дублировать") —
        удаление одного из них не должно утаскивать файл в "Корзина", пока
        другой ещё им пользуется."""
        target = os.path.normcase(path)
        for subject in self.data["subjects"]:
            for lesson in subject["lessons"]:
                if id(lesson) in excluded_lesson_ids:
                    continue
                if any(os.path.normcase(p) == target for p in lesson["files"]):
                    return True
        return False

    def _move_managed_file_to_trash(
        self, subject, lesson, path, excluded_lesson_ids=None
    ):
        """Переносит path в Корзина/<дисциплина>/<занятие>, если это
        управляемая копия (см. _is_managed_copy), она реально есть на диске
        и больше нигде в базе не используется. Возвращает (статус, move),
        где move — (откуда, куда) при статусе "moved", иначе None.
        Статусы: "moved", "kept_shared" (нужен другому занятию-дубликату),
        "external" (внешняя ссылка — не трогаем), "missing" (на диске и так
        уже нет), "error" (не удалось перенести, файл остался на месте)."""
        if not _is_managed_copy(path):
            return "external", None
        if not os.path.isfile(path):
            return "missing", None
        excluded = (
            excluded_lesson_ids if excluded_lesson_ids is not None else {id(lesson)}
        )
        if self._path_referenced_elsewhere(path, excluded):
            return "kept_shared", None
        target_dir = self._lesson_trash_dir(subject, lesson)
        try:
            os.makedirs(target_dir, exist_ok=True)
            dest = unique_dest_path(target_dir, os.path.basename(path))
            shutil.move(path, dest)
        except OSError:
            return "error", None
        return "moved", (path, dest)

    def _move_lesson_files_to_trash(self, subject, lesson, excluded_lesson_ids=None):
        """Переносит в "Корзина" все управляемые файлы занятия (кроме тех,
        что ещё нужны занятиям-дубликатам), и убирает опустевшую папку
        занятия из "Материалы". Возвращает (перенесённые (откуда, куда),
        имена файлов, которые перенести не удалось)."""
        excluded = (
            excluded_lesson_ids if excluded_lesson_ids is not None else {id(lesson)}
        )
        moves = []
        errors = []
        for path in lesson["files"]:
            status, move = self._move_managed_file_to_trash(
                subject, lesson, path, excluded_lesson_ids=excluded
            )
            if status == "moved":
                moves.append(move)
            elif status == "error":
                errors.append(path)
        lesson_dir = self._lesson_materials_dir(subject, lesson)
        try:
            if os.path.isdir(lesson_dir) and not os.listdir(lesson_dir):
                os.rmdir(lesson_dir)
        except OSError:
            pass
        return moves, errors

    def _rename_materials_folder(self, old_dir, new_dir):
        """Переименовывает папку old_dir -> new_dir на диске (если она уже
        существует) и обновляет пути ко всем файлам во всей базе, у которых
        был этот префикс пути — включая занятия-дубликаты, которые могут
        ссылаться на файлы внутри этой же папки. Возвращает True, если
        папка физически переименована (это нужно вызывающему для истории
        отмены — знать, что при Ctrl+Z придётся переименовать её обратно)."""
        if old_dir is None or new_dir is None or old_dir == new_dir:
            return False
        if not os.path.isdir(old_dir):
            return False  # папка ещё не создавалась (файлов не добавляли) — нечего переименовывать
        try:
            os.makedirs(os.path.dirname(new_dir), exist_ok=True)
            os.rename(old_dir, new_dir)
        except OSError as e:
            messagebox.showwarning(
                APP_TITLE,
                "Название изменено, но не удалось переименовать папку с "
                f"файлами на диске:\n{e}\n\nПуть в проводнике остался старым.",
            )
            return False
        # Обязательно с разделителем на конце префикса: без него, скажем,
        # переименование "Урок 1" задело бы и файлы "Урок 10" (совпадение
        # по началу строки, но это разные папки).
        old_dir_prefix = os.path.normcase(old_dir) + os.sep
        for subject in self.data["subjects"]:
            for lesson in subject["lessons"]:
                lesson["files"] = [
                    new_dir + p[len(old_dir) :]
                    if os.path.normcase(p).startswith(old_dir_prefix)
                    else p
                    for p in lesson["files"]
                ]
        return True

    def _scan_lesson_folder_for_new_files(self, subject, lesson):
        """Сравнивает папку занятия на диске со списком файлов в data.json и
        дописывает в lesson["files"] те файлы, которых там ещё нет — это
        покрывает случай, когда файл закинули в папку вручную через
        проводник, а не через кнопку "Добавить файл...". Возвращает
        количество добавленных файлов."""
        target_dir = self._lesson_materials_dir(subject, lesson)
        if not os.path.isdir(target_dir):
            return 0
        # normcase: на Windows пути сравниваем без учёта регистра диска/
        # разделителей — иначе "c:\..." и "C:\..." считаются разными
        # строками, хотя это один и тот же файл (баг с задвоением файлов
        # после перезапуска, если __file__ в другой раз резолвится с другим
        # регистром буквы диска).
        known = {os.path.normcase(p) for p in lesson["files"]}
        added = 0
        for name in sorted(os.listdir(target_dir)):
            if name.lower() in IGNORED_FILENAMES:
                continue
            full = os.path.join(target_dir, name)
            if os.path.isfile(full) and os.path.normcase(full) not in known:
                lesson["files"].append(full)
                added += 1
        return added

    def _scan_all_lessons_for_new_files(self):
        """Прогоняет _scan_lesson_folder_for_new_files по всей базе.
        Возвращает (сколько всего файлов добавлено, список деталей по
        занятиям, где что-то нашлось)."""
        total = 0
        details = []
        for subject in self.data["subjects"]:
            for lesson in subject["lessons"]:
                added = self._scan_lesson_folder_for_new_files(subject, lesson)
                if added:
                    total += added
                    details.append((subject["name"], lesson["name"], added))
        return total, details

    def _relocated_managed_copy_basename(self, subject, lesson, path):
        """Если структура path похожа на управляемую копию ЭТОГО ЖЕ занятия
        — заканчивается на .../Материалы/<эта дисциплина>/<это занятие>/
        <файл> — но, возможно, под другим корневым путём (всю программу
        скопировали или перенесли в другое место, и путь в data.json
        остался привязан к старому расположению), возвращает имя файла.
        Иначе — None (это либо уже нормальный текущий путь, либо вообще
        не управляемая копия, а внешняя ссылка)."""
        parts = os.path.normpath(path).split(os.sep)
        if len(parts) < 4:
            return None
        expected = [
            MATERIALS_DIRNAME,
            sanitize_name_for_path(subject["name"]),
            sanitize_name_for_path(lesson["name"]),
        ]
        tail = parts[-4:-1]
        if [t.lower() for t in tail] == [e.lower() for e in expected]:
            return parts[-1]
        return None

    def _repair_relocated_managed_paths(self):
        """Если всю программу скопировали или перенесли в другую папку/на
        другой диск, старые пути в data.json остаются привязаны к прежнему
        расположению — новый и старый путь для одного и того же файла
        выглядят как два разных файла, и автоскан плодит дубли (реальный
        случай: перенос из репозитория в отдельную тестовую папку). Эта
        проверка идёт ПЕРЕД автосканом и приводит такие "переехавшие"
        ссылки к актуальному месту (текущий MATERIALS_PATH) — но только
        если файл там на самом деле есть, иначе оставляет как было (чтобы
        не терять ссылку, если файл ещё не скопирован на новое место).
        Заодно убирает получившиеся точные дубликаты внутри занятия.
        Возвращает число исправленных/убранных ссылок — для сводки при
        старте."""
        fixed = 0
        for subject in self.data["subjects"]:
            for lesson in subject["lessons"]:
                new_files = []
                seen = set()
                for path in lesson["files"]:
                    basename = self._relocated_managed_copy_basename(
                        subject, lesson, path
                    )
                    if basename is not None:
                        canonical = os.path.join(
                            self._lesson_materials_dir(subject, lesson), basename
                        )
                        if os.path.normcase(canonical) != os.path.normcase(
                            path
                        ) and os.path.isfile(canonical):
                            path = canonical
                            fixed += 1
                    key = os.path.normcase(path)
                    if key in seen:
                        continue  # точный дубликат — например, canonical уже был в списке
                    seen.add(key)
                    new_files.append(path)
                lesson["files"] = new_files
        return fixed

    def _discover_new_subjects_and_lessons(self):
        """Обнаруживает в "Материалы" папки дисциплин и занятий, которых
        ещё нет в базе (созданы вручную через проводник, а не кнопками
        "Добавить"), и заводит для них записи — имя берётся из имени
        папки. Отдельно от _scan_lesson_folder_for_new_files, который
        находит только новые файлы внутри уже известных занятий: этот
        метод должен отработать раньше него, чтобы у новых занятий уже
        было куда добавлять найденные файлы. Возвращает (новые дисциплины,
        новые занятия как (дисциплина, занятие)) для сводки при старте."""
        if not os.path.isdir(MATERIALS_PATH):
            return [], []
        new_subjects = []
        new_lessons = []
        by_sanitized_subject = {
            sanitize_name_for_path(s["name"]).lower(): s for s in self.data["subjects"]
        }
        for subj_entry in sorted(os.listdir(MATERIALS_PATH)):
            subj_dir = os.path.join(MATERIALS_PATH, subj_entry)
            if not os.path.isdir(subj_dir):
                continue
            subject = by_sanitized_subject.get(subj_entry.lower())
            if subject is None:
                if self._subject_name_exists(subj_entry):
                    continue  # имя занято, только регистр папки отличается — не плодим дубль
                subject = {"name": subj_entry, "lessons": []}
                self.data["subjects"].append(subject)
                by_sanitized_subject[subj_entry.lower()] = subject
                new_subjects.append(subj_entry)
            by_sanitized_lesson = {
                sanitize_name_for_path(l["name"]).lower(): l for l in subject["lessons"]
            }
            for lesson_entry in sorted(os.listdir(subj_dir)):
                lesson_dir = os.path.join(subj_dir, lesson_entry)
                if not os.path.isdir(lesson_dir):
                    continue
                lesson = by_sanitized_lesson.get(lesson_entry.lower())
                if lesson is None:
                    if self._lesson_name_exists(subject, lesson_entry):
                        continue
                    lesson = {"name": lesson_entry, "files": []}
                    subject["lessons"].append(lesson)
                    by_sanitized_lesson[lesson_entry.lower()] = lesson
                    new_lessons.append((subject["name"], lesson_entry))
        return new_subjects, new_lessons

    def _add_file(self):
        subject = self._current_subject()
        lesson = self._current_lesson()
        if lesson is None:
            messagebox.showinfo(APP_TITLE, "Сначала выберите занятие.")
            return
        paths = filedialog.askopenfilenames(
            title="Выберите файл(ы) для занятия", parent=self
        )
        if not paths:
            return
        target_dir = self._lesson_materials_dir(subject, lesson)
        try:
            os.makedirs(target_dir, exist_ok=True)
        except OSError as e:
            messagebox.showerror(
                APP_TITLE, f"Не удалось создать папку для файлов:\n{e}"
            )
            return
        # normcase: пути занятия уже известны заранее — если после копирования
        # dest совпадёт с одним из них, это не новый файл, а восстановление
        # прежнего "не найден" на его законном месте (см. ниже).
        known = {os.path.normcase(p) for p in lesson["files"]}
        step = self._push_undo()
        errors = []
        restored = 0
        created_paths = []
        for p in paths:
            dest = unique_dest_path(target_dir, os.path.basename(p))
            try:
                shutil.copy2(p, dest)
            except OSError as e:
                errors.append(f"{os.path.basename(p)}: {e}")
                continue
            created_paths.append(dest)
            # unique_dest_path уклоняется только от файлов, реально лежащих
            # на диске. Если ссылка на этот путь уже есть в занятии, но сам
            # файл был "не найден" — значит, мы его только что восстановили
            # копированием под тем же именем, и заводить вторую (дублирующую)
            # ссылку на тот же файл не нужно.
            if os.path.normcase(dest) in known:
                restored += 1
            else:
                lesson["files"].append(dest)
                known.add(os.path.normcase(dest))
        if created_paths:
            step["created_paths"] = created_paths
        else:
            # ничего реально не изменилось (всё копирование провалилось) —
            # не засорять историю отмены пустым шагом
            self._undo_stack.pop()
            self._update_undo_button()
        save_data(self.data)
        self.file_filter_var.set("")
        self._refresh_files()
        if errors:
            messagebox.showwarning(
                APP_TITLE,
                "Не удалось скопировать некоторые файлы:\n" + "\n".join(errors),
            )
        if restored:
            messagebox.showinfo(
                APP_TITLE,
                "Файл восстановлен на прежнем месте — новая ссылка не добавлена."
                if restored == 1
                else f"Восстановлено файлов на прежнем месте: {restored} "
                "— новые ссылки не добавлялись.",
            )

    def _get_selected_file_path(self):
        lesson = self._current_lesson()
        if lesson is None:
            return None
        sel = self.file_list.curselection()
        if not sel:
            return None
        return lesson["files"][self._file_display_indices[sel[0]]]

    def _open_selected_file(self):
        path = self._get_selected_file_path()
        if path is None:
            messagebox.showinfo(APP_TITLE, "Сначала выберите файл в списке справа.")
            return
        open_file_external(path)

    def _reveal_selected_file(self):
        path = self._get_selected_file_path()
        if path is None:
            messagebox.showinfo(APP_TITLE, "Сначала выберите файл в списке справа.")
            return
        folder = os.path.dirname(path)
        if os.name == "nt" and os.path.exists(path):
            # Открыть проводник Windows с выделенным файлом
            path = path.replace("/", "\\")  # Требование винды
            subprocess.Popen(f'explorer /select,"{path}"')
        elif os.path.isdir(folder):
            open_file_external(folder)
        else:
            messagebox.showerror(APP_TITLE, f"Папка не найдена:\n{folder}")

    def _remove_file(self):
        subject = self._current_subject()
        lesson = self._current_lesson()
        sel = self.file_list.curselection()
        if lesson is None or not sel:
            messagebox.showinfo(APP_TITLE, "Сначала выберите файл(ы) в списке справа.")
            return
        question = (
            "Убрать файл из занятия?"
            if len(sel) == 1
            else f"Убрать выбранные файлы ({len(sel)} шт.) из занятия?"
        )
        if not messagebox.askyesno(
            APP_TITLE,
            question + " (управляемые копии переместятся в папку «Корзина»; "
            "внешние ссылки на файлы затронуты не будут; действие можно отменить — Ctrl+Z)",
        ):
            return
        step = self._push_undo()
        actual_indices = [self._file_display_indices[i] for i in sel]
        trash_moves = []
        errors = []
        for idx in sorted(actual_indices, reverse=True):
            path = lesson["files"][idx]
            status, move = self._move_managed_file_to_trash(subject, lesson, path)
            if status == "error":
                errors.append(os.path.basename(path))
                continue  # не удалось перенести — оставляем файл и ссылку как есть
            if status == "moved":
                trash_moves.append(move)
            del lesson["files"][idx]
        step["trash_restores"] = trash_moves
        save_data(self.data)
        self._compute_trash_stats()
        self._update_undo_button()
        self._refresh_files()
        if errors:
            messagebox.showwarning(
                APP_TITLE,
                "Не удалось переместить в «Корзина» (файл оставлен в занятии):\n"
                + "\n".join(errors),
            )

    # ------------------------------------------------------------- Утилиты --
    def _show_report_window(self, title, text):
        win = tk.Toplevel(self)
        win.title(title)
        win.geometry("700x450")
        c = THEMES[self.theme_name]
        win.configure(bg=c["bg"])

        frame = ttk.Frame(win, padding=8)
        frame.pack(fill=tk.BOTH, expand=True)
        text_widget = tk.Text(
            frame,
            wrap="word",
            font=self.ui_font,
            bg=c["listbox_bg"],
            fg=c["listbox_fg"],
            insertbackground=c["fg"],
        )
        scrollbar = ttk.Scrollbar(frame, command=text_widget.yview)
        text_widget.configure(yscrollcommand=scrollbar.set)
        text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text_widget.insert("1.0", text)
        text_widget.configure(state="disabled")
        ttk.Button(win, text="Закрыть", command=win.destroy).pack(pady=6)
        win.transient(self)
        win.grab_set()

    def _open_help(self):
        help_path = os.path.join(get_app_dir(), "Инструкция для капитана Щербы.txt")
        if not os.path.isfile(help_path):
            messagebox.showerror(APP_TITLE, f"Файл инструкции не найден:\n{help_path}")
            return
        open_file_external(help_path)

    def _check_all_files(self):
        missing = []
        total = 0
        for subject in self.data["subjects"]:
            for lesson in subject["lessons"]:
                for path in lesson["files"]:
                    total += 1
                    if not os.path.exists(path):
                        missing.append((subject["name"], lesson["name"], path))
        if not missing:
            messagebox.showinfo(
                APP_TITLE, f"Проверено файлов: {total}.\nВсе ссылки на файлы в порядке."
            )
            return
        lines = [f"Проверено файлов: {total}. Не найдено: {len(missing)}.\n"]
        for subj_name, lesson_name, path in missing:
            lines.append(f"«{subj_name}» → «{lesson_name}»:\n    {path}\n")
        self._show_report_window("Проверка файлов", "\n".join(lines))

    def _export_plan(self):
        path = filedialog.asksaveasfilename(
            title="Экспорт плана занятий",
            defaultextension=".txt",
            filetypes=[("Текстовый файл", "*.txt")],
            initialfile="план_занятий.txt",
            parent=self,
        )
        if not path:
            return
        lines = [APP_TITLE, "План учебных материалов", ""]
        # Дисциплины и занятия нумеровать нельзя: и то, и другое сейчас
        # выводится в алфавитном/настроенном порядке отображения, а не в
        # порядке преподавания — цифры вида "1.2" выглядели бы как учебная
        # последовательность, которой на самом деле нет. Поэтому просто
        # название + маркер, без сквозной нумерации.
        subjects_sorted = sorted(self.data["subjects"], key=lambda s: s["name"].lower())
        for subject in subjects_sorted:
            lines.append(subject["name"])
            lessons = list(subject["lessons"])
            if self.lesson_sort_mode == "alpha":
                lessons.sort(key=lambda l: l["name"].lower())
            for lesson in lessons:
                lines.append(f"   • {lesson['name']}")
                if lesson["files"]:
                    for fpath in lesson["files"]:
                        lines.append(f"        - {os.path.basename(fpath)}")
                else:
                    lines.append("        (файлов нет)")
            if not subject["lessons"]:
                lines.append("   (занятий нет)")
            lines.append("")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
        except OSError as e:
            messagebox.showerror(APP_TITLE, f"Не удалось сохранить файл:\n{e}")
            return
        messagebox.showinfo(APP_TITLE, f"План сохранён:\n{path}")


def main():
    if os.name == "nt":
        try:
            import ctypes

            try:
                # PROCESS_SYSTEM_DPI_AWARE — без этого Windows растягивает
                # окно как битмап на экранах с масштабированием, из-за чего
                # шрифт выглядит размытым.
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except (AttributeError, OSError):
                ctypes.windll.user32.SetProcessDPIAware()

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "vuc_tsu.TeacherFileManager"
            )
        except (AttributeError, OSError):
            pass
    app = TeacherFileManager()
    app.mainloop()


if __name__ == "__main__":
    main()
