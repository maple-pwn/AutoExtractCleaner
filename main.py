#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import json
import time
import shutil
import logging
import threading
import zipfile
import tarfile
from pathlib import Path
from typing import Optional, Set, Dict, Any
from datetime import datetime

if sys.platform == "win32":
    import winreg

try:
    import pystray
    from PIL import Image, ImageDraw
    from watchdog.events import FileSystemEventHandler

    # Use Windows-specific observer for better reliability
    if sys.platform == "win32":
        from watchdog.observers import Observer
    else:
        from watchdog.observers import Observer
    import py7zr
    import rarfile
except ImportError as e:
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(
        "Error",
        f"Missing dependency: {e}\nPlease run: pip install pystray Pillow watchdog py7zr rarfile",
    )
    sys.exit(1)

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

APP_NAME = "AutoExtractCleaner"
APP_TITLE = "压缩包自动清理"
CONFIG_FILE = "config.json"
LOG_FILE = "app.log"

ARCHIVE_EXTENSIONS = {
    ".zip",
    ".rar",
    ".7z",
    ".tar",
    ".gz",
    ".tgz",
    ".tar.gz",
    ".tar.bz2",
    ".tar.xz",
    ".bz2",
    ".xz",
}


def get_app_data_path() -> Path:
    if sys.platform == "win32":
        app_data = Path(os.environ.get("APPDATA", Path.home()))
    else:
        app_data = Path.home() / ".config"
    app_dir = app_data / APP_NAME
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


def setup_logging():
    log_path = get_app_data_path() / LOG_FILE
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    return logging.getLogger(__name__)


def get_exe_path() -> str:
    if getattr(sys, "frozen", False):
        return sys.executable
    return os.path.abspath(sys.argv[0])


class ConfigManager:
    DEFAULT_CONFIG = {
        "watch_folders": [],
        "auto_start": False,
        "delete_after_extract": True,
        "delete_delay_seconds": 3,
        "auto_monitor": True,
        "extract_to_subfolder": True,
        "supported_formats": list(ARCHIVE_EXTENSIONS),
    }

    def __init__(self):
        self.config_path = get_app_data_path() / CONFIG_FILE
        self.config = self.load()

    def load(self) -> Dict[str, Any]:
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    config = self.DEFAULT_CONFIG.copy()
                    config.update(loaded)
                    return config
            except Exception as e:
                logging.error(f"Failed to load config: {e}")
        return self.DEFAULT_CONFIG.copy()

    def save(self):
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"Failed to save config: {e}")

    def get(self, key: str, default=None):
        return self.config.get(key, default)

    def set(self, key: str, value):
        self.config[key] = value
        self.save()


class AutoStartManager:
    REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"

    @staticmethod
    def is_enabled() -> bool:
        if sys.platform != "win32":
            return False
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, AutoStartManager.REG_PATH, 0, winreg.KEY_READ
            )
            try:
                winreg.QueryValueEx(key, APP_NAME)
                return True
            except WindowsError:
                return False
            finally:
                winreg.CloseKey(key)
        except WindowsError:
            return False

    @staticmethod
    def enable():
        if sys.platform != "win32":
            return False
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                AutoStartManager.REG_PATH,
                0,
                winreg.KEY_SET_VALUE,
            )
            exe_path = get_exe_path()
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{exe_path}"')
            winreg.CloseKey(key)
            logging.info("Auto-start enabled")
            return True
        except WindowsError as e:
            logging.error(f"Failed to enable auto-start: {e}")
            return False

    @staticmethod
    def disable():
        if sys.platform != "win32":
            return False
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                AutoStartManager.REG_PATH,
                0,
                winreg.KEY_SET_VALUE,
            )
            try:
                winreg.DeleteValue(key, APP_NAME)
                logging.info("Auto-start disabled")
            except WindowsError:
                pass
            winreg.CloseKey(key)
            return True
        except WindowsError as e:
            logging.error(f"Failed to disable auto-start: {e}")
            return False


class ArchiveExtractor:
    @staticmethod
    def get_archive_type(filepath: str) -> Optional[str]:
        lower_path = filepath.lower()
        if lower_path.endswith(".zip"):
            return "zip"
        elif lower_path.endswith(".rar"):
            return "rar"
        elif lower_path.endswith(".7z"):
            return "7z"
        elif lower_path.endswith((".tar.gz", ".tgz")):
            return "tar.gz"
        elif lower_path.endswith(".tar.bz2"):
            return "tar.bz2"
        elif lower_path.endswith(".tar.xz"):
            return "tar.xz"
        elif lower_path.endswith(".tar"):
            return "tar"
        elif lower_path.endswith(".gz") and not lower_path.endswith(".tar.gz"):
            return "gz"
        elif lower_path.endswith(".bz2") and not lower_path.endswith(".tar.bz2"):
            return "bz2"
        elif lower_path.endswith(".xz") and not lower_path.endswith(".tar.xz"):
            return "xz"
        return None

    @staticmethod
    def get_base_name(filepath: str) -> str:
        basename = os.path.basename(filepath)
        for ext in [
            ".tar.gz",
            ".tar.bz2",
            ".tar.xz",
            ".tgz",
            ".zip",
            ".rar",
            ".7z",
            ".tar",
            ".gz",
            ".bz2",
            ".xz",
        ]:
            if basename.lower().endswith(ext):
                return basename[: -len(ext)]
        return basename

    @staticmethod
    def extract(
        filepath: str, dest_dir: Optional[str] = None, to_subfolder: bool = True
    ) -> tuple:
        if not os.path.exists(filepath):
            return False, f"File not found: {filepath}"

        archive_type = ArchiveExtractor.get_archive_type(filepath)
        if not archive_type:
            return False, f"Unsupported format: {filepath}"

        if dest_dir is None:
            dest_dir = os.path.dirname(filepath)

        if to_subfolder:
            basename = ArchiveExtractor.get_base_name(filepath)
            dest_dir = os.path.join(dest_dir, basename)

        os.makedirs(dest_dir, exist_ok=True)

        try:
            if archive_type == "zip":
                with zipfile.ZipFile(filepath, "r") as zf:
                    zf.extractall(dest_dir)
            elif archive_type == "rar":
                with rarfile.RarFile(filepath, "r") as rf:
                    rf.extractall(dest_dir)
            elif archive_type == "7z":
                with py7zr.SevenZipFile(filepath, mode="r") as szf:
                    szf.extractall(dest_dir)
            elif archive_type in ("tar", "tar.gz", "tar.bz2", "tar.xz"):
                mode = {
                    "tar": "r",
                    "tar.gz": "r:gz",
                    "tar.bz2": "r:bz2",
                    "tar.xz": "r:xz",
                }[archive_type]
                with tarfile.open(filepath, mode) as tf:
                    tf.extractall(dest_dir)
            elif archive_type == "gz":
                import gzip

                output_path = os.path.join(dest_dir, os.path.basename(filepath)[:-3])
                with gzip.open(filepath, "rb") as f_in:
                    with open(output_path, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)
            elif archive_type == "bz2":
                import bz2

                output_path = os.path.join(dest_dir, os.path.basename(filepath)[:-4])
                with bz2.open(filepath, "rb") as f_in:
                    with open(output_path, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)
            elif archive_type == "xz":
                import lzma

                output_path = os.path.join(dest_dir, os.path.basename(filepath)[:-3])
                with lzma.open(filepath, "rb") as f_in:
                    with open(output_path, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)

            logging.info(f"Extracted: {filepath} -> {dest_dir}")
            return True, f"Extracted to: {dest_dir}"
        except Exception as e:
            logging.error(f"Extract failed {filepath}: {e}")
            return False, f"Extract failed: {str(e)}"


class ArchiveWatcher:
    def __init__(self, config: ConfigManager, on_status_change=None):
        self.config = config
        self.observer = None
        self.handlers: Dict[str, ArchiveEventHandler] = {}
        self.running = False
        self.on_status_change = on_status_change
        self.pending_deletions: Dict[str, float] = {}
        self.lock = threading.Lock()

    def start(self):
        if self.running:
            return

        watch_folders = self.config.get("watch_folders", [])
        if not watch_folders:
            logging.warning("No folders configured for monitoring")
            return

        self.observer = Observer()
        for folder in watch_folders:
            if os.path.exists(folder):
                handler = ArchiveEventHandler(self, folder)
                self.handlers[folder] = handler
                self.observer.schedule(handler, folder, recursive=False)
                logging.info(f"Monitoring: {folder}")

        try:
            self.observer.start()
            self.running = True
            logging.info("Monitoring started")
            if self.on_status_change:
                self.on_status_change(True)
        except Exception as e:
            logging.error(f"Failed to start monitoring: {e}")

    def stop(self):
        if not self.running:
            return

        try:
            if self.observer:
                self.observer.stop()
                self.observer.join(timeout=5)
        except Exception as e:
            logging.error(f"Error stopping observer: {e}")

        self.running = False
        self.handlers.clear()
        self.observer = None

        if self.on_status_change:
            self.on_status_change(False)
        logging.info("Monitoring stopped")

    def is_archive(self, filepath: str) -> bool:
        lower_path = filepath.lower()
        supported = self.config.get("supported_formats", ARCHIVE_EXTENSIONS)
        return any(lower_path.endswith(ext) for ext in supported)

    def schedule_deletion(self, filepath: str):
        if not self.config.get("delete_after_extract", True):
            return

        with self.lock:
            if filepath in self.pending_deletions:
                return
            self.pending_deletions[filepath] = time.time()

        delay = self.config.get("delete_delay_seconds", 3)
        logging.info(f"Scheduled deletion in {delay}s: {filepath}")

        def do_delete():
            time.sleep(delay if delay else 3)
            try:
                if os.path.exists(filepath):
                    filename = os.path.basename(filepath)
                    os.remove(filepath)
                    logging.info(f"已删除压缩包: {filepath}")
                    self._show_notification(f"已删除: {filename}")
            except Exception as e:
                logging.error(f"Delete failed {filepath}: {e}")
            finally:
                with self.lock:
                    self.pending_deletions.pop(filepath, None)

        threading.Thread(target=do_delete, daemon=True).start()

    def _show_notification(self, message: str):
        try:
            if sys.platform == "win32":
                from win10toast import ToastNotifier

                toaster = ToastNotifier()
                toaster.show_toast(
                    APP_TITLE, message, duration=3, threaded=True, icon_path=None
                )
        except:
            pass


class ArchiveEventHandler(FileSystemEventHandler):
    def __init__(self, watcher: ArchiveWatcher, watch_folder: str):
        super().__init__()
        self.watcher = watcher
        self.watch_folder = watch_folder
        self.known_archives: Dict[str, str] = {}
        self.known_folders: Set[str] = set()
        self._scan_existing()
        self._start_periodic_scan()

    def _scan_existing(self):
        try:
            for item in os.listdir(self.watch_folder):
                filepath = os.path.join(self.watch_folder, item)
                if os.path.isfile(filepath) and self.watcher.is_archive(filepath):
                    base_name = ArchiveExtractor.get_base_name(filepath)
                    self.known_archives[base_name.lower()] = filepath
                    logging.info(f"Tracking archive: {os.path.basename(filepath)}")
                elif os.path.isdir(filepath):
                    self.known_folders.add(os.path.basename(filepath).lower())
        except Exception as e:
            logging.error(f"Error scanning folder: {e}")

    def _start_periodic_scan(self):
        def scan_loop():
            while self.watcher.running:
                time.sleep(5)
                self._check_for_new_folders()

        threading.Thread(target=scan_loop, daemon=True).start()

    def _check_for_new_folders(self):
        try:
            current_folders = set()
            for item in os.listdir(self.watch_folder):
                filepath = os.path.join(self.watch_folder, item)
                if os.path.isdir(filepath):
                    current_folders.add(item.lower())

            new_folders = current_folders - self.known_folders
            for folder_name in new_folders:
                if folder_name in self.known_archives:
                    archive_path = self.known_archives[folder_name]
                    logging.info(f"Periodic scan: found extraction {folder_name}")
                    self.watcher.schedule_deletion(archive_path)

            self.known_folders = current_folders
        except Exception as e:
            logging.error(f"Periodic scan error: {e}")

    def on_created(self, event):
        try:
            if event.is_directory:
                dir_name = os.path.basename(event.src_path).lower()
                logging.debug(f"Directory created: {event.src_path}")

                if dir_name in self.known_archives:
                    archive_path = self.known_archives[dir_name]
                    logging.info(
                        f"Detected extraction: {dir_name} -> scheduling deletion of {archive_path}"
                    )
                    self.watcher.schedule_deletion(archive_path)
            else:
                filepath = event.src_path
                if self.watcher.is_archive(filepath):
                    base_name = ArchiveExtractor.get_base_name(filepath)
                    self.known_archives[base_name.lower()] = filepath
                    logging.info(f"New archive detected: {filepath}")
        except Exception as e:
            logging.error(f"Error in on_created: {e}")

    def on_deleted(self, event):
        try:
            if not event.is_directory:
                filepath = event.src_path
                if self.watcher.is_archive(filepath):
                    base_name = ArchiveExtractor.get_base_name(filepath).lower()
                    self.known_archives.pop(base_name, None)
                    logging.debug(f"Archive removed from tracking: {filepath}")
        except Exception as e:
            logging.error(f"Error in on_deleted: {e}")

    def on_modified(self, event):
        pass


class SettingsWindow:
    def __init__(self, config: ConfigManager, watcher: ArchiveWatcher):
        self.config = config
        self.watcher = watcher
        self.window = None

    def show(self):
        if self.window is not None:
            try:
                self.window.lift()
                self.window.focus_force()
                return
            except:
                self.window = None

        self.window = tk.Tk()
        self.window.title(f"{APP_TITLE} - 设置")
        self.window.geometry("550x450")
        self.window.resizable(True, True)

        self._create_widgets()
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)

        try:
            self.window.mainloop()
        except Exception as e:
            logging.error(f"Settings window error: {e}")

    def _create_widgets(self):
        notebook = ttk.Notebook(self.window)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        folder_frame = ttk.Frame(notebook, padding=10)
        notebook.add(folder_frame, text="监控文件夹")

        list_frame = ttk.Frame(folder_frame)
        list_frame.pack(fill=tk.BOTH, expand=True)

        self.folder_listbox = tk.Listbox(list_frame, height=8)
        self.folder_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(
            list_frame, orient=tk.VERTICAL, command=self.folder_listbox.yview
        )
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.folder_listbox.config(yscrollcommand=scrollbar.set)

        for folder in self.config.get("watch_folders", []):
            self.folder_listbox.insert(tk.END, folder)

        btn_frame = ttk.Frame(folder_frame)
        btn_frame.pack(fill=tk.X, pady=10)

        ttk.Button(btn_frame, text="添加文件夹", command=self._add_folder).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(btn_frame, text="移除", command=self._remove_folder).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(btn_frame, text="添加下载文件夹", command=self._add_downloads).pack(
            side=tk.LEFT, padx=5
        )

        general_frame = ttk.Frame(notebook, padding=10)
        notebook.add(general_frame, text="常规设置")

        self.auto_start_var = tk.BooleanVar(value=AutoStartManager.is_enabled())
        ttk.Checkbutton(
            general_frame,
            text="开机自动启动",
            variable=self.auto_start_var,
            command=self._toggle_auto_start,
        ).pack(anchor=tk.W, pady=5)

        self.auto_monitor_var = tk.BooleanVar(
            value=self.config.get("auto_monitor", True)
        )
        ttk.Checkbutton(
            general_frame, text="启动时自动开始监控", variable=self.auto_monitor_var
        ).pack(anchor=tk.W, pady=5)

        self.delete_after_var = tk.BooleanVar(
            value=self.config.get("delete_after_extract", True)
        )
        ttk.Checkbutton(
            general_frame,
            text="解压后自动删除压缩包",
            variable=self.delete_after_var,
        ).pack(anchor=tk.W, pady=5)

        self.subfolder_var = tk.BooleanVar(
            value=self.config.get("extract_to_subfolder", True)
        )
        ttk.Checkbutton(
            general_frame, text="解压到同名子文件夹", variable=self.subfolder_var
        ).pack(anchor=tk.W, pady=5)

        delay_frame = ttk.Frame(general_frame)
        delay_frame.pack(anchor=tk.W, pady=5)
        ttk.Label(delay_frame, text="删除延迟(秒):").pack(side=tk.LEFT)
        self.delay_var = tk.StringVar(
            value=str(self.config.get("delete_delay_seconds", 3))
        )
        ttk.Spinbox(
            delay_frame, from_=1, to=60, width=5, textvariable=self.delay_var
        ).pack(side=tk.LEFT, padx=5)

        extract_frame = ttk.Frame(notebook, padding=10)
        notebook.add(extract_frame, text="手动解压")

        ttk.Label(extract_frame, text="选择压缩包进行解压").pack(pady=10)
        ttk.Button(extract_frame, text="选择压缩包", command=self._manual_extract).pack(
            pady=10
        )

        ttk.Label(extract_frame, text="操作日志:").pack(anchor=tk.W)
        self.log_text = tk.Text(extract_frame, height=8, state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True, pady=5)

        bottom_frame = ttk.Frame(self.window)
        bottom_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Button(bottom_frame, text="保存", command=self._save_settings).pack(
            side=tk.RIGHT, padx=5
        )
        ttk.Button(bottom_frame, text="关闭", command=self._on_close).pack(
            side=tk.RIGHT, padx=5
        )

    def _add_folder(self):
        folder = filedialog.askdirectory(title="选择要监控的文件夹")
        if folder:
            if folder not in self.folder_listbox.get(0, tk.END):
                self.folder_listbox.insert(tk.END, folder)

    def _remove_folder(self):
        selection = self.folder_listbox.curselection()
        if selection:
            self.folder_listbox.delete(selection[0])

    def _add_downloads(self):
        downloads = str(Path.home() / "Downloads")
        if downloads not in self.folder_listbox.get(0, tk.END):
            self.folder_listbox.insert(tk.END, downloads)

    def _toggle_auto_start(self):
        if self.auto_start_var.get():
            AutoStartManager.enable()
        else:
            AutoStartManager.disable()

    def _manual_extract(self):
        filetypes = [
            ("压缩包", "*.zip *.rar *.7z *.tar *.tar.gz *.tgz *.tar.bz2 *.tar.xz"),
            ("所有文件", "*.*"),
        ]

        filepath = filedialog.askopenfilename(title="选择压缩包", filetypes=filetypes)

        if filepath:
            self._log(f"正在解压: {filepath}")
            success, msg = ArchiveExtractor.extract(
                filepath, to_subfolder=self.subfolder_var.get()
            )
            self._log(msg)

            if success and self.delete_after_var.get():
                if messagebox.askyesno("确认", "是否删除原压缩包?"):
                    try:
                        os.remove(filepath)
                        self._log(f"已删除: {filepath}")
                    except Exception as e:
                        self._log(f"删除失败: {e}")

    def _log(self, message: str):
        self.log_text.config(state=tk.NORMAL)
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _save_settings(self):
        folders = list(self.folder_listbox.get(0, tk.END))
        self.config.set("watch_folders", folders)
        self.config.set("auto_monitor", self.auto_monitor_var.get())
        self.config.set("delete_after_extract", self.delete_after_var.get())
        self.config.set("extract_to_subfolder", self.subfolder_var.get())
        try:
            delay = int(self.delay_var.get())
            self.config.set("delete_delay_seconds", max(1, min(60, delay)))
        except:
            pass

        messagebox.showinfo("提示", "设置已保存！\n重启监控后生效。")

    def _on_close(self):
        if self.window:
            self.window.destroy()
            self.window = None


class TrayApp:
    def __init__(self):
        self.config = ConfigManager()
        self.watcher = ArchiveWatcher(self.config, self._on_watcher_status_change)
        self.settings_window = SettingsWindow(self.config, self.watcher)
        self.icon = None
        self.monitoring = False

    def _create_icon_image(self, color="green") -> Image.Image:
        size = 64
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)

        if color == "green":
            fill_color = (76, 175, 80, 255)
        else:
            fill_color = (158, 158, 158, 255)

        draw.rectangle([8, 4, 48, 60], fill=fill_color, outline=(255, 255, 255, 255))
        draw.polygon([(48, 4), (56, 12), (48, 12)], fill=(255, 255, 255, 200))
        draw.rectangle([12, 24, 44, 44], fill=(255, 255, 255, 200))

        return image

    def _create_menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem(
                lambda item: "● 监控中" if self.monitoring else "○ 已停止",
                None,
                enabled=False,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda item: "停止监控" if self.monitoring else "开始监控",
                self._toggle_monitoring,
            ),
            pystray.MenuItem("设置", self._show_settings),
            pystray.MenuItem("手动解压", self._manual_extract),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "开机自启",
                self._toggle_autostart,
                checked=lambda item: AutoStartManager.is_enabled(),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", self._quit),
        )

    def _toggle_monitoring(self, icon=None, item=None):
        if self.monitoring:
            self.watcher.stop()
        else:
            self.watcher.start()

    def _on_watcher_status_change(self, is_running: bool):
        self.monitoring = is_running
        if self.icon:
            self.icon.icon = self._create_icon_image("green" if is_running else "gray")
            self.icon.update_menu()

    def _show_settings(self, icon=None, item=None):
        threading.Thread(target=self.settings_window.show, daemon=True).start()

    def _manual_extract(self, icon=None, item=None):
        def do_extract():
            root = tk.Tk()
            root.withdraw()

            filetypes = [
                (
                    "压缩包",
                    "*.zip *.rar *.7z *.tar *.tar.gz *.tgz *.tar.bz2 *.tar.xz",
                ),
                ("所有文件", "*.*"),
            ]
            filepath = filedialog.askopenfilename(
                title="选择压缩包", filetypes=filetypes
            )

            if filepath:
                success, msg = ArchiveExtractor.extract(
                    filepath, to_subfolder=self.config.get("extract_to_subfolder", True)
                )

                if success:
                    if self.config.get("delete_after_extract", True):
                        if messagebox.askyesno(
                            "解压成功", f"{msg}\n\n是否删除原压缩包?"
                        ):
                            try:
                                os.remove(filepath)
                            except Exception as e:
                                messagebox.showerror("错误", f"删除失败: {e}")
                    else:
                        messagebox.showinfo("成功", msg)
                else:
                    messagebox.showerror("错误", msg)

            root.destroy()

        threading.Thread(target=do_extract, daemon=True).start()

    def _toggle_autostart(self, icon=None, item=None):
        if AutoStartManager.is_enabled():
            AutoStartManager.disable()
        else:
            AutoStartManager.enable()

    def _quit(self, icon=None, item=None):
        logging.info("Exiting application")
        self.watcher.stop()
        if self.icon:
            self.icon.stop()

    def run(self):
        logger = setup_logging()
        logger.info(f"{APP_TITLE} started")

        if self.config.get("auto_monitor", True):
            self.watcher.start()

        self.icon = pystray.Icon(
            APP_NAME,
            self._create_icon_image("green" if self.monitoring else "gray"),
            APP_TITLE,
            self._create_menu(),
        )

        try:
            self.icon.run()
        except Exception as e:
            logger.error(f"Tray icon error: {e}")


def main():
    logger = setup_logging()

    try:
        app = TrayApp()
        app.run()
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
