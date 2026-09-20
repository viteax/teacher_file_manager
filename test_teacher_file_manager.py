"""
Автотесты для teacher_file_manager.pyw.

Это не попытка проверить вообще всё — это страховка именно от повторения
реальных багов, которые уже случались в проекте: регистр буквы диска в
путях (Windows их не различает, а обычное сравнение строк — различает),
потеря выделения после того, как список стал сортироваться по алфавиту,
задвоение записи при попытке восстановить пропавший файл, порча пути
соседнего занятия при переименовании ("Урок 1" внутри "Урок 10") и т.д.
Если в коде однажды снова появится что-то похожее — эти тесты должны
упасть раньше, чем это увидит преподаватель.

Как запустить (нужен рабочий Tk-дисплей — то есть локально на Windows,
не в headless CI):
    python -m unittest test_teacher_file_manager -v

Изоляция: каждый тест копирует teacher_file_manager.pyw во ВРЕМЕННУЮ папку
(через tempfile.mkdtemp, вне этого репозитория) и импортирует его оттуда.
Поскольку DATA_PATH/MATERIALS_PATH/TRASH_PATH внутри программы считаются
через get_app_dir() -> __file__, весь тест работает со своей изолированной
копией и никогда не трогает реальный data.json/Материалы/Корзина рядом с
программой. Временная папка удаляется после каждого теста.
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
APP_SOURCE = os.path.join(PROJECT_DIR, "teacher_file_manager.pyw")
ASSETS_SOURCE = os.path.join(PROJECT_DIR, "assets")
HELP_SOURCE = os.path.join(PROJECT_DIR, "Инструкция для капитана Щербы.txt")

_counter = 0


def _load_app_module(work_dir):
    """Копирует программу (+ assets, + инструкцию) в work_dir и
    импортирует её оттуда, чтобы get_app_dir() резолвился внутрь work_dir."""
    global _counter
    _counter += 1
    dest = os.path.join(work_dir, "teacher_file_manager.pyw")
    shutil.copyfile(APP_SOURCE, dest)
    if os.path.isdir(ASSETS_SOURCE):
        shutil.copytree(ASSETS_SOURCE, os.path.join(work_dir, "assets"))
    if os.path.isfile(HELP_SOURCE):
        shutil.copyfile(
            HELP_SOURCE, os.path.join(work_dir, "Инструкция для капитана Щербы.txt")
        )
    module_name = f"tfm_under_test_{_counter}"
    spec = importlib.util.spec_from_file_location(module_name, dest)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    if module.get_app_dir() != work_dir:
        raise AssertionError("изоляция теста не сработала — это баг в самом тесте")
    return module


class AppTestCase(unittest.TestCase):
    """Базовый класс: на каждый тест — изолированная копия приложения во
    временной папке, с заглушенными messagebox/askyesno, чтобы тесты не
    зависали на модальных окнах."""

    def setUp(self):
        self.work_dir = tempfile.mkdtemp(prefix="tfm_test_")
        self.tfm = _load_app_module(self.work_dir)
        self.tfm.messagebox.showinfo = lambda *a, **k: None
        self.tfm.messagebox.showwarning = lambda *a, **k: None
        self.tfm.messagebox.showerror = lambda *a, **k: None
        self.tfm.messagebox.askyesno = lambda *a, **k: True
        self.app = None

    def tearDown(self):
        if self.app is not None:
            self.app.destroy()
        shutil.rmtree(self.work_dir, ignore_errors=True)

    def start_app(self, data=None):
        """Пишет data.json (если передан) и поднимает главное окно."""
        if data is not None:
            with open(self.tfm.DATA_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        self.app = self.tfm.TeacherFileManager()
        self.app.update_idletasks()
        return self.app

    def write_file(self, path, content="content"):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path


class PureFunctionsTest(unittest.TestCase):
    """Функции без побочных эффектов — тестируются без поднятия Tk-окна и
    без изоляции через рабочую папку (сами по себе безопасны)."""

    def setUp(self):
        self.work_dir = tempfile.mkdtemp(prefix="tfm_test_pure_")
        self.tfm = _load_app_module(self.work_dir)

    def tearDown(self):
        shutil.rmtree(self.work_dir, ignore_errors=True)

    def test_format_size(self):
        self.assertEqual(self.tfm.format_size(0), "0 Б")
        self.assertEqual(self.tfm.format_size(500), "500 Б")
        self.assertEqual(self.tfm.format_size(2048), "2.0 КБ")
        self.assertEqual(self.tfm.format_size(5 * 1024 * 1024), "5.0 МБ")
        self.assertEqual(self.tfm.format_size(int(1.5 * 1024**3)), "1.5 ГБ")

    def test_sanitize_name_for_path_strips_invalid_chars(self):
        cleaned = self.tfm.sanitize_name_for_path('Тема: "1" / 2 <3>')
        for bad_char in '<>:"/\\|?*':
            self.assertNotIn(bad_char, cleaned)

    def test_sanitize_name_for_path_empty_falls_back(self):
        self.assertEqual(self.tfm.sanitize_name_for_path("   "), "без_названия")

    def test_sanitize_name_for_path_truncates_long_names(self):
        cleaned = self.tfm.sanitize_name_for_path("Ы" * 200)
        self.assertLessEqual(len(cleaned), 50)

    def test_unique_dest_path_avoids_disk_collisions(self):
        target_dir = os.path.join(self.work_dir, "target")
        os.makedirs(target_dir)
        first = self.tfm.unique_dest_path(target_dir, "file.txt")
        self.assertEqual(os.path.basename(first), "file.txt")
        with open(first, "w", encoding="utf-8") as f:
            f.write("x")
        second = self.tfm.unique_dest_path(target_dir, "file.txt")
        self.assertEqual(os.path.basename(second), "file (2).txt")

    def test_is_managed_copy(self):
        managed = os.path.join(self.tfm.MATERIALS_PATH, "Тема", "Занятие", "a.txt")
        external = os.path.join(self.work_dir, "external", "a.txt")
        self.assertTrue(self.tfm._is_managed_copy(managed))
        self.assertFalse(self.tfm._is_managed_copy(external))


class AutoDiscoveryTest(AppTestCase):
    """Автообнаружение файлов/папок, закинутых вручную через проводник."""

    def test_case_insensitive_scan_does_not_duplicate_files(self):
        # Баг 2026-09-20: путь, сохранённый с одной буквой диска, и путь,
        # который резолвит текущий запуск с другой буквой — один и тот же
        # физический файл, но разные строки. Сравнение должно это понимать.
        app = self.start_app()
        subject = {"name": "Тема", "lessons": [{"name": "Занятие", "files": []}]}
        app.data["subjects"] = [subject]
        lesson = subject["lessons"][0]
        real_path = self.write_file(
            os.path.join(app._lesson_materials_dir(subject, lesson), "file.txt")
        )
        drive, rest = os.path.splitdrive(real_path)
        stored_path_diff_case = drive.swapcase() + rest
        lesson["files"] = [stored_path_diff_case]

        added = app._scan_lesson_folder_for_new_files(subject, lesson)
        self.assertEqual(added, 0, "не должно считать один и тот же файл новым")
        self.assertEqual(len(lesson["files"]), 1)

    def test_discovers_brand_new_subject_and_lesson_folders(self):
        app = self.start_app(data={"subjects": [], "settings": {}})
        new_file = self.write_file(
            os.path.join(self.tfm.MATERIALS_PATH, "Новая дисциплина", "Новое занятие", "a.txt")
        )
        new_subjects, new_lessons = app._discover_new_subjects_and_lessons()
        self.assertEqual(new_subjects, ["Новая дисциплина"])
        self.assertEqual(new_lessons, [("Новая дисциплина", "Новое занятие")])
        subject = app.data["subjects"][0]
        self.assertEqual(subject["lessons"][0]["files"], [])

        added, _details = app._scan_all_lessons_for_new_files()
        self.assertEqual(added, 1)
        self.assertIn(new_file, subject["lessons"][0]["files"])

    def test_ignores_junk_files_and_does_not_recurse(self):
        app = self.start_app()
        subject = {"name": "Тема", "lessons": [{"name": "Занятие", "files": []}]}
        app.data["subjects"] = [subject]
        lesson = subject["lessons"][0]
        lesson_dir = app._lesson_materials_dir(subject, lesson)
        self.write_file(os.path.join(lesson_dir, "Thumbs.db"))
        self.write_file(os.path.join(lesson_dir, "sub", "nested.txt"))

        added = app._scan_lesson_folder_for_new_files(subject, lesson)
        self.assertEqual(added, 0)
        self.assertEqual(lesson["files"], [])


class SelectionAfterAddTest(AppTestCase):
    """Регрессия 2026-09-20: после сортировки по алфавиту выделение после
    добавления должно попадать на новый элемент, а не на tk.END."""

    def test_new_subject_is_selected_even_when_not_alphabetically_last(self):
        app = self.start_app(data={"subjects": [{"name": "Яблоко", "lessons": []}], "settings": {}})
        self.tfm.simpledialog.askstring = lambda *a, **k: "Августовская тема"
        app._add_subject()
        self.assertEqual(list(app.subject_list.get(0, "end")), ["Августовская тема", "Яблоко"])
        self.assertEqual(app.subject_list.curselection(), (0,))
        self.assertEqual(app.data["subjects"][app.selected_subject_idx]["name"], "Августовская тема")

    def test_new_lesson_is_selected_under_alpha_sort(self):
        app = self.start_app(
            data={
                "subjects": [{"name": "Тема", "lessons": [{"name": "Я-занятие", "files": []}]}],
                "settings": {"lesson_sort_mode": "alpha"},
            }
        )
        app.selected_subject_idx = 0
        app._refresh_lessons()
        self.tfm.simpledialog.askstring = lambda *a, **k: "А-занятие"
        app._add_lesson()
        self.assertEqual(list(app.lesson_list.get(0, "end")), ["А-занятие", "Я-занятие"])
        self.assertEqual(app.lesson_list.curselection(), (0,))


class TrashTest(AppTestCase):
    def test_remove_moves_managed_copy_to_trash_but_not_external_ref(self):
        app = self.start_app()
        subject = {"name": "Тема", "lessons": [{"name": "Занятие", "files": []}]}
        app.data["subjects"] = [subject]
        lesson = subject["lessons"][0]
        managed = self.write_file(
            os.path.join(app._lesson_materials_dir(subject, lesson), "managed.txt")
        )
        external = self.write_file(os.path.join(self.work_dir, "external", "ref.txt"))
        lesson["files"] = [managed, external]

        app.selected_subject_idx = 0
        app._refresh_lessons()
        app.selected_lesson_idx = 0
        app._refresh_files()
        app.file_list.selection_set(0, "end")
        app._remove_file()

        self.assertEqual(lesson["files"], [])
        self.assertFalse(os.path.exists(managed), "управляемая копия должна уехать в Корзина")
        self.assertTrue(os.path.exists(external), "внешняя ссылка не должна трогаться")
        trash_file = os.path.join(app._lesson_trash_dir(subject, lesson), "managed.txt")
        self.assertTrue(os.path.isfile(trash_file))

    def test_shared_file_not_trashed_while_still_referenced(self):
        # Старые базы, где один физический файл делят два занятия (раньше
        # была функция "Дублировать") — удаление одной ссылки не должно
        # утаскивать файл, пока другая ссылка ещё жива.
        app = self.start_app()
        subject = {
            "name": "Тема",
            "lessons": [
                {"name": "A", "files": []},
                {"name": "B", "files": []},
            ],
        }
        app.data["subjects"] = [subject]
        shared = self.write_file(
            os.path.join(app._lesson_materials_dir(subject, subject["lessons"][0]), "shared.txt")
        )
        subject["lessons"][0]["files"] = [shared]
        subject["lessons"][1]["files"] = [shared]

        app.selected_subject_idx = 0
        app._refresh_lessons()
        app.selected_lesson_idx = 0
        app._refresh_files()
        app.file_list.selection_set(0)
        app._remove_file()

        self.assertTrue(os.path.isfile(shared), "файл нужен другому занятию — трогать нельзя")
        self.assertEqual(subject["lessons"][1]["files"], [shared])

    def test_undo_restores_file_from_trash(self):
        app = self.start_app()
        subject = {"name": "Тема", "lessons": [{"name": "Занятие", "files": []}]}
        app.data["subjects"] = [subject]
        lesson = subject["lessons"][0]
        managed = self.write_file(
            os.path.join(app._lesson_materials_dir(subject, lesson), "a.txt")
        )
        lesson["files"] = [managed]

        app.selected_subject_idx = 0
        app._refresh_lessons()
        app.selected_lesson_idx = 0
        app._refresh_files()
        app.file_list.selection_set(0)
        app._remove_file()
        self.assertFalse(os.path.exists(managed))

        app._undo()
        subject_after = app.data["subjects"][0]
        self.assertEqual(subject_after["lessons"][0]["files"], [managed])
        self.assertTrue(os.path.exists(managed))

    def test_rename_lesson_does_not_corrupt_sibling_with_prefix_name(self):
        # Баг: "Урок 1" переименовали, а "Урок 10" — сосед по имени-префиксу
        # — не должен был вообще задеваться.
        app = self.start_app()
        subject = {
            "name": "Тема",
            "lessons": [
                {"name": "Урок 1", "files": []},
                {"name": "Урок 10", "files": []},
            ],
        }
        app.data["subjects"] = [subject]
        lesson1, lesson10 = subject["lessons"]
        file1 = self.write_file(
            os.path.join(app._lesson_materials_dir(subject, lesson1), "a.txt")
        )
        file10 = self.write_file(
            os.path.join(app._lesson_materials_dir(subject, lesson10), "b.txt")
        )
        lesson1["files"] = [file1]
        lesson10["files"] = [file10]

        self.tfm.simpledialog.askstring = lambda *a, **k: "Урок 1 (переименован)"
        app.selected_subject_idx = 0
        app._refresh_lessons()
        app.selected_lesson_idx = 0
        app._rename_lesson()

        self.assertEqual(lesson10["name"], "Урок 10")
        self.assertEqual(lesson10["files"], [file10], "путь соседа не должен был измениться")
        self.assertTrue(os.path.isfile(file10))

    def test_trash_stats_appear_only_when_nonempty(self):
        app = self.start_app()
        self.assertEqual(app._trash_count, 0)
        self.assertNotIn("Корзина", app.status_var.get())

        subject = {"name": "Тема", "lessons": [{"name": "Занятие", "files": []}]}
        app.data["subjects"] = [subject]
        lesson = subject["lessons"][0]
        managed = self.write_file(
            os.path.join(app._lesson_materials_dir(subject, lesson), "a.txt"), "12345"
        )
        lesson["files"] = [managed]
        app.selected_subject_idx = 0
        app._refresh_lessons()
        app.selected_lesson_idx = 0
        app._refresh_files()
        app.file_list.selection_set(0)
        app._remove_file()

        self.assertEqual(app._trash_count, 1)
        self.assertIn("Корзина", app.status_var.get())


class RestoreMissingFileTest(AppTestCase):
    def test_readding_missing_file_restores_instead_of_duplicating(self):
        app = self.start_app()
        subject = {"name": "Тема", "lessons": [{"name": "Занятие", "files": []}]}
        app.data["subjects"] = [subject]
        lesson = subject["lessons"][0]
        app.selected_subject_idx = 0
        app._refresh_lessons()
        app.selected_lesson_idx = 0
        app._refresh_files()

        src = self.write_file(os.path.join(self.work_dir, "src", "lecture.txt"), "v1")
        self.tfm.filedialog.askopenfilenames = lambda **k: (src,)
        app._add_file()
        self.assertEqual(len(lesson["files"]), 1)
        tracked_path = lesson["files"][0]

        os.remove(tracked_path)  # физически пропал

        with open(src, "w", encoding="utf-8") as f:
            f.write("v2")
        app._add_file()

        self.assertEqual(len(lesson["files"]), 1, "должна остаться ровно одна запись")
        self.assertEqual(lesson["files"][0], tracked_path)
        self.assertTrue(os.path.isfile(tracked_path))

    def test_different_file_with_same_basename_still_gets_second_entry(self):
        app = self.start_app()
        subject = {"name": "Тема", "lessons": [{"name": "Занятие", "files": []}]}
        app.data["subjects"] = [subject]
        lesson = subject["lessons"][0]
        app.selected_subject_idx = 0
        app._refresh_lessons()
        app.selected_lesson_idx = 0
        app._refresh_files()

        src_dir = os.path.join(self.work_dir, "src")
        src1 = self.write_file(os.path.join(src_dir, "lecture.txt"), "v1")
        self.tfm.filedialog.askopenfilenames = lambda **k: (src1,)
        app._add_file()
        self.assertEqual(len(lesson["files"]), 1)

        # исходный файл всё ещё на месте (НЕ пропал) — второй файл с тем же
        # именем должен получить нормальный "(2)", а не считаться восстановлением
        src2_dir = os.path.join(self.work_dir, "src2")
        src2 = self.write_file(os.path.join(src2_dir, "lecture.txt"), "different content")
        self.tfm.filedialog.askopenfilenames = lambda **k: (src2,)
        app._add_file()
        self.assertEqual(len(lesson["files"]), 2)


class ExportPlanTest(AppTestCase):
    def test_plan_has_no_numbering_and_is_alphabetically_sorted(self):
        app = self.start_app(
            data={
                "subjects": [
                    {"name": "Огневая подготовка", "lessons": [{"name": "АК47", "files": []}]},
                    {"name": "Военная топография", "lessons": [{"name": "Карты", "files": []}]},
                ],
                "settings": {},
            }
        )
        out_path = os.path.join(self.work_dir, "plan.txt")
        self.tfm.filedialog.asksaveasfilename = lambda **k: out_path
        app._export_plan()

        with open(out_path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()

        self.assertFalse(
            any(l.strip() and l.strip()[0].isdigit() for l in lines),
            "ни одна строка не должна начинаться с цифры (это не порядок преподавания)",
        )
        self.assertLess(lines.index("Военная топография"), lines.index("Огневая подготовка"))
        self.assertIn("   • Карты", lines)


class SubjectSortTest(AppTestCase):
    def test_subject_list_is_always_alphabetical(self):
        app = self.start_app(
            data={
                "subjects": [
                    {"name": "Яблоко", "lessons": []},
                    {"name": "Ананас", "lessons": []},
                    {"name": "Вишня", "lessons": []},
                ],
                "settings": {},
            }
        )
        self.assertEqual(list(app.subject_list.get(0, "end")), ["Ананас", "Вишня", "Яблоко"])


class MultiStepUndoTest(AppTestCase):
    """2026-09-21: отмена теперь работает на несколько шагов (стек, а не
    один слот), и не только для удалений — добавление, переименование,
    перестановка тоже отменяются."""

    def test_undo_add_subject(self):
        app = self.start_app(data={"subjects": [], "settings": {}})
        self.tfm.simpledialog.askstring = lambda *a, **k: "Новая дисциплина"
        app._add_subject()
        self.assertEqual(len(app.data["subjects"]), 1)

        app._undo()
        self.assertEqual(app.data["subjects"], [])

    def test_undo_rename_subject_reverts_folder_on_disk_too(self):
        app = self.start_app()
        subject = {"name": "Старое имя", "lessons": [{"name": "Занятие", "files": []}]}
        app.data["subjects"] = [subject]
        lesson = subject["lessons"][0]
        managed = self.write_file(
            os.path.join(app._lesson_materials_dir(subject, lesson), "a.txt")
        )
        lesson["files"] = [managed]
        old_dir = app._subject_materials_dir(subject)

        self.tfm.simpledialog.askstring = lambda *a, **k: "Новое имя"
        app.selected_subject_idx = 0
        app._rename_subject()
        new_dir = app._subject_materials_dir(app.data["subjects"][0])
        self.assertTrue(os.path.isdir(new_dir))
        self.assertFalse(os.path.isdir(old_dir))

        app._undo()
        restored_subject = app.data["subjects"][0]
        self.assertEqual(restored_subject["name"], "Старое имя")
        self.assertTrue(os.path.isdir(old_dir), "папка должна была переехать обратно")
        self.assertFalse(os.path.isdir(new_dir))
        restored_file = restored_subject["lessons"][0]["files"][0]
        self.assertTrue(os.path.isfile(restored_file))

    def test_undo_add_file_deletes_the_copy(self):
        app = self.start_app()
        subject = {"name": "Тема", "lessons": [{"name": "Занятие", "files": []}]}
        app.data["subjects"] = [subject]
        lesson = subject["lessons"][0]
        app.selected_subject_idx = 0
        app._refresh_lessons()
        app.selected_lesson_idx = 0
        app._refresh_files()

        src = self.write_file(os.path.join(self.work_dir, "src", "lecture.txt"))
        self.tfm.filedialog.askopenfilenames = lambda **k: (src,)
        app._add_file()
        self.assertEqual(len(lesson["files"]), 1)
        copied_path = lesson["files"][0]
        self.assertTrue(os.path.isfile(copied_path))

        app._undo()
        lesson = app.data["subjects"][0]["lessons"][0]
        self.assertEqual(lesson["files"], [])
        self.assertFalse(os.path.isfile(copied_path), "копия должна была удалиться")

    def test_multiple_undo_steps_in_sequence_lifo_order(self):
        app = self.start_app(data={"subjects": [], "settings": {}})
        self.tfm.simpledialog.askstring = lambda *a, **k: "Дисциплина 1"
        app._add_subject()
        self.tfm.simpledialog.askstring = lambda *a, **k: "Дисциплина 2"
        app._add_subject()
        self.tfm.simpledialog.askstring = lambda *a, **k: "Дисциплина 3"
        app._add_subject()
        names = sorted(s["name"] for s in app.data["subjects"])
        self.assertEqual(names, ["Дисциплина 1", "Дисциплина 2", "Дисциплина 3"])

        app._undo()
        names = sorted(s["name"] for s in app.data["subjects"])
        self.assertEqual(names, ["Дисциплина 1", "Дисциплина 2"])

        app._undo()
        names = sorted(s["name"] for s in app.data["subjects"])
        self.assertEqual(names, ["Дисциплина 1"])

        app._undo()
        self.assertEqual(app.data["subjects"], [])

        # стек пуст — кнопка отключена, лишний Ctrl+Z ничего не ломает
        self.assertIn("disabled", app.undo_btn.state())
        app._undo()
        self.assertEqual(app.data["subjects"], [])

    def test_undo_stack_is_capped(self):
        app = self.start_app(data={"subjects": [], "settings": {}})
        for i in range(self.tfm.MAX_UNDO_STEPS + 5):
            self.tfm.simpledialog.askstring = lambda *a, i=i, **k: f"Дисциплина {i}"
            app._add_subject()
        self.assertEqual(len(app._undo_stack), self.tfm.MAX_UNDO_STEPS)
        self.assertEqual(len(app.data["subjects"]), self.tfm.MAX_UNDO_STEPS + 5)

    def test_theme_and_font_changes_do_not_touch_undo_stack(self):
        app = self.start_app(data={"subjects": [], "settings": {}})
        self.tfm.simpledialog.askstring = lambda *a, **k: "Дисциплина"
        app._add_subject()
        self.assertEqual(len(app._undo_stack), 1)

        app._toggle_theme()
        app._change_font_size(1)
        self.assertEqual(len(app._undo_stack), 1, "настройки не должны попадать в историю отмены")


if __name__ == "__main__":
    unittest.main()
