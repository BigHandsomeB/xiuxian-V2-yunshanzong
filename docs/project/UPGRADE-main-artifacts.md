# 已有存档升级至当前 main 法宝版本

新玩家按README初始化当前新档。已有存档不要再次运行setup_local。升级前停止自己的游戏进程，备份整个`.game/`、自己的环境配置和旧代码，备份不要上传GitHub。

当前目标为`sect-artifacts-v1-6.3.0-r1`。请在项目根目录操作；示例使用已有`.venv`。

1. 用原版本完成待处理离线续算，停止服务。只读预检：

```sh
.venv/bin/python -B -m tools.playable.combat_effect_upgrade
```

来自v0.2.0的版本通常为`sect-effects-v1-6.3.0-r1`；更早v0.1.0为`sect-ecology-v1-6.3.0-r1`。必须pending=False。不符合时先回原代码完成续算，不跳过校验。

2. 如果仍是以上旧版本，升级功法时序（已是`sect-skills-v2-6.3.0-r1`则跳过）：

```sh
.venv/bin/python -B -m tools.playable.combat_effect_upgrade --apply
```

3. 从功法版本升级法宝：

```sh
.venv/bin/python -B -m tools.playable.artifact_upgrade
.venv/bin/python -B -m tools.playable.artifact_upgrade --apply
```

两步工具分别先生成权限600的JSON和SQLite完整备份，并输出备份路径，再通过原事务/回执升级内容版本。自行安全保存备份。法宝升级只增加空法宝收藏，不发放成品或资源；装备属性、原有数据分区、身份、时间和当前战斗完整保留。原战斗按原快照继续，新战斗采用秒制技能冷却。已到目标版本不用重复升级。

4. 恢复自己的游戏服务并刷新，进入炼器阁→法宝。实际炼制由玩家支付配方并等待完成。

回退需要先停止游戏、恢复升级前整份存档及对应旧代码；不能只覆盖旧代码。恢复会丢失备份后的进度。不要在运行中的数据库上覆盖备份。更早未知版本和不同玩家存档合并不属于此流程。
