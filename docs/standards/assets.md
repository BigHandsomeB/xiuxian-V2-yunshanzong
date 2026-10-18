# Assets Standard

体验与视觉方向唯一依据：[Visual North Star](visual-north-star.md)；本文件保留各自技术规范。

MASTER != RUNTIME。Master是高质量源资产；Runtime针对最终游戏显示尺寸优化并实机验收。禁止大型Master由浏览器任意缩小直接当Runtime，手机实际清晰度优先。
Source/Master/Component/Runtime、Registry与Manifest的正式Schema/信任边界见[Asset Pipeline](asset-pipeline.md)。Manifest只存游戏可加载的Runtime引用；来源与Prompt关系保留在开发Catalog，不进入Game Manifest。
宗门总览与独立内景的构图/环境连续性按Visual North Star；不额外强制单张全景图。
人物Runtime与背景分离；完整Scene State可按锁定Master表现固定工作位的通用姿态，但不能将正式弟子身份/Assignment写死在背景。场景模板例外与Review见Asset Pipeline；不创建Gameplay映射。
大型Master和中间产物Git限制见 [git](git.md)。

