# 团子的一键部署

LUNA ZHOU · 2026-11-06 · 版本 1.0.0。

## Windows：直接使用免安装包

1. 将 `release/Tuanzi-1.0.0-windows-x64.zip` 复制到另一台 Windows 10/11 64 位电脑，完整解压。
2. 双击文件夹里的 `Tuanzi.exe` 或 `一键启动.cmd`。运行环境、Qt 和动作素材已包含，无需安装 Python，无需联网，无需管理员权限。
3. 可双击 `创建桌面快捷方式.cmd` 创建启动图标。搬动程序时保留整个文件夹。

配置、日志及应用自身的渲染预览保存在 `%LOCALAPPDATA%/TuanziPet/`；升级程序不覆盖这些文件。

## macOS：首次一键部署，之后双击应用

1. 将 `release/Tuanzi-1.0.0-macos-one-click.zip` 复制到 Mac，完整解压。
2. 双击 `Tuanzi-Mac-Setup/deploy-macos.command`。
3. 脚本自动识别 Apple Silicon / Intel，联网准备 Python 和固定版本的构建依赖，在 Mac 本机构建、校验并安装 `~/Applications/Tuanzi.app`，随后启动。无需提前安装 Python、Homebrew 或完整 Xcode。若缺少 Apple 命令行工具，会打开系统官方安装界面，完成安装后脚本自动继续；这一步可能需要系统授权。
4. 以后在用户的“应用程序”中双击团子即可，日常运行无需联网。

最低系统为 **macOS 14**，由当前 PySide6 6.12 的 macOS wheel 决定。首次部署需要访问 PyPI 和 Python 运行环境下载源，时间取决于网络。启动脚本从官方 PyPI 下载 uv 0.13.7，并在执行前核对固定 SHA-256；不会更改系统 Python 或全局 PATH。首次打开下载的未签名启动脚本时，请按 macOS 的正常“右键 → 打开”流程确认；脚本不移除隔离属性，也不关闭 Gatekeeper。

配置和日志保存在 `~/Library/Application Support/TuanziPet/`。重新部署时，旧应用保留为 `~/Applications/Tuanzi-Previous-时间.app`，用户数据保持独立。构建后会先运行真实 `.app` 的自检，再安装。

## 在开发机重新打包

- Windows：双击 `build-windows.cmd`；构建机需要 Python 3.10+，接收免安装包的电脑不需要 Python。
- macOS：上面的一键部署脚本会完成本机打包；已有构建环境也可运行 `python scripts/build_release.py`。
- 仅导出部署源码包：`python scripts/build_release.py --source-only`。
- 原生构建完成后运行 `python scripts/verify_release.py`，验证启动、睡姿、暂停、单实例唤回和退出。

产物集中在 `release/`，附 `SHA256SUMS.txt`、构建信息和实际可执行文件输出的 `*-self-check.json`。Windows ZIP 为一个完整文件夹；macOS 原生 ZIP 保留 `.app` 框架的符号链接。

## 可选的云端一键构建

项目已带 `.github/workflows/build-desktop.yml`。在 [TUANZI 的 Actions 页面](https://github.com/zhouluna/TUANZI/actions/workflows/build-desktop.yml)进入 **Build desktop packages → Run workflow**，会在 Windows、Apple Silicon Mac、Intel Mac 三种原生构建机上生成对应安装包并运行验证。工作流只上传构建产物，不自动发布 Release。现有版本的下载包见 [Releases](https://github.com/zhouluna/TUANZI/releases)。

当前 Windows 环境能产出并验证 Windows 可执行程序；macOS 的 `.app` 必须由 Mac 或上述 macOS 构建机生成。本地提供的是自动完成这一过程的 Mac 部署包，不能把它误认成已在 Mac 上运行验证过的二进制。

## 运行资源与校验

打包仅收录当前程序实际引用的形象、11 组动作、蝴蝶和 4 种睡姿。每个文件在 `runtime-assets.json` 中有 SHA-256；`Tuanzi.exe --self-check --report 路径.json` 可检查捆绑的 Qt 和资源完整性。源码导出采用明确的文件清单，排除 `.local`、个人设置、日志、虚拟环境、旧项目、预览原稿和 `node_modules`。服装仍是供选择的设计预览，未加入当前程序。

资源依据：[PyInstaller 运行时路径](https://pyinstaller.org/en/stable/runtime-information.html)、[原生构建限制](https://pyinstaller.org/en/stable/)、[Qt 用户数据目录](https://doc.qt.io/qt-6/qstandardpaths.html)、[uv 管理 Python](https://docs.astral.sh/uv/guides/install-python/)、[GitHub 原生构建机](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)。
