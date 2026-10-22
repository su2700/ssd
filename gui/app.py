import os
import logging
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Dict, List, Optional, Any

from core.disk_detector import (
    is_admin,
    is_system_disk,
    get_wsl_distros,
    get_physical_disks,
    get_disk_partitions,
    get_free_drive_letters
)
from core.disk_formatter import (
    format_physical_disk_full,
    format_physical_partition,
    sanitize_label
)
from core.wsl_mounter import WslMounter, load_saved_mounts
from core.windows_compat import get_windows_support, get_wsl_capabilities, mount_support_error
from core.diagnostics import explain_error, wsl_environment_error, log_location
from core.explorer_helper import (
    open_in_explorer,
    map_drive_letter,
    unmap_drive_letter,
    create_desktop_shortcut
)

logger = logging.getLogger("ext4_mounter.gui")

class Ext4MounterApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Ext4 一键挂载桌面小工具 - Windows")
        self.root.geometry("820x680")
        self.root.minsize(740, 600)

        # Set default font & style
        self.style = ttk.Style()
        try:
            self.style.theme_use("vista")
        except Exception:
            pass

        self._init_theme_colors()
        self.mounter = WslMounter(discover=False)
        self._ui_queue = queue.Queue()
        self._closed = threading.Event()
        self._wsl_ready = False
        self._physical_ready = False
        self._format_ready = False

        # State tracking
        self.disks_cache: List[Dict[str, Any]] = []
        self.current_partitions: List[Dict[str, Any]] = []
        self.is_busy = False

        self._build_ui()
        self.root.report_callback_exception = self._report_callback_exception
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.mount_phys_btn.configure(state=tk.DISABLED)
        self.mount_img_btn.configure(state=tk.DISABLED)
        self.format_phys_btn.configure(state=tk.DISABLED)
        self._guard_timer = None
        self._poll_timer = self.root.after(50, self._drain_ui_queue)
        self._startup_timer = self.root.after_idle(self._initialize)

    def _initialize(self):
        self._startup_timer = None
        self._refresh_system_status()
        self._async_load_disks()
        self._refresh_active_mounts_table()
        self._start_permission_guard()

    def _post_ui(self, callback):
        # Workers must never call Tk, including Tk.after().
        if not self._closed.is_set():
            self._ui_queue.put(callback)

    def _drain_ui_queue(self):
        if self._closed.is_set():
            return
        for _ in range(100):
            try:
                callback = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                callback()
            except Exception:
                self._report_callback_exception(*sys.exc_info())
            if self._closed.is_set():
                return
        self._poll_timer = self.root.after(50, self._drain_ui_queue)

    def _start_worker(self, target, action=False):
        def guarded():
            try:
                target()
            except Exception as error:
                logger.exception("Background operation failed")
                # Bind now: Python clears exception variables after except.
                self._post_ui(lambda error=error: self._show_error(error, reset_action=action))
        threading.Thread(target=guarded, daemon=True).start()

    def _report_callback_exception(self, exc_type, error, traceback):
        logger.error("UI callback failed", exc_info=(exc_type, error, traceback))
        self._show_error(error)

    def _show_error(self, error, reset_action=True):
        if reset_action:
            self._restore_action_controls()
        self.log(str(error), level="ERROR")
        self._notify_failure("操作失败", error)

    def _notify_failure(self, title, error, warning=False):
        detail = explain_error(error, log_path=log_location())
        self.log(detail, level="WARN" if warning else "ERROR")
        dialog = messagebox.showwarning if warning else messagebox.showerror
        dialog(title, detail, parent=self.root)

    def _restore_action_controls(self):
        self.is_busy = False
        # Restore action controls after a failed worker, so retry remains possible.
        for name, text in (
            ("mount_phys_btn", "🚀 一键挂载物理 SSD 分区"),
            ("mount_img_btn", "🚀 一键挂载 ext4 镜像文件"),
            ("unmount_phys_btn", "⏏️ 卸载此物理磁盘"),
            ("unmount_img_btn", "⏏️ 卸载此镜像"),
            ("format_phys_btn", "🧹 格式化 SSD (ext4)"),
        ):
            enabled = {"mount_phys_btn": self._physical_ready,
                       "mount_img_btn": self._wsl_ready,
                       "format_phys_btn": self._format_ready}.get(name, True)
            getattr(self, name).configure(text=text, state=tk.NORMAL if enabled else tk.DISABLED)

    def _close(self):
        self._closed.set()
        for timer in (self._startup_timer, self._poll_timer, self._guard_timer):
            if timer is not None:
                self.root.after_cancel(timer)
        self.root.destroy()

    def _init_theme_colors(self):
        self.bg_color = "#f4f6f9"
        self.card_bg = "#ffffff"
        self.accent_color = "#2563eb"  # Modern royal blue
        self.success_color = "#16a34a"
        self.danger_color = "#dc2626"
        self.text_primary = "#1e293b"
        self.text_muted = "#64748b"
        self.border_color = "#e2e8f0"
        self.root.configure(bg=self.bg_color)

    def _build_ui(self):
        # Main container with padding
        main_frame = tk.Frame(self.root, bg=self.bg_color, padx=16, pady=12)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 1. Header Bar
        header_frame = tk.Frame(main_frame, bg=self.bg_color)
        header_frame.pack(fill=tk.X, pady=(0, 10))

        title_label = tk.Label(
            header_frame,
            text="💽 Ext4 一键挂载小工具",
            font=("Segoe UI", 16, "bold"),
            fg=self.text_primary,
            bg=self.bg_color
        )
        title_label.pack(side=tk.LEFT)

        # Admin & WSL status badges in header
        self.badge_frame = tk.Frame(header_frame, bg=self.bg_color)
        self.badge_frame.pack(side=tk.RIGHT)

        self.wsl_badge = tk.Label(
            self.badge_frame,
            text="WSL: 检测中...",
            font=("Segoe UI", 9),
            fg="#0369a1",
            bg="#e0f2fe",
            padx=8,
            pady=3,
            relief=tk.FLAT
        )
        self.wsl_badge.pack(side=tk.LEFT, padx=4)

        self.admin_badge = tk.Label(
            self.badge_frame,
            text="权限: 普通用户",
            font=("Segoe UI", 9),
            fg="#6b7280",
            bg="#f3f4f6",
            padx=8,
            pady=3,
            relief=tk.FLAT
        )
        self.admin_badge.pack(side=tk.LEFT, padx=4)

        self.pin_btn = tk.Button(
            self.badge_frame,
            text="📌 桌面快捷方式",
            font=("Segoe UI", 9),
            bg="#ffffff",
            fg=self.text_primary,
            relief=tk.SOLID,
            bd=1,
            padx=6,
            pady=2,
            cursor="hand2",
            command=self._create_desktop_shortcut_ui
        )
        self.pin_btn.pack(side=tk.LEFT, padx=4)

        # 2. Main Tabbed Notebook
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # Tab 1: Physical SSD Tab
        self.tab_physical = tk.Frame(self.notebook, bg=self.card_bg, padx=16, pady=12)
        self.notebook.add(self.tab_physical, text="  💾 物理 SSD / 磁盘分区挂载  ")
        self._build_physical_tab(self.tab_physical)

        # Tab 2: Image File Tab
        self.tab_image = tk.Frame(self.notebook, bg=self.card_bg, padx=16, pady=12)
        self.notebook.add(self.tab_image, text="  📁 ext4 镜像文件挂载 (.img/.ext4/.vhdx)  ")
        self._build_image_tab(self.tab_image)

        # 3. Active Mounts Section
        mounts_frame = tk.LabelFrame(
            main_frame,
            text="  🟢 已挂载设备与镜像 (Active Mounts)  ",
            font=("Segoe UI", 10, "bold"),
            fg=self.text_primary,
            bg=self.card_bg,
            padx=10,
            pady=8
        )
        mounts_frame.pack(fill=tk.X, pady=(0, 8))

        # Mounts Treeview
        tree_columns = ("name", "type", "target", "unc_path", "mode")
        self.mounts_tree = ttk.Treeview(
            mounts_frame,
            columns=tree_columns,
            show="headings",
            height=3,
            selectmode="browse"
        )
        self.mounts_tree.heading("name", text="挂载名称")
        self.mounts_tree.heading("type", text="类型")
        self.mounts_tree.heading("target", text="源目标")
        self.mounts_tree.heading("unc_path", text="Windows 路径")
        self.mounts_tree.heading("mode", text="权限模式")

        self.mounts_tree.column("name", width=110, anchor=tk.W)
        self.mounts_tree.column("type", width=70, anchor=tk.CENTER)
        self.mounts_tree.column("target", width=220, anchor=tk.W)
        self.mounts_tree.column("unc_path", width=240, anchor=tk.W)
        self.mounts_tree.column("mode", width=80, anchor=tk.CENTER)

        mounts_scroll = ttk.Scrollbar(mounts_frame, orient=tk.VERTICAL, command=self.mounts_tree.yview)
        self.mounts_tree.configure(yscrollcommand=mounts_scroll.set)

        self.mounts_tree.pack(side=tk.LEFT, fill=tk.X, expand=True)
        mounts_scroll.pack(side=tk.LEFT, fill=tk.Y)

        # Action buttons next to mounts
        mounts_action_frame = tk.Frame(mounts_frame, bg=self.card_bg, padx=8)
        mounts_action_frame.pack(side=tk.RIGHT, fill=tk.Y)

        self.open_selected_btn = tk.Button(
            mounts_action_frame,
            text="📂 打开选中",
            font=("Segoe UI", 9, "bold"),
            bg="#2563eb",
            fg="#ffffff",
            relief=tk.FLAT,
            padx=10,
            pady=4,
            cursor="hand2",
            command=self._open_selected_mount
        )
        self.open_selected_btn.pack(fill=tk.X, pady=2)

        self.fix_rosbag_btn = tk.Button(
            mounts_action_frame,
            text="🛠️ 修复 mcap 权限",
            font=("Segoe UI", 9, "bold"),
            bg="#fef9c3",
            fg="#854d0e",
            relief=tk.SOLID,
            bd=1,
            padx=10,
            pady=3,
            cursor="hand2",
            command=self._fix_selected_rosbag_permissions
        )
        self.fix_rosbag_btn.pack(fill=tk.X, pady=2)

        self.fix_perm_selected_btn = tk.Button(
            mounts_action_frame,
            text="🛡️ 赋予 777 权限",
            font=("Segoe UI", 9),
            bg="#fef3c7",
            fg="#b45309",
            relief=tk.SOLID,
            bd=1,
            padx=10,
            pady=3,
            cursor="hand2",
            command=self._fix_selected_mount_permissions
        )
        self.fix_perm_selected_btn.pack(fill=tk.X, pady=2)

        self.unmount_selected_btn = tk.Button(
            mounts_action_frame,
            text="⏏️ 卸载选中",
            font=("Segoe UI", 9),
            bg="#f1f5f9",
            fg=self.danger_color,
            relief=tk.SOLID,
            bd=1,
            padx=10,
            pady=3,
            cursor="hand2",
            command=self._unmount_selected_mount
        )
        self.unmount_selected_btn.pack(fill=tk.X, pady=2)

        self.unmount_all_btn = tk.Button(
            mounts_action_frame,
            text="⚠️ 卸载全部",
            font=("Segoe UI", 9),
            bg="#fee2e2",
            fg="#b91c1c",
            relief=tk.FLAT,
            padx=10,
            pady=3,
            cursor="hand2",
            command=self._unmount_all
        )
        self.unmount_all_btn.pack(fill=tk.X, pady=2)

        # 4. Activity Log Area (Collapsible)
        log_frame = tk.LabelFrame(
            main_frame,
            text="  📋 实时操作日志  ",
            font=("Segoe UI", 9),
            fg=self.text_muted,
            bg=self.card_bg,
            padx=6,
            pady=4
        )
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = tk.Text(
            log_frame,
            height=5,
            font=("Consolas", 9),
            bg="#1e293b",
            fg="#f8fafc",
            relief=tk.FLAT,
            wrap=tk.WORD
        )
        log_scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)

        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def _build_physical_tab(self, parent: tk.Frame):
        # Disk selection row
        row1 = tk.Frame(parent, bg=self.card_bg)
        row1.pack(fill=tk.X, pady=6)

        lbl_disk = tk.Label(row1, text="选择物理磁盘:", font=("Segoe UI", 9, "bold"), bg=self.card_bg, width=12, anchor=tk.W)
        lbl_disk.pack(side=tk.LEFT)

        self.disk_combo = ttk.Combobox(row1, state="readonly", font=("Segoe UI", 9))
        self.disk_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        self.disk_combo.bind("<<ComboboxSelected>>", self._on_disk_selected)

        self.refresh_disks_btn = tk.Button(
            row1,
            text="🔄 刷新磁盘",
            font=("Segoe UI", 9),
            bg="#ffffff",
            relief=tk.SOLID,
            bd=1,
            padx=6,
            cursor="hand2",
            command=self._refresh_discovery
        )
        self.refresh_disks_btn.pack(side=tk.LEFT)

        # Partition selection row
        row2 = tk.Frame(parent, bg=self.card_bg)
        row2.pack(fill=tk.X, pady=6)

        lbl_part = tk.Label(row2, text="选择磁盘分区:", font=("Segoe UI", 9, "bold"), bg=self.card_bg, width=12, anchor=tk.W)
        lbl_part.pack(side=tk.LEFT)

        self.part_combo = ttk.Combobox(row2, state="readonly", font=("Segoe UI", 9))
        self.part_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        self.part_combo.bind("<<ComboboxSelected>>", self._on_partition_selected)

        # Partition Info Card
        self.part_info_card = tk.Label(
            parent,
            text="正在扫描磁盘与分区信息...",
            font=("Segoe UI", 9),
            fg="#0369a1",
            bg="#f0f9ff",
            relief=tk.FLAT,
            padx=12,
            pady=8,
            justify=tk.LEFT,
            anchor=tk.W
        )
        self.part_info_card.pack(fill=tk.X, pady=6)

        # Mount Options
        opt_frame = tk.Frame(parent, bg=self.card_bg)
        opt_frame.pack(fill=tk.X, pady=(6, 2))

        lbl_name = tk.Label(opt_frame, text="自定义挂载名:", font=("Segoe UI", 9), bg=self.card_bg)
        lbl_name.pack(side=tk.LEFT)

        self.phys_mount_name_var = tk.StringVar(value="ssd_ext4")
        self.phys_mount_name_entry = ttk.Entry(opt_frame, textvariable=self.phys_mount_name_var, width=16)
        self.phys_mount_name_entry.pack(side=tk.LEFT, padx=6)

        self.phys_ro_var = tk.BooleanVar(value=True)
        self.phys_ro_cb = ttk.Checkbutton(
            opt_frame,
            text="安全只读模式 (保护 ext4 数据)",
            variable=self.phys_ro_var
        )
        self.phys_ro_cb.pack(side=tk.LEFT, padx=12)

        self.phys_auto_open_var = tk.BooleanVar(value=True)
        self.phys_auto_open_cb = ttk.Checkbutton(
            opt_frame,
            text="挂载后自动打开资源管理器",
            variable=self.phys_auto_open_var
        )
        self.phys_auto_open_cb.pack(side=tk.LEFT)

        # Permission & Advance Options Row
        opt_frame2 = tk.Frame(parent, bg=self.card_bg)
        opt_frame2.pack(fill=tk.X, pady=(2, 6))

        self.phys_auto_perm_var = tk.BooleanVar(value=True)
        self.phys_auto_perm_cb = ttk.Checkbutton(
            opt_frame2,
            text="⚡ 自动配置 777/可见权限 (解决 ROS2/mcap 0字节与权限问题，Default ACL 继承)",
            variable=self.phys_auto_perm_var
        )
        self.phys_auto_perm_cb.pack(side=tk.LEFT)

        # Buttons row
        btn_frame = tk.Frame(parent, bg=self.card_bg)
        btn_frame.pack(fill=tk.X, pady=(12, 4))

        self.mount_phys_btn = tk.Button(
            btn_frame,
            text="🚀 一键挂载物理 SSD 分区",
            font=("Segoe UI", 10, "bold"),
            bg="#16a34a",
            fg="#ffffff",
            relief=tk.FLAT,
            padx=18,
            pady=8,
            cursor="hand2",
            command=self._mount_physical_disk_action
        )
        self.mount_phys_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.open_phys_btn = tk.Button(
            btn_frame,
            text="📂 在资源管理器中打开",
            font=("Segoe UI", 10),
            bg="#2563eb",
            fg="#ffffff",
            relief=tk.FLAT,
            padx=14,
            pady=8,
            cursor="hand2",
            command=lambda: self._open_mount_by_name(self.phys_mount_name_var.get().strip())
        )
        self.open_phys_btn.pack(side=tk.LEFT, padx=6)

        self.fix_ros_phys_btn = tk.Button(
            btn_frame,
            text="🛠️ 修复 mcap 权限",
            font=("Segoe UI", 10, "bold"),
            bg="#fef9c3",
            fg="#854d0e",
            relief=tk.SOLID,
            bd=1,
            padx=12,
            pady=8,
            cursor="hand2",
            command=lambda: self._fix_rosbag_permissions_action(self.phys_mount_name_var.get().strip())
        )
        self.fix_ros_phys_btn.pack(side=tk.LEFT, padx=6)

        self.fix_perm_phys_btn = tk.Button(
            btn_frame,
            text="🛡️ 赋予 777 权限",
            font=("Segoe UI", 10),
            bg="#f59e0b",
            fg="#ffffff",
            relief=tk.FLAT,
            padx=12,
            pady=8,
            cursor="hand2",
            command=lambda: self._fix_permissions_action(self.phys_mount_name_var.get().strip())
        )
        self.fix_perm_phys_btn.pack(side=tk.LEFT, padx=6)

        self.unmount_phys_btn = tk.Button(
            btn_frame,
            text="⏏️ 卸载此物理磁盘",
            font=("Segoe UI", 10),
            bg="#fee2e2",
            fg="#b91c1c",
            relief=tk.FLAT,
            padx=14,
            pady=8,
            cursor="hand2",
            command=self._unmount_physical_disk_action
        )
        self.unmount_phys_btn.pack(side=tk.LEFT, padx=6)

        self.format_phys_btn = tk.Button(
            btn_frame,
            text="🧹 格式化 SSD (ext4)",
            font=("Segoe UI", 10, "bold"),
            bg="#dc2626",
            fg="#ffffff",
            relief=tk.FLAT,
            padx=14,
            pady=8,
            cursor="hand2",
            command=self._format_ssd_dialog
        )
        self.format_phys_btn.pack(side=tk.LEFT, padx=6)

    def _build_image_tab(self, parent: tk.Frame):
        # File selector row
        row1 = tk.Frame(parent, bg=self.card_bg)
        row1.pack(fill=tk.X, pady=6)

        lbl_file = tk.Label(row1, text="ext4 镜像路径:", font=("Segoe UI", 9, "bold"), bg=self.card_bg, width=12, anchor=tk.W)
        lbl_file.pack(side=tk.LEFT)

        self.img_path_var = tk.StringVar()
        self.img_path_entry = ttk.Entry(row1, textvariable=self.img_path_var, font=("Segoe UI", 9))
        self.img_path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        self.img_path_entry.bind("<KeyRelease>", self._on_img_path_changed)

        self.browse_btn = tk.Button(
            row1,
            text="📂 浏览文件...",
            font=("Segoe UI", 9),
            bg="#ffffff",
            relief=tk.SOLID,
            bd=1,
            padx=8,
            cursor="hand2",
            command=self._browse_image_file
        )
        self.browse_btn.pack(side=tk.LEFT)

        # Image Info Card
        self.img_info_card = tk.Label(
            parent,
            text="支持 .img/.ext4/.raw（无需 Windows 管理员权限）；.vhd/.vhdx 需要新版 WSL，并会请求 UAC 授权。",
            font=("Segoe UI", 9),
            fg="#0369a1",
            bg="#f0f9ff",
            relief=tk.FLAT,
            padx=12,
            pady=8,
            justify=tk.LEFT,
            anchor=tk.W
        )
        self.img_info_card.pack(fill=tk.X, pady=6)

        # Options
        opt_frame = tk.Frame(parent, bg=self.card_bg)
        opt_frame.pack(fill=tk.X, pady=(6, 2))

        lbl_name = tk.Label(opt_frame, text="自定义挂载名:", font=("Segoe UI", 9), bg=self.card_bg)
        lbl_name.pack(side=tk.LEFT)

        self.img_mount_name_var = tk.StringVar(value="my_ext4_img")
        self.img_mount_name_entry = ttk.Entry(opt_frame, textvariable=self.img_mount_name_var, width=16)
        self.img_mount_name_entry.pack(side=tk.LEFT, padx=6)

        self.img_ro_var = tk.BooleanVar(value=True)
        self.img_ro_cb = ttk.Checkbutton(
            opt_frame,
            text="安全只读模式 (Read-Only)",
            variable=self.img_ro_var
        )
        self.img_ro_cb.pack(side=tk.LEFT, padx=12)

        self.img_auto_open_var = tk.BooleanVar(value=True)
        self.img_auto_open_cb = ttk.Checkbutton(
            opt_frame,
            text="挂载后自动打开资源管理器",
            variable=self.img_auto_open_var
        )
        self.img_auto_open_cb.pack(side=tk.LEFT)

        # Permission & Advance Options Row
        opt_frame2 = tk.Frame(parent, bg=self.card_bg)
        opt_frame2.pack(fill=tk.X, pady=(2, 6))

        self.img_auto_perm_var = tk.BooleanVar(value=True)
        self.img_auto_perm_cb = ttk.Checkbutton(
            opt_frame2,
            text="⚡ 自动配置 777/可见权限 (解决 ROS2/mcap 0字节与权限问题，Default ACL 继承)",
            variable=self.img_auto_perm_var
        )
        self.img_auto_perm_cb.pack(side=tk.LEFT)

        # Buttons row
        btn_frame = tk.Frame(parent, bg=self.card_bg)
        btn_frame.pack(fill=tk.X, pady=(12, 4))

        self.mount_img_btn = tk.Button(
            btn_frame,
            text="🚀 一键挂载 ext4 镜像文件",
            font=("Segoe UI", 10, "bold"),
            bg="#16a34a",
            fg="#ffffff",
            relief=tk.FLAT,
            padx=18,
            pady=8,
            cursor="hand2",
            command=self._mount_image_file_action
        )
        self.mount_img_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.open_img_btn = tk.Button(
            btn_frame,
            text="📂 在资源管理器中打开",
            font=("Segoe UI", 10),
            bg="#2563eb",
            fg="#ffffff",
            relief=tk.FLAT,
            padx=14,
            pady=8,
            cursor="hand2",
            command=lambda: self._open_mount_by_name(self.img_mount_name_var.get().strip())
        )
        self.open_img_btn.pack(side=tk.LEFT, padx=6)

        self.fix_ros_img_btn = tk.Button(
            btn_frame,
            text="🛠️ 修复 mcap 权限",
            font=("Segoe UI", 10, "bold"),
            bg="#fef9c3",
            fg="#854d0e",
            relief=tk.SOLID,
            bd=1,
            padx=12,
            pady=8,
            cursor="hand2",
            command=lambda: self._fix_rosbag_permissions_action(self.img_mount_name_var.get().strip())
        )
        self.fix_ros_img_btn.pack(side=tk.LEFT, padx=6)

        self.fix_perm_img_btn = tk.Button(
            btn_frame,
            text="🛡️ 赋予 777 权限",
            font=("Segoe UI", 10),
            bg="#f59e0b",
            fg="#ffffff",
            relief=tk.FLAT,
            padx=12,
            pady=8,
            cursor="hand2",
            command=lambda: self._fix_permissions_action(self.img_mount_name_var.get().strip())
        )
        self.fix_perm_img_btn.pack(side=tk.LEFT, padx=6)

        self.unmount_img_btn = tk.Button(
            btn_frame,
            text="⏏️ 卸载此镜像",
            font=("Segoe UI", 10),
            bg="#fee2e2",
            fg="#b91c1c",
            relief=tk.FLAT,
            padx=14,
            pady=8,
            cursor="hand2",
            command=self._unmount_image_file_action
        )
        self.unmount_img_btn.pack(side=tk.LEFT, padx=6)

    def log(self, message: str, level: str = "INFO"):
        """Append log message with timestamp."""
        timestamp = time.strftime("%H:%M:%S")
        line = f"[{timestamp}] [{level}] {message}\n"
        self.log_text.insert(tk.END, line)
        self.log_text.see(tk.END)
        logger.log({"ERROR": logging.ERROR, "WARN": logging.WARNING}.get(level, logging.INFO), message)

    def _refresh_system_status(self):
        self._wsl_ready = self._physical_ready = self._format_ready = False
        for button in (self.mount_phys_btn, self.mount_img_btn, self.format_phys_btn):
            button.configure(state=tk.DISABLED)
        admin_ok = is_admin()
        if admin_ok:
            self.admin_badge.configure(text="🛡️ 管理员权限 (已激活)", fg="#15803d", bg="#dcfce7")
        else:
            self.admin_badge.configure(text="🛡️ 普通权限 (物理挂载时将触发UAC)", fg="#b45309", bg="#fef3c7")

        def worker():
            info = get_wsl_distros()
            info["host"] = get_windows_support()
            if info.get("distros") and info["host"]["supported"]:
                info["capabilities"] = get_wsl_capabilities()
            self._post_ui(lambda: self._on_system_status(info))
        self._start_worker(worker)

    def _on_system_status(self, info):
        host = info.get("host", {})
        if host:
            self.log(f"{host['name']} (build {host.get('build', '?')})")
        if host and not host["supported"]:
            info["error"] = host["error"]
        if info.get("error") or not info.get("distros"):
            self.wsl_badge.configure(text="WSL: 不可用", fg="#b91c1c", bg="#fee2e2")
            detail = wsl_environment_error(info)
            self._notify_failure("WSL 不可用", detail, warning=True)
            return
        distros = [d for d in info["distros"] if info.get("versions", {}).get(d) == 2]
        if not distros:
            self.wsl_badge.configure(text="WSL 2: 未配置", fg="#b91c1c", bg="#fee2e2")
            self._notify_failure("需要 WSL 2", wsl_environment_error(info), warning=True)
            return
        distro = "Ubuntu" if "Ubuntu" in distros else (info.get("default") if info.get("default") in distros else distros[0])
        self.mounter.set_distro(distro)
        self._wsl_ready = True
        self.wsl_badge.configure(text=f"WSL: {distro}", fg="#0369a1", bg="#e0f2fe")
        capabilities = info.get("capabilities", {})
        physical_error = mount_support_error(capabilities)
        self._physical_ready = not physical_error
        self._format_ready = not mount_support_error(capabilities, named=False)
        self.mount_phys_btn.configure(state=tk.NORMAL if self._physical_ready else tk.DISABLED)
        self.format_phys_btn.configure(state=tk.NORMAL if self._format_ready else tk.DISABLED)
        self.mount_img_btn.configure(state=tk.NORMAL)
        self.log(f"WSL 分发版: [{distro}]")
        if physical_error:
            self._notify_failure("请更新 WSL", physical_error, warning=True)

    def _refresh_discovery(self):
        if self.is_busy:
            return
        self._refresh_system_status()
        self._async_load_disks()

    def _async_load_disks(self):
        self.disk_combo.set("正在扫描物理磁盘...")
        self.part_combo.set("")
        self.part_info_card.configure(text="正在枚举系统磁盘与分区，请稍候...")
        self.log("正在枚举物理磁盘与分区...")

        def worker():
            try:
                disks = get_physical_disks(strict=True)
            except Exception as error:
                logger.exception("Disk discovery failed")
                self._post_ui(lambda error=error: self._on_disks_failed(error))
                return
            self._post_ui(lambda: self._on_disks_loaded(disks))

        self._start_worker(worker)

    def _on_disks_failed(self, error):
        self._on_disks_loaded([])
        self.disk_combo.set("磁盘查询失败（可修复后刷新）")
        self._show_error(error, reset_action=False)

    def _on_disks_loaded(self, disks: List[Dict[str, Any]]):
        self.disks_cache = disks
        if not disks:
            self.disk_combo.set("未检测到物理磁盘")
            self.part_info_card.configure(text="未发现可用磁盘。请检查磁盘连接、PowerShell 存储服务及访问权限；详情见日志。")
            self.log("未检测到物理磁盘", level="WARN")
            return

        values = []
        preferred_index = 0
        for i, d in enumerate(disks):
            label = f"[磁盘 {d['index']}] {d['model']} ({d['size_gb']} GB)"
            values.append(label)
            # Prioritize non-disk-0 or Samsung 870 or large SSD
            if d['index'] != 0 and ("SSD" in d['model'].upper() or "EVO" in d['model'].upper() or d['size_gb'] > 1000):
                preferred_index = i

        self.disk_combo["values"] = values
        self.disk_combo.current(preferred_index)
        self.log(f"已发现 {len(disks)} 个物理磁盘。已自动为您优选: {values[preferred_index]}")
        self._on_disk_selected(None)

    def _on_disk_selected(self, event):
        idx_str = self.disk_combo.current()
        if idx_str < 0 or idx_str >= len(self.disks_cache):
            return
        disk = self.disks_cache[idx_str]
        disk_idx = disk["index"]

        self.part_combo.set("正在读取分区...")
        self.part_info_card.configure(text=f"正在读取 [磁盘 {disk_idx}] 的分区表...")

        def worker():
            parts = get_disk_partitions(disk_idx)
            self._post_ui(lambda: self._on_partitions_loaded(disk, parts))

        self._start_worker(worker)

    def _on_partitions_loaded(self, disk: Dict[str, Any], partitions: List[Dict[str, Any]]):
        self.current_partitions = partitions
        if not partitions:
            self.part_combo["values"] = ["无可用分区 (RAW未初始化或全盘空白)"]
            self.part_combo.current(0)
            if disk.get("is_system"):
                self.part_info_card.configure(
                    text=f"🛡️ 磁盘 {disk['index']} 为 Windows 系统主盘，未检测到独立 ext4 分区。",
                    fg="#0369a1",
                    bg="#f0f9ff"
                )
            else:
                self.part_info_card.configure(
                    text=f"💡 [磁盘 {disk['index']}] 状态: {disk.get('partition_style', 'RAW')} (未检测到独立分区)\n"
                         f"如需在此固态硬盘上使用 ext4，请点击下方的【🧹 格式化 SSD (ext4)】一键全新初始化并格式化！",
                    fg="#b45309",
                    bg="#fef3c7"
                )
            return

        values = []
        preferred_part_idx = 0
        for i, p in enumerate(partitions):
            tag = "🌟 [强烈推荐: ext4/Linux]" if p["is_linux_candidate"] else ""
            drv = f"(盘符: {p['drive_letter']})" if p['drive_letter'] else "(无盘符)"
            val = f"分区 {p['partition_number']} - 容量: {p['size_gb']} GB {drv} {tag}"
            values.append(val)
            if p["is_linux_candidate"]:
                preferred_part_idx = i

        self.part_combo["values"] = values
        self.part_combo.current(preferred_part_idx)
        self._on_partition_selected(None)

    def _on_partition_selected(self, event):
        idx = self.part_combo.current()
        if idx < 0 or idx >= len(self.current_partitions):
            return
        p = self.current_partitions[idx]
        disk_idx = self.disks_cache[self.disk_combo.current()]["index"]

        status_text = (
            f"📌 分区状态: 分区号 #{p['partition_number']} | 容量: {p['size_gb']} GB\n"
            f"🔍 类型识别: {p['type']} | GUID: {p['guid']}\n"
        )
        if p["is_linux_candidate"]:
            status_text += "✅ 侦测为 Linux ext4 文件系统数据分区！支持一键挂载至 Windows Explorer！"
            self.part_info_card.configure(text=status_text, fg="#15803d", bg="#dcfce7")
        else:
            status_text += f"ℹ️ 当前分区已有 Windows 盘符或为其他格式 ({p.get('drive_letter') or '无盘符'})"
            self.part_info_card.configure(text=status_text, fg="#0369a1", bg="#f0f9ff")

        # Set default mount name
        self.phys_mount_name_var.set(f"ssd_disk{disk_idx}_p{p['partition_number']}")

    def _browse_image_file(self):
        file_path = filedialog.askopenfilename(
            title="选择 ext4 磁盘镜像文件",
            filetypes=[
                ("ext4 / 磁盘镜像", "*.img;*.ext4;*.vhdx;*.vhd;*.raw"),
                ("所有文件", "*.*")
            ]
        )
        if file_path:
            self.img_path_var.set(os.path.normpath(file_path))
            self._on_img_path_changed(None)

    def _on_img_path_changed(self, event):
        path = self.img_path_var.get().strip()
        if not path or not os.path.exists(path):
            self.img_info_card.configure(
                text="请输入或选择有效的镜像文件路径 (.img, .ext4, .vhdx, .vhd, .raw)",
                fg="#0369a1",
                bg="#f0f9ff"
            )
            return

        size_mb = round(os.path.getsize(path) / (1024 * 1024), 2)
        base_name = os.path.splitext(os.path.basename(path))[0]
        # Clean mount name
        clean_name = "".join(c if c.isalnum() or c in "_-" else "_" for c in base_name)
        self.img_mount_name_var.set(f"img_{clean_name}")

        self.img_info_card.configure(
            text=f"📁 已就绪: {os.path.basename(path)} | 文件大小: {size_mb} MB\n"
                 f"💡 即将挂载至: /mnt/wsl/img_{clean_name} (Windows: \\\\wsl$\\...)",
            fg="#15803d",
            bg="#dcfce7"
        )

    def _mount_physical_disk_action(self):
        if self.is_busy:
            return
        disk_pos = self.disk_combo.current()
        part_pos = self.part_combo.current()
        if disk_pos < 0 or part_pos < 0 or not self.current_partitions:
            messagebox.showwarning("提示", "请先选择要挂载的物理磁盘与分区！")
            return

        disk = self.disks_cache[disk_pos]
        part = self.current_partitions[part_pos]
        mount_name = self.phys_mount_name_var.get().strip() or f"ssd_d{disk['index']}_p{part['partition_number']}"
        read_only = self.phys_ro_var.get()
        auto_open = self.phys_auto_open_var.get()
        auto_777 = self.phys_auto_perm_var.get()

        self.is_busy = True
        self.mount_phys_btn.configure(text="⏳ 正在挂载中 (请在UAC弹窗允许)...", state=tk.DISABLED)
        self.log(f"开始挂载物理磁盘 {disk['index']} 分区 {part['partition_number']} -> 挂载名: {mount_name} (只读: {read_only}, 自动777: {auto_777})...")

        def worker():
            success, unc_path, msg = self.mounter.mount_physical_disk(
                disk_index=disk["index"],
                partition_number=part["partition_number"],
                mount_name=mount_name,
                read_only=read_only,
                auto_chmod_777=auto_777
            )
            self._post_ui(lambda: self._on_physical_mount_finished(success, unc_path, msg, auto_open, read_only, auto_777))

        self._start_worker(worker, action=True)

    def _on_physical_mount_finished(self, success: bool, unc_path: str, msg: str, auto_open: bool, read_only: bool, auto_777: bool):
        self.is_busy = False
        self.mount_phys_btn.configure(text="🚀 一键挂载物理 SSD 分区", state=tk.NORMAL)
        self._refresh_active_mounts_table()

        if success:
            self.log(f"挂载成功！UNC 路径: {unc_path}", level="SUCCESS")
            if not read_only and auto_777:
                self.log("已自动赋予该分区 777 权限 (chmod 777 + Default ACL 继承)", level="SUCCESS")
            if auto_open and unc_path:
                open_in_explorer(unc_path)
            messagebox.showinfo("挂载成功", f"物理磁盘分区已成功挂载！\n\n访问路径:\n{unc_path}")
        else:
            self.log(f"挂载失败: {msg}", level="ERROR")
            self._notify_failure("挂载失败", msg)

    def _unmount_physical_disk_action(self):
        if self.is_busy:
            return
        disk_pos = self.disk_combo.current()
        if disk_pos < 0:
            return
        disk = self.disks_cache[disk_pos]
        mount_name = self.phys_mount_name_var.get().strip()

        self.is_busy = True
        self.unmount_phys_btn.configure(text="⏳ 正在卸载...", state=tk.DISABLED)
        self.log(f"开始卸载物理磁盘 {disk['index']}...")

        def worker():
            ok, msg = self.mounter.unmount_physical_disk(disk["index"], mount_name)
            self._post_ui(lambda: self._on_physical_unmount_finished(ok, msg))

        self._start_worker(worker, action=True)

    def _on_physical_unmount_finished(self, ok: bool, msg: str):
        self.is_busy = False
        self.unmount_phys_btn.configure(text="⏏️ 卸载此物理磁盘", state=tk.NORMAL)
        self._refresh_active_mounts_table()
        if ok:
            self.log(f"卸载成功: {msg}", level="SUCCESS")
            messagebox.showinfo("卸载完成", msg)
        else:
            self.log(f"卸载失败: {msg}", level="WARN")
            self._notify_failure("卸载提示", msg, warning=True)

    def _format_ssd_dialog(self):
        if self.is_busy:
            messagebox.showwarning("提示", "当前有任务正在执行，请稍候再试！")
            return

        disk_pos = self.disk_combo.current()
        if disk_pos < 0 or not self.disks_cache:
            messagebox.showwarning("提示", "请先选择要格式化的物理磁盘！")
            return

        disk = self.disks_cache[disk_pos]
        disk_idx = disk["index"]

        # Security Firewall: Prohibit formatting system/boot disk
        if disk.get("is_system") or is_system_disk(disk_idx):
            messagebox.showerror(
                "系统主盘保护",
                f"⛔ 安全阻断：\n\n[磁盘 {disk_idx}] ({disk['model']}) 是当前 Windows 系统的启动/系统主盘 (包含 C: 盘)！\n\n"
                "为了保障您的操作系统与数据安全，本程序严格禁止对系统主盘执行任何格式化操作！"
            )
            return

        has_partitions = bool(self.current_partitions)
        selected_part = None
        part_pos = self.part_combo.current()
        if has_partitions and 0 <= part_pos < len(self.current_partitions):
            selected_part = self.current_partitions[part_pos]

        dialog = tk.Toplevel(self.root)
        dialog.title(f"格式化 SSD / 分区为 ext4 - [磁盘 {disk_idx}]")
        dialog.geometry("560x540")
        dialog.minsize(520, 480)
        dialog.configure(bg=self.card_bg)
        dialog.transient(self.root)
        dialog.grab_set()

        try:
            x = self.root.winfo_x() + (self.root.winfo_width() // 2) - 280
            y = self.root.winfo_y() + (self.root.winfo_height() // 2) - 270
            dialog.geometry(f"+{max(0, x)}+{max(0, y)}")
        except Exception:
            pass

        content_frame = tk.Frame(dialog, bg=self.card_bg, padx=20, pady=16)
        content_frame.pack(fill=tk.BOTH, expand=True)

        # Danger Banner
        banner = tk.Label(
            content_frame,
            text="⚠️ 高危操作警告：格式化将彻底清除目标设备上的全部数据！\n此操作不可撤销，请务必核对目标磁盘编号与型号。",
            font=("Segoe UI", 9, "bold"),
            fg="#b91c1c",
            bg="#fee2e2",
            padx=12,
            pady=8,
            justify=tk.LEFT,
            anchor=tk.W,
            relief=tk.SOLID,
            bd=1
        )
        banner.pack(fill=tk.X, pady=(0, 12))

        # Target Disk Info Box
        info_frame = tk.LabelFrame(
            content_frame,
            text="  🎯 目标磁盘信息  ",
            font=("Segoe UI", 9, "bold"),
            bg=self.card_bg,
            fg=self.text_primary,
            padx=12,
            pady=8
        )
        info_frame.pack(fill=tk.X, pady=(0, 12))

        info_text = (
            f"• 磁盘编号: 磁盘 {disk_idx} ({disk.get('device_id', '')})\n"
            f"• 设备型号: {disk['model']}\n"
            f"• 磁盘总容量: {disk['size_gb']} GB\n"
            f"• 当前分区状态: {disk.get('partition_style', 'RAW')}"
        )
        lbl_info = tk.Label(info_frame, text=info_text, font=("Segoe UI", 9), bg=self.card_bg, justify=tk.LEFT, anchor=tk.W)
        lbl_info.pack(fill=tk.X)

        # Format Mode Selection
        mode_frame = tk.LabelFrame(
            content_frame,
            text="  ⚙️ 格式化范围选择  ",
            font=("Segoe UI", 9, "bold"),
            bg=self.card_bg,
            fg=self.text_primary,
            padx=12,
            pady=8
        )
        mode_frame.pack(fill=tk.X, pady=(0, 12))

        mode_var = tk.StringVar(value="full" if not has_partitions else "part")

        rb_full = ttk.Radiobutton(
            mode_frame,
            text="整盘全新初始化 (清除旧结构，初始化为 GPT 并创建 100% 容量 ext4 分区)",
            value="full",
            variable=mode_var
        )
        rb_full.pack(anchor=tk.W, pady=2)

        part_desc = f"仅格式化选中的 分区 #{selected_part['partition_number']} ({selected_part['size_gb']} GB，保留其他分区)" if selected_part else "仅格式化选中分区 (当前磁盘无独立分区，不可用)"
        rb_part = ttk.Radiobutton(
            mode_frame,
            text=part_desc,
            value="part",
            variable=mode_var,
            state=tk.NORMAL if has_partitions else tk.DISABLED
        )
        rb_part.pack(anchor=tk.W, pady=2)

        # Volume Label row
        label_frame = tk.Frame(content_frame, bg=self.card_bg)
        label_frame.pack(fill=tk.X, pady=(0, 12))

        tk.Label(label_frame, text="ext4 卷标 (Label):", font=("Segoe UI", 9, "bold"), bg=self.card_bg).pack(side=tk.LEFT)
        label_var = tk.StringVar(value="EXT4_SSD")
        entry_label = ttk.Entry(label_frame, textvariable=label_var, width=18, font=("Segoe UI", 9))
        entry_label.pack(side=tk.LEFT, padx=8)
        tk.Label(label_frame, text="(最多16位字母/数字/下划线)", font=("Segoe UI", 8), fg=self.text_muted, bg=self.card_bg).pack(side=tk.LEFT)

        # Safety Double-Confirmation Area
        confirm_frame = tk.LabelFrame(
            content_frame,
            text="  🛡️ 防误触确认 (满足条件后解锁操作)  ",
            font=("Segoe UI", 9, "bold"),
            bg=self.card_bg,
            fg="#dc2626",
            padx=12,
            pady=8
        )
        confirm_frame.pack(fill=tk.X, pady=(0, 12))

        ack_var = tk.BooleanVar(value=False)
        ack_cb = ttk.Checkbutton(
            confirm_frame,
            text="我已知晓格式化将永久清除目标数据，且该过程不可撤销",
            variable=ack_var
        )
        ack_cb.pack(anchor=tk.W, pady=(0, 6))

        prompt_row = tk.Frame(confirm_frame, bg=self.card_bg)
        prompt_row.pack(fill=tk.X)

        tk.Label(
            prompt_row,
            text=f"请输入目标磁盘编号 [{disk_idx}] 或 FORMAT 解锁:",
            font=("Segoe UI", 9),
            bg=self.card_bg
        ).pack(side=tk.LEFT)

        input_confirm_var = tk.StringVar()
        entry_confirm = ttk.Entry(prompt_row, textvariable=input_confirm_var, width=12, font=("Segoe UI", 9, "bold"))
        entry_confirm.pack(side=tk.LEFT, padx=8)

        dlg_status_lbl = tk.Label(
            content_frame,
            text="请完成上方确认以解锁格式化按钮",
            font=("Segoe UI", 8),
            fg=self.text_muted,
            bg=self.card_bg
        )
        dlg_status_lbl.pack(fill=tk.X, pady=(0, 8))

        # Bottom Buttons
        btn_box = tk.Frame(content_frame, bg=self.card_bg)
        btn_box.pack(fill=tk.X, pady=(6, 0))

        cancel_btn = tk.Button(
            btn_box,
            text="取消",
            font=("Segoe UI", 9),
            bg="#f1f5f9",
            fg=self.text_primary,
            relief=tk.SOLID,
            bd=1,
            padx=16,
            pady=6,
            cursor="hand2",
            command=dialog.destroy
        )
        cancel_btn.pack(side=tk.RIGHT, padx=(6, 0))

        do_format_btn = tk.Button(
            btn_box,
            text="💥 确认并立即开始格式化",
            font=("Segoe UI", 9, "bold"),
            bg="#dc2626",
            fg="#ffffff",
            relief=tk.FLAT,
            padx=18,
            pady=6,
            state=tk.DISABLED,
            cursor="hand2"
        )
        do_format_btn.pack(side=tk.RIGHT)

        def _check_unlock(*args):
            is_acked = ack_var.get()
            txt = input_confirm_var.get().strip().upper()
            is_match = (txt == str(disk_idx) or txt == "FORMAT")
            if is_acked and is_match:
                do_format_btn.configure(state=tk.NORMAL)
                dlg_status_lbl.configure(text="✅ 已通过安全校验，点击右侧按钮立即开始格式化", fg="#16a34a")
            else:
                do_format_btn.configure(state=tk.DISABLED)
                dlg_status_lbl.configure(text="请完成上方确认以解锁格式化按钮", fg=self.text_muted)

        ack_var.trace_add("write", _check_unlock)
        input_confirm_var.trace_add("write", _check_unlock)

        def _on_start_format():
            mode = mode_var.get()
            raw_label = label_var.get().strip()
            label = sanitize_label(raw_label)

            dialog.destroy()
            self._execute_format_task(disk, mode, selected_part, label)

        do_format_btn.configure(command=_on_start_format)

    def _execute_format_task(
        self,
        disk: Dict[str, Any],
        mode: str,
        selected_part: Optional[Dict[str, Any]],
        label: str
    ):
        self.is_busy = True
        disk_idx = disk["index"]

        self.format_phys_btn.configure(text="⏳ 正在格式化...", state=tk.DISABLED)
        self.mount_phys_btn.configure(state=tk.DISABLED)

        if mode == "full":
            desc = f"[磁盘 {disk_idx}] 整盘全新初始化并格式化为 ext4 (卷标: {label})"
        else:
            p_num = selected_part["partition_number"] if selected_part else 1
            desc = f"[磁盘 {disk_idx}] 分区 #{p_num} 格式化为 ext4 (卷标: {label})"

        self.log(f"开始执行格式化任务: {desc}，请在弹出的 UAC 提权窗口中允许授权...")

        def worker():
            if mode == "full":
                ok, msg = format_physical_disk_full(disk_idx, label=label, distro=self.mounter.distro)
            else:
                p_num = selected_part["partition_number"] if selected_part else 1
                ok, msg = format_physical_partition(disk_idx, partition_number=p_num, label=label, distro=self.mounter.distro)

            self._post_ui(lambda: self._on_format_task_finished(ok, msg, disk_idx))

        self._start_worker(worker, action=True)

    def _on_format_task_finished(self, ok: bool, msg: str, disk_idx: int):
        self.is_busy = False
        self.format_phys_btn.configure(text="🧹 格式化 SSD (ext4)", state=tk.NORMAL)
        self.mount_phys_btn.configure(state=tk.NORMAL)

        # Refresh disks and partitions to immediately show newly formatted ext4 partition
        self._async_load_disks()

        if ok:
            self.log(f"格式化成功: {msg}", level="SUCCESS")
            messagebox.showinfo(
                "格式化成功",
                f"🎉 ext4 格式化成功完成！\n\n"
                f"{msg}\n\n"
                f"系统已自动重新枚举磁盘与分区。\n"
                f"您现在可以直接点击【🚀 一键挂载物理 SSD 分区】挂载并在资源管理器中打开！"
            )
        else:
            self.log(f"格式化未成功: {msg}", level="ERROR")
            self._notify_failure("格式化失败", msg)

    def _mount_image_file_action(self):
        if self.is_busy:
            return
        file_path = self.img_path_var.get().strip()
        if not file_path or not os.path.exists(file_path):
            messagebox.showwarning("提示", "请选择有效的镜像文件！")
            return

        mount_name = self.img_mount_name_var.get().strip() or "my_ext4_img"
        read_only = self.img_ro_var.get()
        auto_open = self.img_auto_open_var.get()
        auto_777 = self.img_auto_perm_var.get()

        self.is_busy = True
        self.mount_img_btn.configure(text="⏳ 正在挂载镜像中...", state=tk.DISABLED)
        self.log(f"开始挂载镜像文件: {file_path} -> 挂载名: {mount_name} (只读: {read_only}, 自动777: {auto_777})...")

        def worker():
            success, unc_path, msg = self.mounter.mount_image_file(
                file_path=file_path,
                mount_name=mount_name,
                read_only=read_only,
                auto_chmod_777=auto_777
            )
            self._post_ui(lambda: self._on_image_mount_finished(success, unc_path, msg, auto_open, read_only, auto_777))

        self._start_worker(worker, action=True)

    def _on_image_mount_finished(self, success: bool, unc_path: str, msg: str, auto_open: bool, read_only: bool, auto_777: bool):
        self.is_busy = False
        self.mount_img_btn.configure(text="🚀 一键挂载 ext4 镜像文件", state=tk.NORMAL)
        self._refresh_active_mounts_table()

        if success:
            self.log(f"镜像挂载成功: {unc_path}", level="SUCCESS")
            if not read_only and auto_777:
                self.log("已自动赋予该镜像 777 权限 (chmod 777 + Default ACL 继承)", level="SUCCESS")
            if auto_open and unc_path:
                open_in_explorer(unc_path)
            messagebox.showinfo("挂载成功", f"ext4 镜像文件已成功挂载！\n\n访问路径:\n{unc_path}")
        else:
            self.log(f"镜像挂载失败: {msg}", level="ERROR")
            self._notify_failure("挂载失败", msg)

    def _unmount_image_file_action(self):
        if self.is_busy:
            return
        mount_name = self.img_mount_name_var.get().strip()
        file_path = self.img_path_var.get().strip()

        self.is_busy = True
        self.unmount_img_btn.configure(text="⏳ 正在卸载...", state=tk.DISABLED)
        self.log(f"正在卸载镜像挂载点: {mount_name}...")

        def worker():
            ok, msg = self.mounter.unmount_image_file(mount_name, file_path)
            self._post_ui(lambda: self._on_image_unmount_finished(ok, msg))

        self._start_worker(worker, action=True)

    def _on_image_unmount_finished(self, ok: bool, msg: str):
        self.is_busy = False
        self.unmount_img_btn.configure(text="⏏️ 卸载此镜像", state=tk.NORMAL)
        self._refresh_active_mounts_table()
        if ok:
            self.log(f"镜像卸载成功: {msg}", level="SUCCESS")
            messagebox.showinfo("卸载完成", msg)
        else:
            self.log(f"镜像卸载提示: {msg}", level="WARN")
            self._notify_failure("卸载提示", msg, warning=True)

    def _refresh_active_mounts_table(self):
        def worker():
            mounts = self.mounter.list_active_mounts()
            self._post_ui(lambda: self._on_active_mounts_loaded(mounts))
        self._start_worker(worker)

    def _on_active_mounts_loaded(self, mounts):
        # Clear tree
        for item in self.mounts_tree.get_children():
            self.mounts_tree.delete(item)

        for m in mounts:
            name = m.get("mount_name", "")
            m_type = "物理磁盘" if m.get("type") == "physical" else "镜像文件"
            target = m.get("device_path") or os.path.basename(m.get("file_path", ""))
            unc = m.get("unc_path", "")
            mode = "只读 (ro)" if m.get("read_only") else "读写 (rw)"
            self.mounts_tree.insert("", tk.END, values=(name, m_type, target, unc, mode))

    def _open_selected_mount(self):
        selected = self.mounts_tree.selection()
        if not selected:
            messagebox.showinfo("提示", "请先在表格中选择要打开的挂载项！")
            return
        item_vals = self.mounts_tree.item(selected[0], "values")
        unc_path = item_vals[3]
        if unc_path:
            self.log(f"正在打开目录: {unc_path}")
            open_in_explorer(unc_path)

    def _open_mount_by_name(self, mount_name: str):
        if not mount_name:
            return
        unc_path = self.mounter.get_unc_path(mount_name)
        if os.path.exists(unc_path) or self.mounter.check_mount_exists(mount_name):
            self.log(f"在资源管理器中打开: {unc_path}")
            open_in_explorer(unc_path)
        else:
            messagebox.showinfo("提示", f"挂载点 {mount_name} 当前尚未挂载！请先点击挂载。")

    def _fix_selected_mount_permissions(self):
        selected = self.mounts_tree.selection()
        if not selected:
            messagebox.showinfo("提示", "请先在表格中选择要修复权限的挂载项！")
            return
        item_vals = self.mounts_tree.item(selected[0], "values")
        mount_name = item_vals[0]
        self._fix_permissions_action(mount_name)

    def _fix_permissions_action(self, mount_name: str):
        if self.is_busy:
            return
        if not mount_name:
            messagebox.showwarning("提示", "请输入或选择要修复权限的挂载名称！")
            return

        if not self.mounter.check_mount_exists(mount_name):
            messagebox.showwarning("提示", f"挂载点 {mount_name} 尚未挂载或不可访问！请先执行挂载。")
            return

        if not messagebox.askyesno(
            "确认赋予 777 权限",
            f"即将对挂载点 [{mount_name}] 递归赋予全员 777 完全控制权限 (chmod -R 777) 并配置新建文件 Default ACL 自动继承。\n\n"
            "此操作将彻底消除 Windows 下由于 Linux root 或只读权限导致的“拒绝访问”问题，且之后新建的文件/目录都将自动继承 777。\n\n"
            "是否立即执行？"
        ):
            return

        self.is_busy = True
        self.log(f"正在对挂载点 [{mount_name}] 执行 777 权限配置 (chmod -R 777 + Default ACL)...")

        def worker():
            ok, msg = self.mounter.fix_permissions(mount_name, mode="rw", restore_ro=False)
            self._post_ui(lambda: self._on_fix_permissions_finished(mount_name, ok, msg))

        self._start_worker(worker, action=True)

    def _on_fix_permissions_finished(self, mount_name: str, ok: bool, msg: str):
        self.is_busy = False
        self._refresh_active_mounts_table()
        if ok:
            self.log(f"挂载点 [{mount_name}] 777 权限配置成功: {msg}", level="SUCCESS")
            messagebox.showinfo("配置成功", f"挂载点 [{mount_name}] 777 权限配置成功！\n\n全部现有文件/目录已开放 777 读写权限，且新建文件/文件夹将自动继承完全控制权限。")
        else:
            self.log(f"挂载点 [{mount_name}] 权限配置提示: {msg}", level="WARN")
            self._notify_failure("配置提示", msg, warning=True)

    def _fix_selected_rosbag_permissions(self):
        selected = self.mounts_tree.selection()
        if not selected:
            messagebox.showinfo("提示", "请先在表格中选择要修复 mcap 权限的挂载项！")
            return
        item_vals = self.mounts_tree.item(selected[0], "values")
        mount_name = item_vals[0]
        self._fix_rosbag_permissions_action(mount_name)

    def _fix_rosbag_permissions_action(self, mount_name: str, target_dir: Optional[str] = None):
        if self.is_busy:
            return
        if not mount_name:
            messagebox.showwarning("提示", "请输入或在表格中选择要修复权限的挂载名称！")
            return

        if not self.mounter.check_mount_exists(mount_name):
            messagebox.showwarning("提示", f"挂载点 [{mount_name}] 尚未挂载或不可访问！请先执行挂载。")
            return

        detected = self.mounter.detect_rosbag_dirs(mount_name)
        folder_tip = ""
        if detected:
            folder_tip = f"\n\n已检测到相关目录：\n  " + "\n  ".join([f"📁 {d}" for d in detected[:5]])
            if not target_dir and len(detected) == 1:
                target_dir = detected[0]

        target_desc = f"子目录 [{target_dir}]" if target_dir else f"挂载点 [{mount_name}] 全部目录"

        if not messagebox.askyesno(
            "确认修复 ROS2 / mcap 权限",
            f"即将对 {target_desc} 执行 ROS2 / mcap 专项权限修复：\n\n"
            "• 彻底解决 Windows 资源管理器显示「大小: 0 字节 / 0 个文件」问题（常见于 Docker/ROS2 写入的数据）\n"
            "• 递归为全部 mcap/bag 录制目录与文件开放读取与遍历权限 (chmod a+rX + POSIX Default ACL 继承)\n"
            "• 若当前为只读挂载，修复完成后将自动恢复只读保护，确保数据安全\n"
            f"{folder_tip}\n\n"
            "是否立即开始修复？"
        ):
            return

        self.is_busy = True
        self.log(f"正在对挂载点 [{mount_name}] 执行 ROS2/mcap 权限修复...")

        def worker():
            ok, msg = self.mounter.fix_rosbag_permissions(mount_name, target_dir=target_dir)
            self._post_ui(lambda: self._on_fix_rosbag_permissions_finished(mount_name, ok, msg))

        self._start_worker(worker, action=True)

    def _on_fix_rosbag_permissions_finished(self, mount_name: str, ok: bool, msg: str):
        self.is_busy = False
        self._refresh_active_mounts_table()
        if ok:
            self.log(f"挂载点 [{mount_name}] mcap 权限修复成功: {msg}", level="SUCCESS")
            messagebox.showinfo(
                "修复成功",
                f"挂载点 [{mount_name}] ROS2/mcap 权限修复完成！\n\n"
                f"{msg}\n\n"
                "💡 提示：您现在可以在 Windows 资源管理器中刷新查看，文件夹属性、大小与全部 .mcap 文件即可正常显示与读取。"
            )
        else:
            self.log(f"挂载点 [{mount_name}] mcap 权限修复未完成: {msg}", level="WARN")
            self._notify_failure("修复提示", msg, warning=True)

    def _start_permission_guard(self):
        """Start periodic light background sweep to ensure RW mounts always have 777 permissions."""
        self._permission_guard_tick()

    def _permission_guard_tick(self):
        if self._closed.is_set():
            return
        try:
            active = load_saved_mounts()
            rw_mounts = [m.get("mount_name") for m in active if not m.get("read_only") and m.get("mount_name")]
            if rw_mounts and self._wsl_ready and not self.is_busy:
                def bg_sweep():
                    for name in rw_mounts:
                        if self.mounter.check_mount_exists(name):
                            self.mounter.sweep_permissions(name)
                self._start_worker(bg_sweep)
        except Exception:
            logger.exception("Permission guard failed")
        # Sweep every 45 seconds
        self._guard_timer = self.root.after(45000, self._permission_guard_tick)

    def _unmount_selected_mount(self):
        selected = self.mounts_tree.selection()
        if not selected:
            messagebox.showinfo("提示", "请先在表格中选择要卸载的项！")
            return
        item_vals = self.mounts_tree.item(selected[0], "values")
        mount_name = item_vals[0]
        m_type = item_vals[1]

        self.log(f"开始卸载选中项: {mount_name} ({m_type})...")
        if m_type == "物理磁盘":
            # Find disk index from saved mounts
            disk_idx = 1
            for m in load_saved_mounts():
                if m.get("mount_name") == mount_name:
                    disk_idx = m.get("disk_index", 1)
                    break
            ok, msg = self.mounter.unmount_physical_disk(disk_idx, mount_name)
        else:
            ok, msg = self.mounter.unmount_image_file(mount_name)

        self._refresh_active_mounts_table()
        if ok:
            self.log(f"已卸载: {mount_name}", level="SUCCESS")
        else:
            self.log(f"卸载提示: {msg}", level="WARN")

    def _unmount_all(self):
        if not messagebox.askyesno("确认全部卸载", "是否确认安全卸载并释放所有已挂载的磁盘和镜像文件？"):
            return

        self.log("正在执行安全卸载全部设备...")
        results = self.mounter.unmount_all()
        self._refresh_active_mounts_table()
        self.log(f"全部卸载操作完成！处理结果数: {len(results)}", level="SUCCESS")
        messagebox.showinfo("卸载完成", "所有 ext4 设备与镜像已成功安全断开！")

    def _create_desktop_shortcut_ui(self):
        script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "main.py"))
        python_exe = sys.executable
        # Try to use pythonw for windowed launch if available
        pythonw = os.path.join(os.path.dirname(python_exe), "pythonw.exe")
        frozen = getattr(sys, "frozen", False)
        target = python_exe if frozen else (pythonw if os.path.exists(pythonw) else python_exe)

        ok, res = create_desktop_shortcut(
            target_path=target,
            shortcut_name="Ext4 一键挂载小工具",
            arguments="" if frozen else f'"{script_path}"'
        )
        if ok:
            self.log(f"快捷方式已成功创建至桌面: {res}", level="SUCCESS")
            messagebox.showinfo("成功", f"桌面快捷方式创建成功！\n\n路径: {res}")
        else:
            self.log(f"创建桌面快捷方式失败: {res}", level="ERROR")
            self._notify_failure("创建快捷方式失败", res)


def run_app():
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("The Tk GUI must run on the main thread")
    root = tk.Tk()
    try:
        app = Ext4MounterApp(root)
        root.mainloop()
    finally:
        if 'app' in locals() and not app._closed.is_set():
            app._close()
        try:
            root.destroy()
        except tk.TclError:
            pass

if __name__ == "__main__":
    run_app()
