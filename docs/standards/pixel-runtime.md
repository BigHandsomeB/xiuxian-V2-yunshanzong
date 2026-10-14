# Pixel Runtime Contract

体验与视觉方向唯一依据：[Visual North Star](visual-north-star.md)；本文件保留各自技术规范。
Status: SCAFFOLD

素材生产的逻辑尺寸、透明Cell、间隔、锚点与Runtime默认规格已正式锁定在[唯一Template/Profile数据](../../assets/templates/templates.json)，由[共享规格模块](../../tools/asset_manager/specs.py)读取，WHY见[ASSET_PIXEL_PROFILE_V1](../decisions/ASSET_PIXEL_PROFILE_V1.md)。不在此复制尺寸表。下表仅保留未来具体游戏画幅/实际浏览器显示契约；素材规格不等同于页面占位、碰撞箱或显示缩放倍数。

| Contract | 尺寸/密度/显示比例 |
| --- | --- |
| BATTLE_PLAYER_RUNTIME | TBD |
| BATTLE_MONSTER_RUNTIME | TBD |
| BATTLE_BOSS_RUNTIME | TBD |
| SCENE_NPC_RUNTIME | TBD |
| SECT_NPC_RUNTIME | TBD |
| ITEM_ICON_RUNTIME | TBD |
| BUILDING_RUNTIME | TBD |

优先整数倍像素缩放，避免非整数模糊；使用正确image-rendering像素策略，具体CSS按渲染方式验证。
Sprite Sheet frame尺寸、裁帧区域必须严格匹配，禁止相邻帧泄漏；Runtime像素密度统一。
主角实际显示清晰度不得低于普通怪物。记录natural size、display size、frame size、缩放倍数与Manifest引用。
正式数值确定后建立Decision并做真实手机验收。Master/Runtime分离见assets标准。

物品导出升级见[ASSET_ITEM_ICON_PROFILE_V2](../decisions/ASSET_ITEM_ICON_PROFILE_V2.md)：仅游戏内容物品Profile改变，导航/HUD Profile不变；历史生成规格与当前导出规格独立追溯，尺寸数值仍只由上述Template数据读取。
