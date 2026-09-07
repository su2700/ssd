# Ext4 SSD & 镜像文件一键挂载桌面小工具 (Windows)

专为 Windows 10/11 用户打造的 **ext4 文件系统一键挂载桌面小工具**。

支持直接挂载读取物理 SSD / 移动硬盘上的 ext4 分区（如 `Samsung SSD 870 EVO 4TB` 等），以及各类 ext4 磁盘镜像文件（`.img`、`.ext4`、`.vhdx`、`.raw` 等），挂载成功后自动在 Windows 资源管理器中打开，支持安全只读模式与干净卸载。

---

## ✨ 核心特性

1. **物理 SSD 分区一键挂载**
   - 自动识别接入 Windows 的物理磁盘与分区表。
   - 智能高亮 Linux ext4 候选分区（识别 GUID 与 Linux 文件系统特征，无需死记命令）。
   - 自动处理 Windows UAC 管理员提权，告别繁琐的命令行操作。
2. **ext4 镜像文件秒级挂载**
   - 支持 `.img`, `.ext4`, `.vhdx`, `.vhd`, `.raw` 等多种镜像格式。
   - 通过 WSL2 loopback 高速桥接，**无需 Windows 管理员权限**即可秒级挂载与访问。
3. **Windows 资源管理器原生集成**
   - 挂载后自动唤起 Windows File Explorer 窗口，直接像本地文件夹一样浏览、拖拽、拷贝文件。
4. **数据安全防护 (Safe Mode)**
   - 默认开启“**安全只读模式 (Read-Only)**”，防止 ext4 日志损坏或在 Windows 中误写误删。
   - 随时可勾选切换为“读写模式 (Read-Write)”。
5. **一键安全卸载与全部释放**
   - 提供独立卸载与【⚠️ 全部卸载】按钮，干净释放 Linux loop 占用与物理驱动器锁，防止数据损坏。
6. **开箱即用桌面快捷方式**
   - 已在用户桌面生成 `Ext4-Mounter.lnk`，双击即可直接启动，无控制台黑框打扰。

---

## 🚀 启动方式

### 方式 1：双击桌面图标（推荐）
直接双击 Windows 桌面上的 **`Ext4-Mounter`** 快捷方式。

### 方式 2：双击启动脚本
在项目根目录下双击：
- `start_ext4_mounter.bat`：普通启动（静默无黑框）
- `start_as_admin.bat`：以管理员身份直接启动

### 方式 3：命令行启动
```pwsh
python main.py
```

---

## 📖 使用指南

### 1. 挂载物理 SSD 上的 ext4 分区
1. 打开小工具，进入 **【💾 物理 SSD / 磁盘分区挂载】** 选项卡。
2. 在“选择物理磁盘”下拉菜单中选择目标 SSD（例如 `[磁盘 1] Samsung SSD 870 EVO 4TB`）。
3. 工具会自动列出该磁盘的分区，并用 `🌟 [强烈推荐: ext4/Linux]` 高亮 Linux 分区。
4. 保持勾选“安全只读模式”（推荐）与“挂载后自动打开资源管理器”。
5. 点击 **【🚀 一键挂载物理 SSD 分区】**。
6. 若弹出 Windows UAC 提示，点击“是”允许。
7. 挂载成功后，Windows 资源管理器将自动弹出，显示该 ext4 分区内的全部文件！
8. 读取完毕后，点击 **【⏏️ 卸载此物理磁盘】** 安全断开。

### 2. 挂载 ext4 镜像文件 (.img / .ext4 / .vhdx)
1. 进入 **【📁 ext4 镜像文件挂载】** 选项卡。
2. 点击 **【📂 浏览文件...】**，选择 `.img`、`.ext4` 或 `.vhdx` 文件。
3. 点击 **【🚀 一键挂载 ext4 镜像文件】**。
4. 资源管理器瞬间打开，随心浏览或复制文件。
5. 复制完成后点击 **【⏏️ 卸载此镜像】**。

---

## 🛠️ 技术架构

```
ssd/
├── core/
│   ├── disk_detector.py     # 物理磁盘、分区表与 ext4 智能识别引擎
│   ├── wsl_mounter.py       # WSL2 原生内核挂载与镜像 Loopback 调度器
│   ├── explorer_helper.py   # Windows Explorer 唤起与盘符映射助手
│   └── __init__.py
├── gui/
│   ├── app.py               # 现代化 Tkinter/ttk 桌面 GUI 实现
│   └── __init__.py
├── scripts/
│   └── create_desktop_shortcut.ps1 # 桌面快捷方式生成器
├── tests/
│   ├── test_detector.py     # 磁盘侦测单元测试
│   └── test_mounter.py      # ext4 镜像挂载与卸载端到端测试
├── main.py                  # 主程序入口
├── start_ext4_mounter.bat   # 无黑框启动脚本
├── start_as_admin.bat       # 管理员提权启动脚本
└── README.md                # 使用说明文档
```

---

## 🧪 自动化测试验证

在项目根目录下运行单元与集成测试：
```pwsh
python -m unittest discover -s tests
```
所有 6 项测试（磁盘枚举、分区识别、路径转换、WSL 挂载/卸载）均已自动通过。
