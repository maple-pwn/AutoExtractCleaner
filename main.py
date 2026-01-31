#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Auto Extract Cleaner - 压缩包解压后自动删除工具
功能：
1. 系统托盘运行
2. 开机自启动
3. 监控文件夹，解压后自动删除压缩包
4. 内置解压功能
5. 支持 zip/rar/7z/tar/gz 等格式
"""

import os
import sys
import json
import time
import shutil
import logging
import threading
import winreg
import zipfile
import tarfile
from pathlib import Path
from typing import Optional, Set, Dict, Any
from datetime import datetime

# Third-party imports
try:
    import pystray
    from PIL import Image, ImageDraw
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    import py7zr
    import rarfile
except ImportError as e:
    print(f"缺少依赖: {e}")
    print("请运行: pip install -r requirements.txt")
    sys.exit(1)

# Tkinter for settings UI
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ============================================================================
# 常量定义
# ============================================================================
APP_NAME = "AutoExtractCleaner"
APP_TITLE = "压缩包自动清理工具"
CONFIG_FILE = "config.json"
LOG_FILE = "app.log"

# 支持的压缩格式
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


# ============================================================================
# 日志配置
# ============================================================================
def setup_logging():
    """配置日志系统"""
    log_path = get_app_data_path() / LOG_FILE
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    return logging.getLogger(__name__)


def get_app_data_path() -> Path:
    """获取应用数据目录"""
    if sys.platform == "win32":
        app_data = Path(os.environ.get("APPDATA", Path.home()))
    else:
        app_data = Path.home() / ".config"

    app_dir = app_data / APP_NAME
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


def get_exe_path() -> str:
    """获取当前可执行文件路径"""
    if getattr(sys, "frozen", False):
        return sys.executable
    return os.path.abspath(sys.argv[0])


# ============================================================================
# 配置管理
# ============================================================================
class ConfigManager:
    """配置管理器"""

    DEFAULT_CONFIG = {
        "watch_folders": [],
        "auto_start": False,
        "delete_after_extract": True,
        "delete_delay_seconds": 5,
        "auto_monitor": True,
        "notification_enabled": True,
        "extract_to_subfolder": True,
        "supported_formats": list(ARCHIVE_EXTENSIONS),
    }

    def __init__(self):
        self.config_path = get_app_data_path() / CONFIG_FILE
        self.config = self.load()

    def load(self) -> Dict[str, Any]:
        """加载配置"""
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    # 合并默认配置
                    config = self.DEFAULT_CONFIG.copy()
                    config.update(loaded)
                    return config
            except Exception as e:
                logging.error(f"加载配置失败: {e}")
        return self.DEFAULT_CONFIG.copy()

    def save(self):
        """保存配置"""
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"保存配置失败: {e}")

    def get(self, key: str, default=None):
        return self.config.get(key, default)

    def set(self, key: str, value):
        self.config[key] = value
        self.save()


# ============================================================================
# 开机自启动管理
# ============================================================================
class AutoStartManager:
    """Windows开机自启动管理"""

    REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"

    @staticmethod
    def is_enabled() -> bool:
        """检查是否已启用开机自启"""
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
        """启用开机自启"""
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
            logging.info("已启用开机自启动")
            return True
        except WindowsError as e:
            logging.error(f"启用开机自启失败: {e}")
            return False

    @staticmethod
    def disable():
        """禁用开机自启"""
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                AutoStartManager.REG_PATH,
                0,
                winreg.KEY_SET_VALUE,
            )
            try:
                winreg.DeleteValue(key, APP_NAME)
                logging.info("已禁用开机自启动")
            except WindowsError:
                pass
            winreg.CloseKey(key)
            return True
        except WindowsError as e:
            logging.error(f"禁用开机自启失败: {e}")
            return False


# ============================================================================
# 解压处理器
# ============================================================================
class ArchiveExtractor:
    """多格式压缩包解压器"""

    @staticmethod
    def get_archive_type(filepath: str) -> Optional[str]:
        """识别压缩包类型"""
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
    def extract(
        filepath: str, dest_dir: Optional[str] = None, to_subfolder: bool = True
    ) -> tuple[bool, str]:
        """
        解压压缩包

        Args:
            filepath: 压缩包路径
            dest_dir: 目标目录，默认为压缩包所在目录
            to_subfolder: 是否解压到以压缩包名称命名的子文件夹

        Returns:
            (成功与否, 消息)
        """
        if not os.path.exists(filepath):
            return False, f"文件不存在: {filepath}"

        archive_type = ArchiveExtractor.get_archive_type(filepath)
        if not archive_type:
            return False, f"不支持的格式: {filepath}"

        # 确定目标目录
        if dest_dir is None:
            dest_dir = os.path.dirname(filepath)

        if to_subfolder:
            # 获取不含扩展名的文件名作为子文件夹名
            basename = os.path.basename(filepath)
            # 移除所有压缩扩展名
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
                    basename = basename[: -len(ext)]
                    break
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
                mode = "r"
                if archive_type == "tar.gz":
                    mode = "r:gz"
                elif archive_type == "tar.bz2":
                    mode = "r:bz2"
                elif archive_type == "tar.xz":
                    mode = "r:xz"
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

            logging.info(f"解压成功: {filepath} -> {dest_dir}")
            return True, f"解压成功: {dest_dir}"

        except Exception as e:
            logging.error(f"解压失败 {filepath}: {e}")
            return False, f"解压失败: {str(e)}"


# ============================================================================
# 文件监控
# ============================================================================
class ArchiveWatcher:
    """压缩包文件监控器"""

    def __init__(self, config: ConfigManager, on_status_change=None):
        self.config = config
        self.observer = Observer()
        self.handlers: Dict[str, ArchiveEventHandler] = {}
        self.running = False
        self.on_status_change = on_status_change
        # 记录已处理的压缩包（避免重复删除）
        self.processed_archives: Set[str] = set()
        self.lock = threading.Lock()

    def start(self):
        """启动监控"""
        if self.running:
            return

        watch_folders = self.config.get("watch_folders", [])
        if not watch_folders:
            logging.warning("没有配置监控文件夹")
            return

        for folder in watch_folders:
            if os.path.exists(folder):
                handler = ArchiveEventHandler(self, folder)
                self.handlers[folder] = handler
                self.observer.schedule(handler, folder, recursive=False)
                logging.info(f"开始监控: {folder}")

        self.observer.start()
        self.running = True
        if self.on_status_change:
            self.on_status_change(True)

    def stop(self):
        """停止监控"""
        if not self.running:
            return

        self.observer.stop()
        self.observer.join()
        self.running = False
        self.handlers.clear()

        # 重新创建observer以便下次启动
        self.observer = Observer()

        if self.on_status_change:
            self.on_status_change(False)
        logging.info("已停止监控")

    def is_archive(self, filepath: str) -> bool:
        """判断是否为支持的压缩包"""
        lower_path = filepath.lower()
        supported = self.config.get("supported_formats", ARCHIVE_EXTENSIONS)
        return any(lower_path.endswith(ext) for ext in supported)

    def mark_for_deletion(self, filepath: str):
        """标记压缩包待删除（解压完成后）"""
        with self.lock:
            if filepath not in self.processed_archives:
                self.processed_archives.add(filepath)
                delay = self.config.get("delete_delay_seconds", 5)
                threading.Thread(
                    target=self._delayed_delete, args=(filepath, delay), daemon=True
                ).start()

    def _delayed_delete(self, filepath: str, delay: int):
        """延迟删除压缩包"""
        time.sleep(delay)
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
                logging.info(f"已删除压缩包: {filepath}")
        except Exception as e:
            logging.error(f"删除失败 {filepath}: {e}")
        finally:
            with self.lock:
                self.processed_archives.discard(filepath)


class ArchiveEventHandler(FileSystemEventHandler):
    """文件系统事件处理器"""

    def __init__(self, watcher: ArchiveWatcher, watch_folder: str):
        super().__init__()
        self.watcher = watcher
        self.watch_folder = watch_folder
        # 记录压缩包的初始大小，用于检测解压完成
        self.archive_sizes: Dict[str, int] = {}
        self.check_interval = 2  # 检查间隔秒数

    def on_created(self, event):
        """文件创建事件 - 可能是新下载的压缩包"""
        if event.is_directory:
            return

        filepath = event.src_path
        if self.watcher.is_archive(filepath):
            logging.info(f"检测到新压缩包: {filepath}")
            # 记录初始大小
            try:
                self.archive_sizes[filepath] = os.path.getsize(filepath)
            except:
                pass

    def on_modified(self, event):
        """文件修改事件 - 检测压缩包是否被访问（可能正在解压）"""
        if event.is_directory:
            return

        filepath = event.src_path
        if self.watcher.is_archive(filepath):
            # 检查文件大小是否稳定（用于判断下载是否完成）
            try:
                current_size = os.path.getsize(filepath)
                if filepath in self.archive_sizes:
                    if current_size == self.archive_sizes[filepath]:
                        # 大小稳定，可能是解压操作访问了文件
                        pass
                self.archive_sizes[filepath] = current_size
            except:
                pass

    def on_deleted(self, event):
        """文件删除事件"""
        if event.is_directory:
            # 如果删除的是目录，检查是否有同名压缩包
            dir_name = os.path.basename(event.src_path)
            for ext in ARCHIVE_EXTENSIONS:
                archive_path = event.src_path + ext
                if os.path.exists(archive_path):
                    # 可能是解压创建的目录，标记压缩包待删除
                    pass

        filepath = event.src_path
        # 清理记录
        self.archive_sizes.pop(filepath, None)


# ============================================================================
# 设置界面
# ============================================================================
class SettingsWindow:
    """设置窗口"""

    def __init__(self, config: ConfigManager, watcher: ArchiveWatcher):
        self.config = config
        self.watcher = watcher
        self.window = None

    def show(self):
        """显示设置窗口"""
        if self.window is not None:
            try:
                self.window.lift()
                self.window.focus_force()
                return
            except:
                pass

        self.window = tk.Tk()
        self.window.title(f"{APP_TITLE} - 设置")
        self.window.geometry("600x500")
        self.window.resizable(True, True)

        # 设置图标
        try:
            self.window.iconbitmap(self._get_icon_path())
        except:
            pass

        self._create_widgets()
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)
        self.window.mainloop()

    def _get_icon_path(self) -> str:
        """获取图标路径"""
        if getattr(sys, "frozen", False):
            return os.path.join(sys._MEIPASS, "icon.ico")
        return "icon.ico"

    def _create_widgets(self):
        """创建界面组件"""
        notebook = ttk.Notebook(self.window)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # ========== 监控文件夹标签页 ==========
        folder_frame = ttk.Frame(notebook, padding=10)
        notebook.add(folder_frame, text="监控文件夹")

        # 文件夹列表
        list_frame = ttk.Frame(folder_frame)
        list_frame.pack(fill=tk.BOTH, expand=True)

        self.folder_listbox = tk.Listbox(list_frame, height=10)
        self.folder_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(
            list_frame, orient=tk.VERTICAL, command=self.folder_listbox.yview
        )
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.folder_listbox.config(yscrollcommand=scrollbar.set)

        # 加载已保存的文件夹
        for folder in self.config.get("watch_folders", []):
            self.folder_listbox.insert(tk.END, folder)

        # 按钮
        btn_frame = ttk.Frame(folder_frame)
        btn_frame.pack(fill=tk.X, pady=10)

        ttk.Button(btn_frame, text="添加文件夹", command=self._add_folder).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(btn_frame, text="移除选中", command=self._remove_folder).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(btn_frame, text="添加下载文件夹", command=self._add_downloads).pack(
            side=tk.LEFT, padx=5
        )

        # ========== 常规设置标签页 ==========
        general_frame = ttk.Frame(notebook, padding=10)
        notebook.add(general_frame, text="常规设置")

        # 开机自启
        self.auto_start_var = tk.BooleanVar(value=AutoStartManager.is_enabled())
        ttk.Checkbutton(
            general_frame,
            text="开机自动启动",
            variable=self.auto_start_var,
            command=self._toggle_auto_start,
        ).pack(anchor=tk.W, pady=5)

        # 自动监控
        self.auto_monitor_var = tk.BooleanVar(
            value=self.config.get("auto_monitor", True)
        )
        ttk.Checkbutton(
            general_frame, text="启动时自动开始监控", variable=self.auto_monitor_var
        ).pack(anchor=tk.W, pady=5)

        # 解压后删除
        self.delete_after_var = tk.BooleanVar(
            value=self.config.get("delete_after_extract", True)
        )
        ttk.Checkbutton(
            general_frame, text="解压后自动删除压缩包", variable=self.delete_after_var
        ).pack(anchor=tk.W, pady=5)

        # 解压到子文件夹
        self.subfolder_var = tk.BooleanVar(
            value=self.config.get("extract_to_subfolder", True)
        )
        ttk.Checkbutton(
            general_frame, text="解压到同名子文件夹", variable=self.subfolder_var
        ).pack(anchor=tk.W, pady=5)

        # 删除延迟
        delay_frame = ttk.Frame(general_frame)
        delay_frame.pack(anchor=tk.W, pady=5)
        ttk.Label(delay_frame, text="删除延迟(秒):").pack(side=tk.LEFT)
        self.delay_var = tk.StringVar(
            value=str(self.config.get("delete_delay_seconds", 5))
        )
        ttk.Spinbox(
            delay_frame, from_=1, to=60, width=5, textvariable=self.delay_var
        ).pack(side=tk.LEFT, padx=5)

        # ========== 手动解压标签页 ==========
        extract_frame = ttk.Frame(notebook, padding=10)
        notebook.add(extract_frame, text="手动解压")

        ttk.Label(
            extract_frame, text="选择压缩包进行解压，解压后可选择删除原文件"
        ).pack(pady=10)

        ttk.Button(
            extract_frame, text="选择压缩包解压", command=self._manual_extract
        ).pack(pady=10)

        # 解压日志
        ttk.Label(extract_frame, text="操作日志:").pack(anchor=tk.W)
        self.log_text = tk.Text(extract_frame, height=10, state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True, pady=5)

        # ========== 底部保存按钮 ==========
        bottom_frame = ttk.Frame(self.window)
        bottom_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Button(bottom_frame, text="保存设置", command=self._save_settings).pack(
            side=tk.RIGHT, padx=5
        )
        ttk.Button(bottom_frame, text="关闭", command=self._on_close).pack(
            side=tk.RIGHT, padx=5
        )

    def _add_folder(self):
        """添加监控文件夹"""
        folder = filedialog.askdirectory(title="选择要监控的文件夹")
        if folder:
            if folder not in self.folder_listbox.get(0, tk.END):
                self.folder_listbox.insert(tk.END, folder)

    def _remove_folder(self):
        """移除选中的文件夹"""
        selection = self.folder_listbox.curselection()
        if selection:
            self.folder_listbox.delete(selection[0])

    def _add_downloads(self):
        """添加系统下载文件夹"""
        downloads = str(Path.home() / "Downloads")
        if downloads not in self.folder_listbox.get(0, tk.END):
            self.folder_listbox.insert(tk.END, downloads)

    def _toggle_auto_start(self):
        """切换开机自启"""
        if self.auto_start_var.get():
            AutoStartManager.enable()
        else:
            AutoStartManager.disable()

    def _manual_extract(self):
        """手动选择解压"""
        filetypes = [
            (
                "所有压缩包",
                "*.zip *.rar *.7z *.tar *.tar.gz *.tgz *.tar.bz2 *.tar.xz *.gz *.bz2 *.xz",
            ),
            ("ZIP文件", "*.zip"),
            ("RAR文件", "*.rar"),
            ("7Z文件", "*.7z"),
            ("TAR文件", "*.tar *.tar.gz *.tgz *.tar.bz2 *.tar.xz"),
            ("所有文件", "*.*"),
        ]

        filepath = filedialog.askopenfilename(
            title="选择要解压的文件", filetypes=filetypes
        )

        if filepath:
            self._log(f"开始解压: {filepath}")
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
        """添加日志"""
        self.log_text.config(state=tk.NORMAL)
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _save_settings(self):
        """保存设置"""
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
        """关闭窗口"""
        if self.window:
            self.window.destroy()
            self.window = None


# ============================================================================
# 系统托盘
# ============================================================================
class TrayApp:
    """系统托盘应用"""

    def __init__(self):
        self.config = ConfigManager()
        self.watcher = ArchiveWatcher(self.config, self._on_watcher_status_change)
        self.settings_window = SettingsWindow(self.config, self.watcher)
        self.icon = None
        self.monitoring = False

    def _create_icon_image(self, color="green") -> Image.Image:
        """创建托盘图标"""
        size = 64
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)

        # 绘制压缩包图标样式
        if color == "green":
            fill_color = (76, 175, 80, 255)  # 绿色 - 监控中
        else:
            fill_color = (158, 158, 158, 255)  # 灰色 - 未监控

        # 文件图标形状
        draw.rectangle([8, 4, 48, 60], fill=fill_color, outline=(255, 255, 255, 255))
        # 折角
        draw.polygon([(48, 4), (56, 12), (48, 12)], fill=(255, 255, 255, 200))
        # ZIP文字
        draw.rectangle([12, 24, 44, 44], fill=(255, 255, 255, 200))

        return image

    def _create_menu(self) -> pystray.Menu:
        """创建托盘菜单"""
        return pystray.Menu(
            pystray.MenuItem(
                lambda item: "● 监控中" if self.monitoring else "○ 未监控",
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
        """切换监控状态"""
        if self.monitoring:
            self.watcher.stop()
        else:
            self.watcher.start()

    def _on_watcher_status_change(self, is_running: bool):
        """监控状态变化回调"""
        self.monitoring = is_running
        if self.icon:
            self.icon.icon = self._create_icon_image("green" if is_running else "gray")
            self.icon.update_menu()

    def _show_settings(self, icon=None, item=None):
        """显示设置窗口"""
        threading.Thread(target=self.settings_window.show, daemon=True).start()

    def _manual_extract(self, icon=None, item=None):
        """手动解压（通过托盘菜单）"""

        def do_extract():
            root = tk.Tk()
            root.withdraw()

            filetypes = [
                (
                    "所有压缩包",
                    "*.zip *.rar *.7z *.tar *.tar.gz *.tgz *.tar.bz2 *.tar.xz",
                ),
                ("所有文件", "*.*"),
            ]

            filepath = filedialog.askopenfilename(
                title="选择要解压的文件", filetypes=filetypes
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
        """切换开机自启"""
        if AutoStartManager.is_enabled():
            AutoStartManager.disable()
        else:
            AutoStartManager.enable()

    def _quit(self, icon=None, item=None):
        """退出程序"""
        self.watcher.stop()
        if self.icon:
            self.icon.stop()

    def run(self):
        """运行应用"""
        logger = setup_logging()
        logger.info(f"{APP_TITLE} 启动")

        # 自动开始监控
        if self.config.get("auto_monitor", True):
            self.watcher.start()

        # 创建托盘图标
        self.icon = pystray.Icon(
            APP_NAME,
            self._create_icon_image("green" if self.monitoring else "gray"),
            APP_TITLE,
            self._create_menu(),
        )

        self.icon.run()


# ============================================================================
# 主入口
# ============================================================================
def main():
    """主函数"""
    # 确保只有一个实例运行
    import socket

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 59173))
    except socket.error:
        print("程序已在运行中")
        sys.exit(0)

    app = TrayApp()
    app.run()


if __name__ == "__main__":
    main()
