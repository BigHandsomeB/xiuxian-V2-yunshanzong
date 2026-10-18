# Windows 独立桌面版 · v0.3.0

与网页／服务器版使用相同的法宝、功法和五副本内容，采用独立窗口与 Python 直接调用。游戏和素材工坊均不启动 HTTP 服务。

## 下载与首次启动

从 [Windows 独立发行版](https://github.com/BigHandsomeB/xiuxian-V2-yunshanzong/releases/tag/v0.3.0-windows) 下载 `YunshanZong-v0.3.0-Windows-x64.zip`。完整解压后双击 `YunshanZong.exe`，支持 Windows 10/11 x64，无需另装 Python。整个文件夹需要一起保留，不能只移动 EXE。请放在自己可写的普通目录。

首次启动只在完全没有存档时创建新档。进度保存在程序目录 `.game/`，关闭后保留。游戏设置里的「打开素材管理器」打开独立素材工坊窗口，也可运行 `素材工坊.cmd`。

Windows 源码包为 `YunshanZong-v0.3.0-Windows-source.zip`，需要 Python 3.11+；双击「启动云山宗.vbs」或 `start-desktop.cmd` 准备项目依赖并启动。

## 从旧 Windows 版升级

1. 关闭游戏和素材工坊，完整备份原来的 `.game/`、自制素材和管理数据库。
2. 将新版本解压到新目录，复制自己的 `.game/`。自制素材另按 Asset ID 和 Manifest 合并，不能用空制作数据库覆盖旧数据库。
3. 先用旧版完成待处理的离线续算。运行新目录的「升级存档.cmd」，显式完成旧内容 → 秒制功法 → 法宝迁移；不得重新初始化旧档。
4. 迁移保留旧装备、库存、身份、世界时间和原战斗，只增加空法宝收藏，不赠送法宝或材料。旧战斗沿用原快照，新规则在下一场生效。
5. 再双击 EXE。需要回退时恢复整份旧存档与对应旧程序，不能仅覆盖旧代码。

网页／服务器版的下载和部署仍见[项目主分支](https://github.com/BigHandsomeB/xiuxian-V2-yunshanzong)。两个发行版采用不同标签和下载文件名，存档不会随发行包上传。

## 本地体验

保留暂停时切换装备和功法、挂机中换装、图标缓存、逐帧时辰条及约每秒的本地状态同步。奖励、产物、存档版本和重复提交仍由 Python 校验。

## 从源码构建

在 Windows 上运行：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -m tools.release.build_windows --output .tmp/windows-release-v0.3.0 --version v0.3.0
```

打包工具只导出公开代码、配置和正式 Runtime，排除 `.game/`、制作数据库、原图、环境和口令。打包后执行 EXE 包完整性检查、游戏及素材工坊桌面验收，再生成两个 ZIP 与 `SHA256SUMS.txt`。构建使用 PyInstaller 的目录模式，见[官方使用说明](https://pyinstaller.org/en/stable/usage.html)。
