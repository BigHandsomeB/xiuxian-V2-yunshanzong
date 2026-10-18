# 法宝：玩法与副本扩展入口

状态：当前main已实现；手机实机和长期经济平衡待验。内容版本 `sect-artifacts-v1-6.3.0-r1`。

## 玩家入口与首批内容

主页面：**炼器阁 → 法宝**。统一查看配方/来源、炼制进度、装备/卸下、投喂、升级和强化。战斗画面在主角左上方展示装备中的法宝，动作使用场景共用RAF，不结算数值。

| 法宝 | 核心来源 | 炼制时间 | 独特效果 |
| --- | --- | --- | --- |
| 斩妖飞剑 | 荆棘古道·山魈王獠牙 | 2小时 | 每3回合飞剑追击 |
| 镇岳鼎 | 赤铜废矿·镇矿傀心 | 4小时 | 每6回合提供3回合护盾 |
| 噬魂幡 | 雾隐灵泽·泽蛟灵珠 | 6小时 | 击败敌人后回复生命 |
| 寒魄印 | 寒玉冰窟·玄冰龙髓 | 8小时 | 周期冰伤与迟缓 |
| 赤焰葫 | 离火丹墟·丹墟炉心 | 12小时 | 周期火伤与持续灼烧 |

显示名称以游戏Registry为准；上表用于定位。首批以现有Boss材料落地，寒魄印替代初稿未有对应来源的雷鸣印。

每种法宝只炼制一件，同时装备一件。打通对应副本100层且拥有炼器阁后可开工；单独一个法宝炼制位置，不占普通装备的瞬时打造入口。配方一次扣料、时间固定、不随弟子人数缩短，必定成功；开工后不可取消。世界暂停冻结，离线使用同一结算机制，完成自动入藏，无需额外领取。法宝属于个人收藏，不占普通材料仓容，不出售或自动分解。

等级上限20，经验阈值为 `100 × L × (L−1) / 2`；装备并参与战斗的法宝随已领取击杀奖励获得普通/精英/Boss经验2/10/50。未装备不获得刷怪经验；领奖、重放、刷新不能重复发放。投喂材料与每个材料的经验值由目录声明；到满级只扣最少整件材料，满级不消耗。

强化上限+10，每级增加基础属性10%；强化消耗炼器精华与灵钱，+5起还消耗对应Boss核心。等级提升招牌效果，强化提升基础属性。战斗、待领奖或挂机中禁止更换、投喂与强化，开战冻结等级/强化/效果来源；培养不会改写旧战斗快照。材料保留量在服务端保护，正在炼制的配方输入已扣除，不会被再次投喂。

具体配方、属性和效果数值以[唯一目录](../../src/data/artifacts/catalog.json)为准，本版为首批可调基线，不表示已完成长期平衡。

## 新副本更新：从这里开始

1. 按现有副本流程更新[副本目录](../../src/data/dungeons/catalog.py)、副本JSON与[内容清单](../../src/data/content_manifest.json)，登记真实Boss和Boss专属材料。
2. 在[法宝目录](../../src/data/artifacts/catalog.json)的 `artifacts` 增加稳定法宝ID，填写 `source_dungeon_id`、`source_boss_id`、`core_material_id`、`recipe_id`、`inputs`、`duration_ms`、`unlock_floor`、`min_forge_level`、`effect_id`、`motion_profile_id`、`base_stats`、名称和显示字形。
3. 使用已有 `effect_id` / `motion_profile_id` 即可复用行为；在 `feed` 添加新掉落材料及经验值。共用 `growth` / `enhancement` 控制首批成长与强化基线。不得根据中文名称猜测绑定。
4. 新效果若能由已有操作组合，在 `effects` 新增稳定效果ID和规则即可；现有支持战斗开始、回合推进、攻击/命中、击杀等触发。新增操作才扩展[规则校验](../../src/data/combat/mechanics.py)与[受控解释器](../../src/systems/combat/mechanics.py)。`mul`按万分比相乘，普通整数等级系数应先乘10000，不能直接套普通乘法。
5. 动作有 `strike`、`spin`、`absorb`、`pulse`、`pour`；新增动作扩展[场景渲染器](../../src/ui/pages/game/static/battle/renderer.js)的 `artifactFrame`，并更新[目录校验](../../src/data/artifacts/definitions.py)的 `MOTIONS`。正式外观通过`src/rendering/game-assets.json`的`artifact_icons`按法宝ID绑定已发布素材；加载失败回退字形，新增法宝仍须显式绑定。
6. 页面按服务端目录生成，**不用逐件修改炼器阁页面或战斗中的法宝ID判断**。校验实际副本Boss、Boss材料、配方资源引用、唯一配方ID、未知效果/动作和参数范围；补扩展、旧档及在线离线测试，然后按现有内容版本流程发布。

目录在启动时纳入Registry并seal；运行中的输入变化会拒绝加载，需要新进程，无热加载或任意代码插件。

## 真实接口与所有权

| 入口 | 职责 |
| --- | --- |
| `src/data/artifacts/definitions.py` | `settings` / `definition` / `register`；集中校验与Registry装配 |
| `src/systems/artifacts/artifacts.py` | 收藏状态、等级/属性、开战快照、击杀经验和炼制事件 |
| `src/application/artifacts.py` | 命令候选、保留量保护、配方门槛及只读页面投影 |
| `src/application/ecology.py` | 复用SQLite事务、回执和现有命令链 |
| `src/application/ecology_settlement.py` | 将法宝事件注入现有结算引擎，不建立新时钟 |
| `src/application/economy.py` | 唯一战利品结算链同时发放法宝经验 |
| `src/systems/combat/battle.py` | 手动、自动及压缩开战都冻结同一法宝快照 |
| `src/ui/pages/game/static/screens/artifacts.js` | 炼器阁法宝页面，只发送意图 |
| `src/application/artifact_upgrade.py` | 显式存档升级；保留原域/时钟/身份/装备/战况，只增加空法宝域 |

所有公开操作复用 `/api/command` 的登录、CSRF、generation/revision及request_id协议：

| 命令 | payload |
| --- | --- |
| `artifact_craft` | `{artifact_id}` |
| `artifact_equip` | `{artifact_id}` |
| `artifact_unequip` | `{}` |
| `artifact_feed` | `{artifact_id, resource_id, quantity}`，1～10000整件 |
| `artifact_enhance` | `{artifact_id}` |

读取 `view.artifacts`；战斗表现读取 `view.combat.artifact`，实际效果使用已提交的战斗事件。不会通过动画结束、GET或轮询重发资源。

