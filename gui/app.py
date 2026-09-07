import os
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Dict, List, Optional, Any

from core.disk_detector import (
    is_admin,
    get_wsl_distros,
    get_physical_disks,
    get_disk_partitions,
    get_free_drive_letters
)
from core.wsl_mounter import WslMounter, load_saved_mounts
from core.explorer_helper import (
    open_in_explorer,
    map_drive_letter,
    unmap_drive_letter,
    create_desktop_shortcut
)

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
        self.mounter = WslMounter()

        # State tracking
        self.disks_cache: List[Dict[str, Any]] = []
        self.current_partitions: List[Dict[str, Any]] = []
        self.is_busy = False

        self._build_ui()
        self._refresh_system_status()
        self._async_load_disks()
        self._refresh_active_mounts_table()

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
            command=self._async_load_disks
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
        opt_frame.pack(fill=tk.X, pady=6)

        lbl_name = tk.Label(opt_frame, text="自定义挂载名:", font=("Segoe UI", 9), bg=self.card_bg)
        lbl_name.pack(side=tk.LEFT)

        self.phys_mount_name_var = tk.StringVar(value="ssd_ext4")
        self.phys_mount_name_entry = ttk.Entry(opt_frame, textvariable=self.phys_mount_name_var, width=16)
        self.phys_mount_name_entry.pack(side=tk.LEFT, padx=6)

        self.phys_ro_var = tk.BooleanVar(value=True)
        self.phys_ro_cb = ttk.Checkbutton(
            opt_frame,
            text="安全只读模式 (推荐，保护 ext4 数据不被意外破坏)",
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
            text="提示: 支持 .img, .ext4, .vhdx, .vhd, .raw 等镜像文件。无需管理员权限即可秒级挂载！",
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
        opt_frame.pack(fill=tk.X, pady=6)

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

    def _refresh_system_status(self):
        admin_ok = is_admin()
        if admin_ok:
            self.admin_badge.configure(text="🛡️ 管理员权限 (已激活)", fg="#15803d", bg="#dcfce7")
        else:
            self.admin_badge.configure(text="🛡️ 普通权限 (物理挂载时将触发UAC)", fg="#b45309", bg="#fef3c7")

        wsl_info = get_wsl_distros()
        distro = wsl_info.get("default") or "未检测到"
        self.wsl_badge.configure(text=f"WSL2: {distro} (就绪)", fg="#0369a1", bg="#e0f2fe")
        self.mounter.set_distro(self.mounter.distro)
        self.log(f"系统就绪: WSL 默认分发版为 [{self.mounter.distro}], 管理员权限: {admin_ok}")

    def _async_load_disks(self):
        self.disk_combo.set("正在扫描物理磁盘...")
        self.part_combo.set("")
        self.part_info_card.configure(text="正在枚举系统磁盘与分区，请稍候...")
        self.log("正在枚举物理磁盘与分区...")

        def worker():
            disks = get_physical_disks()
            self.root.after(0, lambda: self._on_disks_loaded(disks))

        threading.Thread(target=worker, daemon=True).start()

    def _on_disks_loaded(self, disks: List[Dict[str, Any]]):
        self.disks_cache = disks
        if not disks:
            self.disk_combo.set("未检测到物理磁盘")
            self.part_info_card.configure(text="未发现可用磁盘。请确认磁盘已连接并处于联机状态。")
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
            self.root.after(0, lambda: self._on_partitions_loaded(disk, parts))

        threading.Thread(target=worker, daemon=True).start()

    def _on_partitions_loaded(self, disk: Dict[str, Any], partitions: List[Dict[str, Any]]):
        self.current_partitions = partitions
        if not partitions:
            self.part_combo["values"] = ["无可用分区或已占用"]
            self.part_combo.current(0)
            self.part_info_card.configure(text=f"磁盘 {disk['index']} 未检测到独立分区。")
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
                 f"💡 即将挂载至: /mnt/wsl/img_{clean_name} (Windows: \\\\wsl.localhost\\...)",
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

        self.is_busy = True
        self.mount_phys_btn.configure(text="⏳ 正在挂载中 (请在UAC弹窗允许)...", state=tk.DISABLED)
        self.log(f"开始挂载物理磁盘 {disk['index']} 分区 {part['partition_number']} -> 挂载名: {mount_name} (只读: {read_only})...")

        def worker():
            success, unc_path, msg = self.mounter.mount_physical_disk(
                disk_index=disk["index"],
                partition_number=part["partition_number"],
                mount_name=mount_name,
                read_only=read_only
            )
            self.root.after(0, lambda: self._on_physical_mount_finished(success, unc_path, msg, auto_open))

        threading.Thread(target=worker, daemon=True).start()

    def _on_physical_mount_finished(self, success: bool, unc_path: str, msg: str, auto_open: bool):
        self.is_busy = False
        self.mount_phys_btn.configure(text="🚀 一键挂载物理 SSD 分区", state=tk.NORMAL)
        self._refresh_active_mounts_table()

        if success:
            self.log(f"挂载成功！UNC 路径: {unc_path}", level="SUCCESS")
            if auto_open and unc_path:
                open_in_explorer(unc_path)
            messagebox.showinfo("挂载成功", f"物理磁盘分区已成功挂载！\n\n访问路径:\n{unc_path}")
        else:
            self.log(f"挂载失败: {msg}", level="ERROR")
            messagebox.showerror("挂载失败", f"挂载操作未成功完成。\n\n详情:\n{msg}")

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
            self.root.after(0, lambda: self._on_physical_unmount_finished(ok, msg))

        threading.Thread(target=worker, daemon=True).start()

    def _on_physical_unmount_finished(self, ok: bool, msg: str):
        self.is_busy = False
        self.unmount_phys_btn.configure(text="⏏️ 卸载此物理磁盘", state=tk.NORMAL)
        self._refresh_active_mounts_table()
        if ok:
            self.log(f"卸载成功: {msg}", level="SUCCESS")
            messagebox.showinfo("卸载完成", msg)
        else:
            self.log(f"卸载失败: {msg}", level="WARN")
            messagebox.showwarning("卸载提示", msg)

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

        self.is_busy = True
        self.mount_img_btn.configure(text="⏳ 正在挂载镜像中...", state=tk.DISABLED)
        self.log(f"开始挂载镜像文件: {file_path} -> 挂载名: {mount_name} (只读: {read_only})...")

        def worker():
            success, unc_path, msg = self.mounter.mount_image_file(
                file_path=file_path,
                mount_name=mount_name,
                read_only=read_only
            )
            self.root.after(0, lambda: self._on_image_mount_finished(success, unc_path, msg, auto_open))

        threading.Thread(target=worker, daemon=True).start()

    def _on_image_mount_finished(self, success: bool, unc_path: str, msg: str, auto_open: bool):
        self.is_busy = False
        self.mount_img_btn.configure(text="🚀 一键挂载 ext4 镜像文件", state=tk.NORMAL)
        self._refresh_active_mounts_table()

        if success:
            self.log(f"镜像挂载成功: {unc_path}", level="SUCCESS")
            if auto_open and unc_path:
                open_in_explorer(unc_path)
            messagebox.showinfo("挂载成功", f"ext4 镜像文件已成功挂载！\n\n访问路径:\n{unc_path}")
        else:
            self.log(f"镜像挂载失败: {msg}", level="ERROR")
            messagebox.showerror("挂载失败", f"镜像文件挂载失败。\n\n详情:\n{msg}")

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
            self.root.after(0, lambda: self._on_image_unmount_finished(ok, msg))

        threading.Thread(target=worker, daemon=True).start()

    def _on_image_unmount_finished(self, ok: bool, msg: str):
        self.is_busy = False
        self.unmount_img_btn.configure(text="⏏️ 卸载此镜像", state=tk.NORMAL)
        self._refresh_active_mounts_table()
        if ok:
            self.log(f"镜像卸载成功: {msg}", level="SUCCESS")
            messagebox.showinfo("卸载完成", msg)
        else:
            self.log(f"镜像卸载提示: {msg}", level="WARN")
            messagebox.showwarning("卸载提示", msg)

    def _refresh_active_mounts_table(self):
        # Clear tree
        for item in self.mounts_tree.get_children():
            self.mounts_tree.delete(item)

        mounts = self.mounter.list_active_mounts()
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
        target = pythonw if os.path.exists(pythonw) else python_exe

        ok, res = create_desktop_shortcut(
            target_path=target,
            shortcut_name="Ext4 一键挂载小工具",
            arguments=f'"{script_path}"'
        )
        if ok:
            self.log(f"快捷方式已成功创建至桌面: {res}", level="SUCCESS")
            messagebox.showinfo("成功", f"桌面快捷方式创建成功！\n\n路径: {res}")
        else:
            self.log(f"创建桌面快捷方式失败: {res}", level="ERROR")
            messagebox.showerror("失败", f"创建快捷方式失败: {res}")


def run_app():
    root = tk.Tk()
    app = Ext4MounterApp(root)
    root.mainloop()

if __name__ == "__main__":
    run_app()
