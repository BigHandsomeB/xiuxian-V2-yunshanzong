# Animation Standard

体验与视觉方向唯一依据：[Visual North Star](visual-north-star.md)；本文件保留各自技术规范。

慢节奏修仙增量经营；约120秒 = 游戏一天。

素材生产当前采用[Template中的精简动作权威](../../assets/templates/templates.json)与[LOW_FRAME_ANIMATION_PROFILE_V1](../decisions/LOW_FRAME_ANIMATION_PROFILE_V1.md)。下表保留为早期宽泛指导，不能覆盖正式Prompt/Sprite导入模板；完整Scene State不按动画帧解释。

| 动作 | 历史宽泛建议帧数 |
| --- | --- |
| Idle | 2～3 |
| 普通工作 | 约4 |
| 行走 | 约4 |
| 普通攻击 | 4～6 |
| 施法 | 4～6 |
| 受击 | 约2 |
| 死亡 | 3～4 |
| 特殊大型动作 | 必要时6～8 |

慢、稳、克制、允许停顿。禁止默认12帧高速动作或机械提高FPS；表现修仙世界缓慢运行。
帧时长、停顿、循环频率及特殊动作正式参数TBD。屏外视觉可暂停，但数值推进必须正确，见performance。

Simulation与Animation FPS彻底解耦：视觉后台/屏外/低FPS可暂停，数值按显式Settlement正确推进；动画结束不发奖或写Save。正式依据：[TIME_SETTLEMENT_MODEL](../decisions/TIME_SETTLEMENT_MODEL.md)、[Time Contract](../architecture/time-contract.md)。

Phase13 protagonist exception: higher-frame combat repertoire is authorized as a future player_combat_v1 template requirement; ordinary monster remains compact. [Current visual authority](visual-north-star.md) and [readiness](../gameplay/player-combat-readiness.md). No current Asset template/profile changes.

