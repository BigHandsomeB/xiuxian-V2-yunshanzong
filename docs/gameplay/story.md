# 剧情接口与后续更新

当前为五章＋独立筑基36节点，无奖励、配方或数值修改；非阻塞待阅读列表与回看。正文唯一来源为[stage1.json](../../assets/story/stage1.json)，[第一阶段备忘录](../design/story-stage1.md)包含作者背景和对应文本。

## 三层接口

- Data：[definitions.py](../../src/data/story/definitions.py)读取assets/story/catalog.json登记的本地JSON包，检查章节/节点ID唯一、排序、对白与条件字段。剧情目录独立于数值Registry源清单，不修改content_version。服务进程启动后首次读取缓存，发布文本后重启原游戏服务。
- Domain：[story.py](../../src/systems/sect/story.py)管理条件处理器、持久已触发ID、阅读顺序与只读投影。story位于sect_management的可选字段，格式`{unlocked: [node_id], read: [node_id]}`；缺省空，不做GET/启动迁移。已触发ID只增不减。
- Application：[story.py](../../src/application/story.py)处理`story_read`，通过既有`/game/api/command`协议、版本1、payload `{node_id}`提交；复用存档generation/revision CAS、Receipt幂等与同一SQLite事务。允许世界暂停/自动战斗中标记，pending期间拒绝；不调用wake/settle、不修改游戏域或世界时间。

## 条件与新增节点

每个节点具有固定`id`、`chapter`、整数`order`、`title`、`track`、`condition`、`lines`。对白行为`{speaker,text}`，仅纯文本呈现，不执行HTML或代码。track为main（顺序主线）、side（独立经营插曲）、independent（独立筑基记事）。

现有条件：

| kind | 字段 | 实际证据 |
| --- | --- | --- |
| always | 无 | 序章可读 |
| selected | dungeon_id | 当前选择/曾记录的选择/该区域已通关或进入 |
| entered | dungeon_id | 真实战斗 encounter 或已保存区域通关进度 |
| floor | dungeon_id, minimum | 各自区域的最高已通关层数 |
| building_level | building_kind, minimum | 实际建筑等级；弟子居最低2级 |
| realm | minimum | 已保存境界序号；筑基及以后可补看 |
| event | event_id | 实际生产交付事件；wood_harvest在木材产物成功入库时记录 |

新增第六章通常只需：在assets/story增加stage2.json，登记catalog.json，使用不重复的章节/节点ID与现有条件。已有包结构为`{schema_version:1,release,chapters,nodes}`，release为可读版本标记；扩展现有章节时新包的chapters可为空。修改现有文字保留ID，不得挪用ID表达另一件事。

新增条件类别时，同时扩展Data的CONDITION_FIELDS与Domain的CONDITION_HANDLERS；条件必须纯读游戏事实。新瞬时事件由真实事务候选中的observer记录，再补充check_story和测试，禁止从GET或前端伪造触发事实。

## 兼容、阅读与顺序

- 旧档按现有最高层数/当前战况/境界/建筑等级纯读补看，不重放战斗、不发物品、不恢复旧队列、不改装备。首次真实操作才保存剧情账本。
- 无历史证据不能从库存木材推断“曾采集”，木材生活片段等下一次真实生产入库；经营插曲独立，不阻塞33段主线。独立筑基节点不绑任何章节。
- 主线按目录顺序阅读。服务端只返回当前可读节点和已读节点正文，其他节点仅标题/状态，拒绝跳读。已读可回看，单纯打开/回看不自动提交。
- 50层/章末“返回宗门”段落按通关事实进入队列，以回顾场景呈现，不强制玩家在指定层数停下或切页；不会追溯假装发生过一次浏览器路由事件。旧档、离线连续通关可依次补看。
- 选择/实际战斗的短暂事实在其原事务记录；自动战斗/离线通过原结算wake观察。生产交付在成功入库后记录，不因开工、材料购买或仅有库存提前触发。
- 未知旧ID保留，避免临时下架/重新发布使已读丢失；目录中不再存在的节点不会显示。新节点按当前事实可补看。追加到已读章节的新主线可形成新的待阅读节点，旧已读仍可回看。
- 冒险地图的副本列表最底部提供“主线记录”按钮，专用页面沿用原五主导航及计时调度；没有弹窗/新轮询器/强制导航。阅读页继续现有自动战斗、生产结算轮询；世界暂停仍停止。

## 更新与验证入口

项目根执行：

```sh
.venv/bin/python -B -m tools.playable.check_story
.venv/bin/python -B -m unittest tests.test_story -q
.venv/bin/python -B -m tests.story_ui_fixture
```

最后一条产生真实隔离模型与原生JS模块图，由既有V8工具执行story_ui_test.js；不是浏览器绘制验收。验证后备份当前存档及SQLite，重启原xianxia-v2-play，核验受保护view、相关静态脚本与完整存档摘要。新文本无须进行存档迁移或发放物品。
