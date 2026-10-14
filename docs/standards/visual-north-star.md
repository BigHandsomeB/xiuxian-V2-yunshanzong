# Xianxia V2 — Visual North Star

Status: LOCKED · Phase 13 user revision · 2026-10-07
Authority: current explicit user instruction replaces the Phase7.5 daily-scene direction. [Decision](../decisions/MOBILE_GAME_FRAMEWORK_FIRST.md).

## Priorities and visual architecture

GAME FRAMEWORK FIRST / MOBILE BROWSER FIRST / ASSET LATER.

Daily management is ICON FIRST. Sect, production, inventory, alchemy, crafting, plants, beasts, disciples, cultivation, trade and materials use icons, portraits, quantities, progress, status, cards, lists and light feedback. The product must read as a Chinese cultivation sect game, with jade, stone, ink, copper, mountains and readable Chinese typography. It must not become a dashboard, ERP, HTML table collection or fifteen identical white buttons.

Battle is SCENE FIRST. Only combat, dungeons, bosses and battle within secret realms need complete scene rendering. Background / player / enemy / independent effect / combat HUD are separate layers. There is no fake victory, damage, reward or progression when the corresponding Domain is absent.

Daily interiors, indoor disciple movement, Work Points, interior Scene State swapping and daily production scene animation are retired from core gameplay. Existing approved interiors, Master, Scene States and all asset history remain intact for illustrations, unlock images, events, backgrounds or special displays. Existing art is not implicitly reapproved or deleted.

## Mobile product structure

Portrait mobile Safari is primary. Shared shell: lightweight status header, content, exactly five bottom navigation entries, shared Drawer/Bottom Sheet, Loading/Empty/Error/Offline/Reconnecting states. Primary tabs are 宗门、弟子、修炼、仓库、冒险. Settings/help/game information live in the upper-right entry. Default entry is 宗门. Navigation, return and refresh preserve authoritative jobs/state.

Sect uses vertically grouped regions with distinct lightweight tones, building icons/thumbnails, names, real status and clickable entries. Main entries: 山门、宗务殿、弟子居、灵膳房、灵植园、御兽苑、灵渊、后山、丹鼎阁、炼器阁、百工坊、营造司、万宝库、万宝楼、问道峰. 秘境塔 belongs to Adventure. Unimplemented features explicitly show 尚未开放; entries never fabricate fifteen systems.

Building Management View is shared. Building-specific adapters provide current level, state, resources, production, recipe icons, progress and commands. Danding connects the existing Phase12 single凝气丹 recipe; requirements/duration/yield/progress are all read-model facts. Feedback is a furnace icon/progress/light CSS, not an interior scene.

Inventory is a mobile backpack icon grid, with 全部/资源/药材/丹药/装备/其他 filters, quantity, quality, locked/disabled/selected/unobtained appearance and item-detail Bottom Sheet. Only real positive holdings appear as possessed items. Icon component state support does not create locked item facts or unknown resources.

Disciples show actual available identity/group and assignment information. Individual names, realms, stats and growth cannot be invented from a workforce cohort. Detail reserves portrait, attributes, realm, cultivation, equipment, techniques, assignment and status; unavailable modules are labeled or hidden. Cultivation and Adventure reserve future structure without simulated earnings.

## Asset and rendering boundaries

All formal art is made through the existing Asset Manager. Asset ID → Runtime Manifest → Game Renderer. Source names, Catalog database and online Asset Manager are not game runtime dependencies. Registry bindings choose identity; reloading Manifest picks up subsequent approved publication of that identity. Newly created unbound identities must be registered in the game presentation binding map, not inferred from Source filenames.

Every art slot has a fallback: resource, pill, character, building, player, enemy and battle background. Missing/corrupt/unavailable art never blocks screens. No asset size/profile debate or pipeline restructuring in this phase. Approved PNG dimensions and hash/path guards remain authoritative. Pixel sampling and crop isolation follow [Pixel Runtime](pixel-runtime.md).

Battle supports explicit sheet metadata, action, frame count/duration, loop, anchor, position, facing, integer scale, effect trigger points and z order. Independent published frame images also work without guessed grids. Programmatic X/Y movement is separate from reusable Run frames. Animation is read-only presentation, never a time, damage or reward authority.

The protagonist has highest combat visual priority. Future independent player_combat_v1 supports idle4, move6, combo8–10, heavy6, skill8, ultimate10–12, dodge4, hit3, death6. Generic character_compact is not the final protagonist combat specification. New monsters and elites use one static full-body image at128×128; new Boss images use256×256. Independent monster collections share one sheet, then automatic geometry localization and explicit preview confirmation create one asset per name. They do not require action frames. Future displacement, hit shake/flash and exit fading belong to the presentation layer; gameplay remains the damage authority. Historical monster_compact and boss_v1 animations and frozen versions remain compatible. This current user-directed production policy supersedes the earlier enemy animation target. Sword trails, slashes, fire, lightning, impacts, hit feedback and spiritual energy are separate Effect Assets.

## Authority, performance and acceptance

Existing Inventory/Building/Assignment/Alchemy use true Application/Domain. Foundation defaults to no changes; any necessity requires STOP and explanation. Phase11.5/TASK13 stay archived; Phase12 gains no recipes; no auto-advance to Phase14.

UI receives committed read models, sends versioned HTTP intents and explicitly requests settlement. It never deducts inputs, delivers pills, completes jobs, upgrades or grants resources locally. Pending HTTP identity can be retained for safe replay, but there is no second client save. GET remains pure.

Use existing Flask/HTML/CSS/ES Modules/native JS, no new frontend engine/framework/build dependencies. Pause hidden polling and offscreen visual RAF; Simulation correctness belongs to existing Settlement. Keep gameplay, presentation and asset-development tools independent.

Implementation runs the complete screen sequence before polish. Tests verify navigation, real Domain wiring, asset resolution/fallback, unavailable feature nonmutation and restart/refresh. Real iPhone/Safari rendering and touch acceptance must be reported separately from HTTP and DOM harness checks. No invented phone pass.

Phase14 separately authorized2026-10-07: Minimal real Combat now uses the established five-layer Battle Scene and semantic event presentation. Daily ICON FIRST remains unchanged. Actual iPhone Safari fallback combat layout accepted; no formal-art quality claim or player template expansion. Phase15 separately authorized2026-10-07; real Cultivation upgrades existing ICON FIRST screen only. No new Scene/Pipeline/templates; actual phone breakthrough acceptance remains pending real resources.
