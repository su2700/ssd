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
   - 随附一键安装脚本，自动在桌面生成 `Ext4-Mounter.lnk`，双击即可直接启动，无控制台黑框打扰。
7. **SSD / 分区一键格式化为 ext4 (全新升级)**
   - 专为新接入的空白/RAW 固态硬盘打造，内置【🧹 格式化 SSD (ext4)】操作向导。
   - 支持全自动 GPT 初始化与 Linux 数据分区创建，借助 WSL2 原生 `mkfs.ext4` 秒级格式化。
   - 针对 4TB 等大容量 SSD 专项优化（`-m 1`，为 4TB SSD 挽回 ~160GB 空间）。
   - 内置严格的系统盘防火墙锁定（严禁格式化 Disk 0 / C: 系统盘）与二次输入防误触校验。

---

## 📦 环境准备与安装

### 1. 系统与前置环境要求

- **操作系统**：
  - Windows 10（版本 2004 及以上 / 内部版本 19041+）或 Windows 11。
- **WSL 2（Windows 适用于 Linux 的子系统）**：
  - 本工具利用 Windows 官方 WSL 2 及其 Linux 原生内核驱动实现 ext4 分区与镜像文件的安全挂载。
  - **检查 WSL 状态**：打开 PowerShell 运行 `wsl --status` 或 `wsl -l -v`。
  - **安装 WSL 2（若尚未安装）**：以管理员身份打开 PowerShell，运行以下命令（会自动启用虚拟化支持、安装 WSL2 内核及默认 Ubuntu 发行版）：
    ```powershell
    wsl --install
    ```
    *安装完成后，根据系统提示重启电脑即可。*
  - **确保默认版本为 WSL 2**：
    ```powershell
    wsl --set-default-version 2
    ```
- **Python 3.8+**：
  - 前往 [Python 官网](https://www.python.org/downloads/) 下载并安装 Python 3.8 或更高版本。
  - ⚠️ **重要提示**：安装 Python 向导页面底部务必勾选 **“Add python.exe to PATH”**（将 Python 添加到环境变量）。
  - ✨ **零第三方 pip 依赖**：本项目完全基于 Python 原生标准库（Tkinter、ctypes、subprocess 等）开发，**无需执行任何 `pip install`**，极其纯净小巧！

---

### 2. 软件安装步骤

#### 步骤一：获取项目源码
将本项目克隆或下载解压到本地任意目录（例如 `C:\Users\<用户名>\Documents\ssd`）：
```bash
git clone https://github.com/su2700/ssd.git
cd ssd
```
*（也可以直接在代码托管页面点击“Download ZIP”并解压）。*

#### 步骤二：一键安装桌面快捷方式（推荐）
进入项目根目录，找到并**双击运行**：
👉 **`install_desktop_shortcut.bat`**

- 脚本会自动检测您电脑中的 `pythonw.exe` / `python.exe` 路径与项目入口。
- 自动在当前用户的 **Windows 桌面** 上生成名为 **`Ext4-Mounter`** 的快捷方式。
- 提示 `[OK] 安装成功！已在桌面生成 "Ext4-Mounter" 快捷方式！`。

至此安装已全部完成！后续无需再进入文件夹或打开终端，在桌面上双击即可一键打开应用。

#### 步骤三（可选）：打包为单文件独立可执行文件 (.exe)
如果您希望脱离 Python 解释器在其他 Windows 机器上直接免安装运行：
1. 双击运行 `scripts\build_exe.bat`。
2. 脚本会自动使用 PyInstaller 将应用打包为无黑框的单文件可执行程序。
3. 打包产物将生成在 `dist\Ext4-Mounter.exe`，直接双击该 exe 即可运行。

#### 步骤四（可选）：运行自测验证
在项目根目录下的命令行中运行单元测试，验证所有磁盘探测与挂载模块正常工作：
```pwsh
python -m unittest discover -s tests
```
若显示 `Ran 6 tests in ... OK`，说明环境一切就绪。

---

## 🚀 启动方式

安装完成后，可通过以下任意方式启动小工具：

### 方式 1：双击桌面图标（推荐，无黑框）
直接双击 Windows 桌面上的 **`Ext4-Mounter`** 快捷方式。

### 方式 2：双击启动脚本
在项目根目录下双击：
- **`start_ext4_mounter.bat`**：常规静默启动（推荐日常使用，无控制台黑框）。
- **`start_as_admin.bat`**：以管理员身份直接启动（物理磁盘挂载无需后续弹窗提权）。

### 方式 3：命令行启动
在项目根目录下打开终端运行：
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
│   ├── create_desktop_shortcut.ps1 # 桌面快捷方式生成器
│   └── build_exe.bat        # 单文件独立 exe 打包脚本
├── tests/
│   ├── test_detector.py     # 磁盘侦测单元测试
│   └── test_mounter.py      # ext4 镜像挂载与卸载端到端测试
├── install_desktop_shortcut.bat # 一键安装桌面快捷方式脚本
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

---

## ❓ 常见问题与排查 (FAQ)

**Q1：双击桌面图标没有反应，或提示找不到 Python？**
- 请确认已安装 Python 3.8+ 并添加到了系统环境变量（PATH）。
- 在 PowerShell 中运行 `python --version`。如果未找到，可重新运行 Python 安装包，选择 **Modify** 并勾选 **"Add python.exe to PATH"**，随后重新运行 `install_desktop_shortcut.bat`。

**Q2：运行或挂载时提示 WSL 相关错误或找不到发行版？**
- 请以管理员身份打开 PowerShell 执行：
  ```powershell
  wsl --install
  ```
  安装 WSL 2 和默认 Ubuntu 发行版，并按提示重启电脑。

**Q3：挂载物理 SSD 为什么会弹出 Windows UAC 提示？**
- 访问底层物理磁盘设备（如 `\\.\PhysicalDrive1`）属于 Windows 操作系统的敏感权限操作。
- 本工具已内置自动提权模块，挂载时在 UAC 弹窗中点击“是”即可；或者也可以直接右键 `start_as_admin.bat` 选择“以管理员身份运行”。

**Q4：挂载镜像文件 (.img / .vhdx) 是否需要管理员权限？**
- **不需要**。镜像文件挂载利用了 WSL2 用户态 loopback 设备映射，普通用户权限即可直接挂载并在文件资源管理器中浏览与复制。

