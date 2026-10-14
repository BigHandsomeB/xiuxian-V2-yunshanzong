<div align="center">

# 云山宗 · 修仙 V2

**从一座山门开始，经营宗门、修习功法，走向更深的秘境。**

手机竖屏 · 宗门经营 · 自动战斗 · 像素修仙

[游戏预览](#游戏预览) · [世界概况](#世界概况) · [已实现功能](#已实现功能) · [本地运行](#本地运行) · [后续开发计划](#后续开发计划) · [版本历史](#版本历史)

</div>

云山宗是一款持续开发中的修仙宗门经营网页游戏。日常以资源、建筑和弟子岗位管理为主，冒险以独立场景中的单主角回合战斗为主。每一次炼丹、生产、掉落和突破，都连接同一份服务器存档。

本仓库为 **2026-10-14 的完整游戏发布快照**：包含当前游戏代码、数据定义、测试，以及游戏和万宝图鉴正在引用的正式素材。内容标识为 `sect-ecology-v1-6.3.0-r1`，包含后续功法、委托和显示改动；尚未创建语义版本 Tag。

## 游戏预览

以下为游戏已接入的实际场景与角色素材，**不是游戏界面截图**。仓库不公开生产服务地址；本地启动后可直接体验完整页面。

### 荆棘古道

<img src="assets/runtime/scene.environment.af52d052e0c12.scene/v1/75247be10a474cec89f5929e30609553.png" alt="荆棘古道实际战斗背景" width="640">

### 赤铜废矿

<img src="assets/runtime/scene.environment.a3a1936f6defb/v1/1920ec1e6850478fafa608b85f53fe0b.png" alt="赤铜废矿实际战斗背景" width="640">

### 雾隐灵泽

<img src="assets/runtime/scene.environment.a43022fdd6f21.scene/v1/716f37f90307495b9c6b7c950adeb818.png" alt="雾隐灵泽实际战斗背景" width="640">

### 寒玉冰窟

<img src="assets/runtime/scene.environment.aff66a63c8f71/v1/a5f8b3265403406fb0eb13d977c908ea.png" alt="寒玉冰窟实际战斗背景" width="640">

<table>
<tr><th>主角</th><th>荆棘山魈王</th><th>宗门资源</th><th>装备成长</th></tr>
<tr>
<td align="center"><img src="assets/runtime/character.af8b2d2ce9282.idle/v1/17fb2cd067a047c28a9a9ceb7f1216bb.png" alt="主角正式素材" width="120"></td>
<td align="center"><img src="assets/runtime/boss.static.a75d4fa9e16f8/v1/aeac3da8d1bb42588a7372d4fa567b65.png" alt="荆棘山魈王正式素材" width="150"></td>
<td align="center"><img src="assets/runtime/icon.resource.a86878b93e958/v1/069d5f662b84475e98bc7ed396576468.png" alt="灵草" width="72"><img src="assets/runtime/icon.pill.a05aa9179e82c/v1/0a0fd5b8e53e45e19120d32f24030548.png" alt="凝气丹" width="72"></td>
<td align="center"><img src="assets/runtime/icon.equipment.a80eec5dd9690/v1/9a613382874f4c4cb3488b543097d185.png" alt="山魈王骨刃" width="72"><img src="assets/runtime/icon.equipment.ac105eb3f8bfa/v1/5fe3cec8f96d4dbabb8bc78d777c788f.png" alt="荆王战甲" width="72"></td>
</tr>
</table>

## 世界概况

故事以云山宗为中心展开：山门内是药园、矿洞、丹鼎与炼器设施，山门外则是妖兽盘踞、材料与机缘并存的秘境。玩家安排弟子生产，构建灵植、养殖、灵膳与修炼之间的供给循环，逐步强化主角并推进副本。

- **当前可玩副本**：荆棘古道、赤铜废矿、雾隐灵泽、寒玉冰窟，各 100 层。普通怪、精英与终层 Boss 分层出现，后续副本按前置通关解锁。
- **当前开放境界**：炼气与筑基，共 1–1000 级。金丹、元婴、化神、炼虚及总计 3000 级为配置预留，并未全部开放。
- **远景秘境**：离火丹墟、玄雷剑冢、地脉古城、太阴幽府、星陨天宫、玄黄封仙台仍属于未开放内容。
- **核心循环**：岗位与供给 → 采集与生产 → 丹药与修炼 → 副本与掉落 → 装备、功法与宗门成长。

## 已实现功能

| 系统 | 当前能力 |
| --- | --- |
| 手机游戏界面 | 宗门、弟子、修炼、仓库、冒险五个主页面；浅色、深色与系统主题；详情弹窗与设置 |
| 宗门经营 | 建筑升级、住房与人口约束、招募、弟子岗位分配、仓容与供膳管理 |
| 生产与炼丹 | 采集、材料加工、丹药与装备制作；自动生产目标、资源保留量和消耗限制 |
| 灵植与养殖 | 四建筑生态玩法；17 种灵植、24 种养殖对象、27 种灵膳及对应饲料、加工和设施配置 |
| 修炼成长 | 击杀修为、等级属性成长、丹药修炼、里程碑与条件突破；已开放炼气、筑基 |
| 四大副本 | 共 400 层内容，独立进度与掉落；手动挑战、自动推层、定层回刷和首通奖励 |
| 战斗 | 回合计算、命中与暴击、护甲和破甲、闪避、毒抗与反伤；场景、角色与特效分层表现 |
| 装备 | 六槽装备、持久保存的随机属性、穿脱比较、强化、锁定/收藏、出售与分解、整包处理 |
| 功法 | 150 部正式功法目录，内功及分类槽位、装备与击杀成长、灵石购买和功法来源 |
| 宗门活动 | 每日委托、贡献兑换、累计声望、四副本首次 Boss 奖励的三选一定向宝箱 |
| 商店与图鉴 | 每日商店、物品详情、万宝图鉴及独立的说明编辑 |
| 时间与存档 | 世界暂停/继续、离线续算与收益报告、持久化存档、备份与恢复接口、请求重放保护 |
| 开发工具 | 素材集合、提示词、上传与裁切、人工审核、Runtime 发布；经济检查和原生 UI 测试 |

**当前边界**：弟子独立战斗与完整个体养成、后续境界、后六个副本、功法打坐/演武等预留入口尚未开放。部分最新功能仍待真实手机验收及长期经济平衡验证；代码检查不等于已完成这些验收。

## 本地运行

需要 Python 3.11 或更新版本。请在项目根目录执行：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

# 显式创建当前内容的新档；已有存档时拒绝覆盖
.venv/bin/python -B -m tools.playable.setup_local

# 口令只存在于本机环境中
export ASSET_MANAGER_TOKEN="$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export GAME_LOCAL_HTTP=1
.venv/bin/python -B -m tools.playable.server
```

打开 **http://127.0.0.1:8000/game/**，使用本机环境中的 `ASSET_MANAGER_TOKEN` 登录。新档使用当前完整内容配置，后续重启不重复初始化。运行数据生成于 `.game/`，已纳入 Git 忽略规则。

`GAME_LOCAL_HTTP=1` 仅用于本地 HTTP 开发。HTTPS 部署时移除该变量，通过 `GAME_ALLOWED_HOSTS` 配置可信主机名，并让可信反向代理覆盖 `X-Forwarded-Proto`。游戏监听回环地址；生产口令、代理配置与服务器地址需要自行设置。

素材管理器可另行运行：

```sh
.venv/bin/python -B -m tools.asset_manager
```

访问 http://127.0.0.1:8001。它会建立自己的空元数据库，**不含原项目的素材制作历史**。游戏运行读取正式 Manifest 和小型公开图鉴索引，无须先启动素材管理器。图鉴索引只保存展示所需的名称、分类和顺序，不包含制作数据库或历史。

## 项目结构

```text
src/
  core/           时间、存档、事务与基础验证
  application/    玩法命令、查询与系统组合
  systems/        宗门、战斗、修炼、生产等规则
  data/           物品、配方、副本与功法定义
  transport/      Flask HTTP 与存档接口
  rendering/      正式素材绑定与表现投影
  ui/             原生 HTML / CSS / JavaScript 手机界面
assets/
  runtime/        当前发布并被游戏使用的成品素材
  manifest.json   素材路径、版本、尺寸与校验值
  templates/      素材制作规格配置
  registry/       公开图鉴索引与空初始化配置
tools/            启动、素材开发与经济工具
tests/            隔离测试
balance/          战斗与经济基线
docs/             技术规则与发布说明
```

`tools/playable/` 提供游戏启动与升级工具，`tools/asset_manager/` 提供素材开发工具，`tools/economy/` 和 `balance/` 提供数值检查，`tests/` 保存 Python 和原生 JavaScript 测试。

技术栈：**Python · Flask · SQLite · Pillow · 原生 JavaScript**。日常经营采用图标与数量，战斗采用场景与角色；游戏数值以服务器 SQLite 事务为权威。

## 验证

```sh
.venv/bin/python -B -m unittest tests.systems.test_sect_activities tests.transport.test_sect_activities
.venv/bin/python -B -m unittest tests.systems.test_formal_techniques tests.systems.test_level_cultivation
```

全量 Python 测试入口为 `python -B -m unittest discover -s tests`。原生 JavaScript 测试在 `tests/*_test.js` 中，需要相应 JavaScript 运行环境；受限服务器优先分模块串行验证。

本次发布检查与资源边界见 [发布说明](docs/project/RELEASE.md)。手机视觉、长期平衡与测试统计按实际验证范围记录。

## 后续开发计划

先巩固四副本、生态经济、存档与手机体验，再按依赖逐步扩展：

| 方向 | 规划内容 |
| --- | --- |
| 后六副本 | 离火丹墟 → 玄雷剑冢 → 地脉古城 → 太阴幽府 → 星陨天宫 → 玄黄封仙台；内容与解锁待设计 |
| 后续境界 | 金丹、元婴、化神、炼虚；现有 3000 级预留配置需逐步补齐并验证 |
| 功法培养 | 打坐与演武、资源和时间约束、成长节奏 |
| 弟子与宗门 | 个体养成、境界与独立战斗；继续完善经营与冒险的资源闭环 |
| 生产与装备 | 后续批次配方、孵化、精炼、符文方案 |
| 交付质量 | 长期数值平衡、实际手机验收、旧档兼容、真实界面截图与版本化更新 |

以上为规划，尚未全部实现或开放，也没有承诺具体上线日期。详细边界与交付顺序见 [ROADMAP.md](ROADMAP.md)。

## 版本历史

| 日期 | 主要更新 |
| --- | --- |
| 2026-10-14 | 宗门每日委托、贡献与声望、Boss 定向宝箱；修复活动客户端命令；属性整数显示；首次完整游戏 GitHub 快照 |
| 2026-10-13 | 四建筑生态与灵膳、击杀修为及等级成长、150 部正式功法、万宝图鉴说明编辑 |
| 2026-10-12 | 寒玉冰窟、离线续算优化、战斗效果与追赶提示、灵泉灌溉、招募与配方界面完善 |
| 2026-10-11 | 宗门经营扩展、存档备份与客户端恢复、离线收益报告；副本内容持续完善 |
| 2026-10-10 | 六槽随机装备、荆棘古道掉落与怪物强度规则、副本图标、只读 UI 预览 |
| 2026-10-08–09 | 宗门经济与自动生产、世界暂停、主题和资源图标、战斗表现与素材流程完善 |
| 2026-10-06–07 | 完整手机游戏外壳、最小真实战斗、炼丹与修炼闭环 |
| 2026-10-03–05 | V2 时间与存档基础、玩法边界、资源和建筑基础、素材管理工具 |

详细历史见 [CHANGELOG.md](CHANGELOG.md)。历史条目整理自本地提交与实施记录；仓库从本次快照开始保留 Git 更新历史，不携带原工作区中的私密历史。
