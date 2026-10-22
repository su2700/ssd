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
   - `.img/.ext4/.raw` 通过 WSL2 loopback 挂载，无需 Windows 管理员权限；`.vhd/.vhdx` 使用新版 WSL 的原生挂载功能，需要 UAC 授权。
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
8. **ROS2 / Docker / MCAP 数据权限一键专项修复 (自动驾驶与机器人场景优化)**
   - 彻底解决 Windows 资源管理器显示「大小: 0 字节 / 0 个文件」问题（Docker/ROS2 以 root 用户或高限制权限录制导致的 Windows 访问受限）。
   - 智能识别录包目录（如 `mcap`、`rosbag`），递归配置读取与遍历权限（`chmod a+rX`）并应用 POSIX Default ACL 自动继承。
   - 智能适配安全只读模式：只读模式下修复完成后自动恢复 Linux 只读保护，确保原始采集数据不被篡改或损坏。

---

## 📦 环境准备与安装

### 1. 系统与前置环境要求

- **操作系统**：
  - Windows 10（版本 2004 及以上 / 内部版本 19041+，建议 22H2）或 Windows 11。
  - 应用使用同一套源码和启动入口支持两种系统；启动后会检查实际 WSL 功能，而非仅根据系统名称判断。
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
  - 上述命令只设置新发行版的默认版本。使用 `wsl -l -v` 检查现有发行版，必要时运行 `wsl --set-version Ubuntu 2`（替换为实际名称）。应用只选择 WSL 2 发行版。
  - **物理磁盘和 VHD 挂载**：Windows 10/11 均建议安装/更新 Microsoft Store 版 WSL。管理员 PowerShell 中运行 `wsl --update`，完成后点击界面“刷新磁盘”重新检测。物理磁盘自定义名称要求 `--mount`/`--name`；VHD 另需 `--vhd`。
  - 旧版 WSL 缺少物理挂载功能时，应用仍可挂载 WSL 2 原始镜像，并会禁用不支持的磁盘操作。格式化会在修改分区前重新检查兼容性。
  - 两种系统均使用 `\\wsl$\<发行版>\mnt\wsl\<挂载名>` 访问文件。磁盘查询兼容 Windows PowerShell 5.1；32 位 Python 会通过 Sysnative 调用系统工具。
  - 依据：[Microsoft WSL 安装说明](https://learn.microsoft.com/windows/wsl/install)、[磁盘挂载要求与限制](https://learn.microsoft.com/windows/wsl/wsl2-mount-disk)。WSL 的 USB/读卡器及正在使用的系统磁盘限制仍适用。
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
- 提示 `[OK] Ext4-Mounter shortcut created on your desktop.`。

至此安装已全部完成！后续无需再进入文件夹或打开终端，在桌面上双击即可一键打开应用。

#### 步骤三（可选）：打包为单文件独立可执行文件 (.exe)
如果您希望脱离 Python 解释器在其他 Windows 机器上直接免安装运行：
1. 双击运行 `scripts\build_exe.bat`。
2. 脚本会自动使用 PyInstaller 将应用打包为无黑框的单文件可执行程序。
3. 打包产物将生成在 `dist\Ext4-Mounter.exe`，直接双击该 exe 即可运行。
4. 构建脚本包含 Windows 10/11 兼容清单、DPI 和长路径声明。普通启动无需提权，仅磁盘操作请求 UAC。旧版 exe 需要重新构建才能包含兼容性修复。

#### 步骤四（可选）：运行自测验证
在项目根目录下的命令行中运行单元测试，验证所有磁盘探测与挂载模块正常工作：
```pwsh
python -m unittest discover -s tests
```
测试依赖本机 WSL 环境；无 WSL 的环境可运行 `python -m unittest discover -s tests -p test_shell_compat.py` 验证中英文终端兼容性。

Windows 10/11 功能矩阵和启动回归无需真实 WSL 或磁盘操作（启动测试需要 Tcl/Tk）：
```powershell
python -m unittest discover -s tests -p test_windows_compat.py -v
python -m unittest discover -s tests -p test_startup.py -v
```
这些测试模拟系统版本与 WSL 功能；发布前仍需在 Windows 10/11 真机或虚拟机上验证实际磁盘挂载。

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
磁盘与挂载集成测试需要已配置的 WSL2 发行版。终端兼容性回归测试不需要挂载或格式化磁盘。

---

## ❓ 常见问题与排查 (FAQ)

**中文 CMD / PowerShell 中出现乱码或“不是内部或外部命令”？**
- 更新后重新运行 `install_desktop_shortcut.bat`。批处理入口使用纯 ASCII 与 Windows CRLF 换行，无需修改系统语言或全局代码页；界面仍为中文。
- 在 PowerShell 中使用 `./install_desktop_shortcut.bat`、`./start_ext4_mounter.bat` 或 `./start_as_admin.bat`；在 CMD 中直接运行相同文件名。
- PowerShell 命令显式使用 UTF-8 输出，WSL 输出兼容 UTF-16LE、UTF-8 和本机中文编码。发行版检测不依赖英文表头或英文运行状态。
- 项目和用户目录支持中文及空格；如果提示找不到 Python，请安装 Python 并添加到 PATH 后重试，无需为安装快捷方式额外提权。

**Q1：双击桌面图标没有反应，或提示找不到 Python？**
- 应用会将启动错误、后台异常和磁盘探测失败写入 `%LOCALAPPDATA%\Ext4-Mounter\app.log`（单文件最大 1 MiB，保留 3 个历史文件）。若该目录不可写，则使用 `%TEMP%\Ext4-Mounter\app.log`。
- GUI 导入或 Tcl/Tk 初始化失败时会显示 Windows 原生错误对话框；WSL 不可用时窗口仍可打开，并显示依赖错误。物理磁盘操作仍在需要时请求 UAC 授权。
- 依赖/兼容性错误对话框会显示“问题、原因、解决方法、详细信息”和可用的日志路径，包括缺少 WSL、未安装发行版、WSL 1、新版 WSL 选项缺失、虚拟化未启用、权限/UAC、PowerShell/CIM 查询失败及 Linux 工具缺失。未知错误会明确说明原因尚未确定。
- 缺少 Python/Tcl/Tk 或 Python 版本不兼容时，启动脚本也会显示原生提示。修复依赖后按提示重启系统，再点击“刷新磁盘”重新检测；程序不会自动安装组件或更改系统设置。
- 启动回归测试不访问真实磁盘或 WSL：`python -m unittest discover -s tests -p test_startup.py -v`。测试会创建隐藏的 Tk 窗口，需要安装带 Tcl/Tk 的 Python。
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
- `.img/.ext4/.raw` 使用 WSL2 loopback，不需要 Windows 管理员权限；`.vhd/.vhdx` 使用 WSL 原生 VHD 挂载，需要支持 `--vhd` 的新版 WSL 和 UAC 管理员授权。

**Q5：为什么挂载后，Windows 资源管理器显示 ROS2 / mcap 文件夹属性为「大小: 0 字节 / 0 个文件」或无法访问？**
- 这是由于 Docker 容器或 ROS2 `ros2 bag record` 录包工具通常以 Linux `root` 用户运行并设置了严格的权限掩码（如 `0700` 或 `0750`）。
- Windows 资源管理器通过 WSL 网络共享服务（9P 协议）访问时使用的是 WSL 默认普通用户身份，无法遍历 `root` 专享目录，导致属性显示为 0 字节且无法查看子文件夹。
- **一键解决**：在小工具的已挂载列表中选中该挂载项，点击 **【🛠️ 修复 mcap 权限】**（或在挂载时保持勾选 **【⚡ 自动配置 777/可见权限】**），工具将自动递归配置读取与遍历权限（`chmod a+rX`）并应用 Default ACL 继承。修复后在 Windows 资源管理器中按 `F5` 刷新即可正常查看完整文件与大小！

