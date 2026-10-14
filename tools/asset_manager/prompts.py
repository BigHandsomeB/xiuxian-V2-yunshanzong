"""@module Prompt compiler; @purpose Template-driven traceable text, never image generation.
@depends model; @usedBy catalog and web; @see Visual North Star and asset-pipeline.md
"""
from .model import mapping, require
from pathlib import Path
import hashlib, re

PROJECT = Path(__file__).resolve().parents[2]

def project_rules(template):
    """Extract bounded relevant paragraphs in contract priority order; retain full-source hashes."""
    selectors = [
        ("docs/standards/visual-north-star.md", ["WORLD FIRST / UI SECOND", "HIGH VISUAL DETAIL +", "Runtime-first sizing"]),
        ("docs/standards/asset-pipeline.md", ["SOURCE NEVER DIRECTLY", "AI does not invent actions"]),
        ("assets/templates/templates.json", []),
        ("docs/standards/assets.md", ["MASTER != RUNTIME"]),
        ("docs/standards/animation.md", ["慢、稳、克制", "Simulation与Animation"]),
        ("docs/standards/pixel-runtime.md", ["优先整数倍像素缩放", "Sprite Sheet frame尺寸"]),
    ]
    if template["category"] == "building":
        selectors[0][1].append("点击建筑进入独立 Interior" if template["master_required"] else "宗门总览是纵向活建筑场景")
    snippets, hashes = [], {}
    for path, phrases in selectors:
        raw = (PROJECT / path).read_bytes()
        hashes[path] = hashlib.sha256(raw).hexdigest()
        if path.endswith("templates.json"):
            snippets.append("Asset Template: " + "; ".join(template["rules"]))
            continue
        paragraphs = raw.decode().split("\n\n")
        chosen = []
        for phrase in phrases:
            match = next((p for p in paragraphs if phrase in p), "")
            if match and match not in chosen:
                chosen.append(match)
        summaries = {
            "docs/standards/visual-north-star.md": "WORLD FIRST / SCENE FIRST / MOBILE FIRST. High visual detail, low frame counts, slow rhythm. Plan final mobile display size before the master. Building interiors use an independent spacious composition; overview buildings are living scenes.",
            "docs/standards/asset-pipeline.md": "Source never enters the game directly. Use template-defined actions, states and frame counts; AI must not invent them. Only reviewed and approved runtime builds may be published.",
            "docs/standards/assets.md": "Master and runtime assets are separate. Lock visual identity and pixel density; export for the actual display size.",
            "docs/standards/animation.md": "Slow, calm, restrained motion. Animation only presents committed state and never drives simulation.",
            "docs/standards/pixel-runtime.md": "Prefer integer pixel scaling and nearest-neighbor sampling. Frame dimensions must match the viewport; no neighboring-frame leakage."
        }
        snippets.append(path + ":\n" + summaries[path])
    return "\n".join(snippets), hashes

def compile_prompt(template, options, rule_context="", spec=None):
    from .specs import freeze_spec
    spec = spec or freeze_spec(template, options)
    selected = spec["template_snapshot"]
    for value in options.values():
        require(len(str(value)) <= 6000, "Prompt option too long")
    # Asset-bound frozen state is authoritative; raw user options cannot bypass the guard.
    if selected["master_required"] and spec["output_mode"] != "master":
        require(bool(options.get("master_reference")), "Interior state prompt requires confirmed Master reference")
    require(options.get("quality", "LEVEL 2") in ("LEVEL 1","LEVEL 2","LEVEL 3"), "Invalid visual quality")
    require(options.get("mode", "static") in ("static","dynamic"), "Invalid motion mode")
    manual_style = ''
    if spec['template_id'] == 'cultivation_manual_icon_v1':
        styles = {
            'scripture': '经书型 / Scripture: a neatly bound traditional scripture volume, orderly layered pages, dignified cloth cover and restrained sacred ornament.',
            'scroll': '卷轴型 / Scroll: a rolled or partially unfurled scroll with visible roller ends and a clear parchment silhouette.',
            'secret_book': '秘籍型 / Secret manual: a worn thread-bound martial cultivation handbook, weathered cover, visible binding stitches and restrained mysterious ornament.',
        }
        style = options.get('manual_style', 'scroll')
        require(isinstance(style, str) and style in styles, '请选择经书型、卷轴型或秘籍型')
        manual_style = styles[style] + ' Use this selected physical form for every named icon; it overrides the generic scroll/jade slip/book/sigil alternatives. No readable writing or baked titles. Keep the specified transparent export, dimensions and layout.'
    dims=lambda value: "x".join(map(str,value))
    from .sheets import canonical_spec
    spec=canonical_spec(spec)
    semantics=spec.get('sheet_semantics')
    effective=semantics or spec['template_snapshot'].get('default_sheet_semantics','independent_assets')
    static_actor=selected['category'] in ('monster','boss') and effective=='independent_assets'
    require(not static_actor or options.get('mode','static')=='static', '怪物静态素材不支持动作序列，请使用单张全身立绘')
    descriptions={
        'independent_assets':'Different independent game Assets, exactly one static frame each. These cells are NOT animation frames.',
        'action_frames':'The SAME character/object, with action frames ordered in time. All cells belong to that object; never create a new character per frame.',
        'scene_states':'Each cell is a COMPLETE independent Scene State of the same locked room/building. NOT animation frames. Never divide one room into pieces or spread six states across a continuous room.',
        'environment_variants':'Complete variants of the SAME location. Lock camera, terrain, architecture and perspective; change only time, sky, light, lamps, shadow, fog and clouds. NOT animation frames.',
        'state_sequence':'Non-animation states of the SAME object, not different resources or frame animation.',
        'effect_frames':'Consecutive effect keyframes, ordered in time; high detail and low frame count.',
        'ui_states':'Separate interaction states of the SAME UI component. NOT animation frames. Never rely on hover for mobile use.',
        'tiles':'Distinct stitchable terrain tiles with matching pixel density and continuous edges. NOT animation frames.',
        'nine_slice':'Nine ordered interface frame parts: top_left, top, top_right, left, center, right, bottom_left, bottom, bottom_right. Matching edge continuity. NOT animation frames.'}
    if spec.get('frame_asset_list'):
        structure=descriptions[effective]+' Each row is a DIFFERENT named effect; columns are consecutive frames of that same effect. Never mix effect identities between rows.\n'+'\n'.join(f'Row {i}: {item["name_zh"]}, {spec["frame_counts"]["effect"]} frames left to right' for i,item in enumerate(spec['frame_asset_list'],1))
    elif effective in ('action_frames','effect_frames'):
        structure=descriptions[effective]+'\n'+'\n'.join(f'Row {i}: {a}, {n} frame(s), left to right' for i,(a,n) in enumerate(spec['frame_counts'].items(),1))
    elif spec.get('asset_list'):
        prefix=f'{spec["asset_count"]} different independent game assets. Each asset has exactly one static frame. ' if effective=='independent_assets' else f'{len(spec["cell_mapping"])} complete scene/state/variant components. '
        structure=prefix+descriptions[effective]+'\n'+'\n'.join(f'{i+1}. {a["name_zh"]} ({a["asset_id"]})'+(' / '+a['action'] if a.get('action') else '') for i,a in enumerate(spec['asset_list']))
    else:structure=descriptions[effective]+'\n'+', '.join(spec['row_order'])
    if spec['output_mode']=='master':structure='Single locked Master Scene; one complete image, no sheet, no action variants'
    g=spec['layout_spec'];container=spec['source_container']
    layout=f'{g["rows"]} rows x {g["columns"]} columns. Fixed cell {dims(spec["source_cell_size"])} px; horizontal gap {g["horizontal_gap"]} px; vertical gap {g["vertical_gap"]} px; row-major order. '
    if container=='sheet':
        width=g['columns']*g['cell_width']+(g['columns']-1)*g['horizontal_gap']+g['outer_margin']['left']+g['outer_margin']['right']
        height=g['rows']*g['cell_height']+(g['rows']-1)*g['vertical_gap']+g['outer_margin']['top']+g['outer_margin']['bottom']
        layout='Generate ONE sliceable sheet. '+layout+f'Total sheet canvas: {width}x{height} px. '
        if spec.get('frame_asset_list'):layout+='Each named effect occupies its own row. Only specified frames are active; every unused cell remains transparent and unassigned. '
        elif effective in ('action_frames','effect_frames'):layout+='Each action occupies its own row. Only specified frames are active; every unused cell remains transparent and unassigned. '
        else:layout+='Each cell is one mapped Asset/state/variant, never a frame sequence. Do not merge multiple mapped entries into one cell. Unused cells remain empty. '
        layout+='Cell order: '+', '.join(f'[{c["row"]+1},{c["column"]+1}] '+c.get('name_zh',c['action'])+(' frame '+str(c['frame']) if effective in ('action_frames','effect_frames') else '') for c in spec['cell_mapping'])
    elif container=='image_set':layout='Generate separate complete images with shared identity/reference; '+structure+' Each upload must explicitly bind its Asset/state or selected action. No automatic semantic recognition.'
    else:layout='Generate ONE complete image with the selected source-cell aspect ratio. No sheet or additional states.'
    art=("Simplified Chinese xianxia pixel art, bright and legible, semi-realistic proportions, moderately emphasized defining features. "
         "Real pixel clusters, hard edges, limited color steps, upper-left key light. No obvious big-head chibi, antialiasing, blurry gradients, smoothed 3D or downscaled high-resolution illustration pretending to be pixel art. "
         "Phone-size readability first. Refined shapes, materials, textures and restrained effects; no neon pollution or full-screen particles. "
         "WORLD FIRST / SCENE FIRST / MOBILE FIRST. High detail, low frame count, slow rhythm. "+options.get("quality","LEVEL 2"))
    if spec['transparent']:art+=' This is an isolated sprite/icon export, not a scene illustration. World/scene art direction controls visual style only; it does not request any environment or backdrop.'
    ui_component=spec.get('runtime_role')=='ui_component'
    transparency_contract=(
        '必须输出带真实 Alpha 通道的 RGBA PNG，背景像素 Alpha=0，不能用颜色模拟透明。'
        '禁止白底、灰底、棋盘格、透明网格示意图、纸张纹理、雾底、渐变底、地面、底座、场景或图鉴展示背景。'
        '透明是文件属性，不是要画出来的图案。背景保持空白透明；只绘制指定主体。\n'
        'Deliver RGBA PNG with a genuine alpha channel. All background pixels must have alpha=0. '
        'Do not paint a white/gray background, checkerboard, transparency grid, paper texture, fog backdrop, gradient, floor, pedestal or showcase scene. '
        'Transparency is a file property, never a drawn pattern. No ambient haze, bloom, cast shadow or translucent wash outside the subject. '
        'Keep anatomical holes and spaces between limbs transparent. Solid anatomy and materials use readable opaque pixel clusters; authored glass or effect pixels may keep intentional transparency inside the subject silhouette. Keep highlights and material detail inside that silhouette, never as background haze. '
        'If the generation tool cannot export genuine alpha, report that limitation instead of substituting a fake transparent background. '
        'Export requirements take priority over decorative presentation and subject notes.'
    ) if spec['transparent'] else ''
    if ui_component:
        transparency_contract=(
            '必须输出真实Alpha通道的RGBA PNG，组件外、留白与格间像素Alpha=0；不要绘制白底、棋盘格或展示背景。'
            '指定的组件边框、墨色面板底、玉石或纸纹填充属于组件本身，允许实色；文字和图标由游戏叠加，不要烘焙。\n'
            'Deliver RGBA PNG with a genuine alpha channel. All empty margins and gaps outside components must be alpha=0; never paint checkerboards or showcase backgrounds. '
            'Never use an opaque white, gray or black backdrop, even temporarily; transparency is a file property, not a painted color or checkerboard. Export PNG, never JPG. Requested component borders and interior ink, jade or paper-texture fills belong to the component and may be opaque ONLY inside their intended silhouette. '
            'Do not bake labels, numbers or icons; preserve requested viewport and corner inset bands. Report if genuine alpha export is unavailable.'
        )
    if spec['transparent']:
        transparency_contract+='\n[Final Alpha Check / 输出前透明自检] 四角安全边和所有格间必须Alpha=0。输出前检查实际文件Alpha通道；白底、棋盘底或不透明留边均不合格，必须重新生成真透明PNG再交付。不得把整张图片半透明冒充抠空背景。 Verify the actual alpha channel before delivery: corner safety padding, cell gaps and every pixel outside intended component/subject silhouettes must have alpha=0. Reject and regenerate opaque backdrop or checkerboard results before delivery. Do not simulate transparency by reducing opacity across the whole image. If genuine alpha export is unavailable, state that limitation; do not substitute a flat background.'
    safety=(f'Background: {"transparent" if spec["transparent"] else "complete scene background"}. '
            f'At least {spec["spacing"]} px transparent separation between cells; at least {spec["inner_safe_padding"]} px inner safe padding on each side. '
            'Empty cells, outer margins and cell gaps must be alpha=0, without grid lines or dividers. Weapons, hair, clothing, sword trails and particles must never enter adjacent cells. Reduce subject scale or split large effects into separate assets instead of narrowing gaps.')
    if not spec["transparent"]: safety="Complete scene background; preserve locked composition and aspect ratio. Cell dimensions describe scene framing, not a sprite body."
    anchor_text=(" Scene framing anchor: center. Actor landing baseline follows the battle-stage rules below; no actors are baked into this background." if spec["template_id"]=="battle_background_v1" else f' Anchor: {spec["anchor"]["type"]}; feet baseline inset {spec["anchor"]["baseline_from_bottom"]} px. Consistent subject scale and baseline across frames.')
    sections=[
        "[This Asset]\n"+str(options.get("object","Unnamed subject"))+" / "+spec["template_id"]+"@"+str(spec["template_version"])+"; family="+spec["family"]+"; motion intent="+options.get("mode","static")+"; "+str(options.get("purpose","Xianxia V2 visual asset")),
        *(['[Cultivation Manual Style / 功法样式]\n'+manual_style] if manual_style else []),
        *(['[Required Transparent Export / 必须真实透明]\n'+transparency_contract] if spec['transparent'] else []),
        "[Overall Art Direction]\n"+art+"\nProject rules in priority order:\n"+rule_context,
        "[Logical Pixels and Runtime Target]\n"+f'Subject logic size: {dims(spec["subject_logic_size"])} px. Fixed source cell: {dims(spec["source_cell_size"])} px. Runtime frame: {dims(spec["runtime_profile"]["frame_size"])} px; policy={spec["runtime_profile"]["policy"]}; profile={spec["runtime_profile"]["profile_id"]}. Subject size is not transparent canvas, collision area or gameplay footprint. '+("For complete scene profiles, Source/Master may use a larger integer multiple of the logical scene resolution with identical aspect ratio/composition; Runtime stays at its logical target." if spec["runtime_profile"]["policy"]=="scene_resize" else "Sprite/icon source cells are fixed; do not confuse padding or body size with the final frame."),
        "[Transparency and Slice Safety]\n"+safety+anchor_text,
        ("[Independent Static Assets]\n" if effective=="independent_assets" else "[Actions / States]\n")+structure+"\nAI must not add actions or decide frame counts; draw only this frozen specification.",
        ("[Effect Keyframes]\nDraw the specified effect itself: readable start/impact/dissipation keyframes in temporal order. Maintain the same center anchor, scale and pixel density across its frames. No characters, weapons held by actors, scenery or fake transparent background; effects stay fully inside their own cells. Do not add extra frames." if effective=="effect_frames" else "[Static Image Policy]\nEach Asset contains one static image. Asset Count is independent of Frame Count; no animation sequence is requested." if effective not in ("action_frames","effect_frames") else "[Low Frame Count]\nUse a few high-quality key poses and deliberate holds. Do not default to 6, 8 or 12 frames per action. Displacement, flash, scaling, trails, particles and shake belong to future presentation code where appropriate, not every sprite frame."),
        "[Type-Specific Rules]\n"+"; ".join(selected["rules"]),
        "[Master / Reference Rules]\nMaster reference: "+str(options.get("master_reference","none"))+". If selected, attach the actual approved master image manually; an ID alone cannot replace image reference. "+("References preserve subject identity, anatomy, material and pixel style only; do not copy their background, checkerboard, labels or scene." if spec['transparent'] else "Interior states preserve the same camera, composition, architecture, furniture, perspective, base lighting, character scale and workstations."),
        "[Allowed Changes]\n"+str(options.get("allowed_changes") or ("Only the named UI component shape, continuous borders, corner ornaments and restrained interior fills. Keep exact viewport size and genuine transparent outer padding; leave space for programmatic labels and icons." if ui_component else "Different complete monster silhouettes, anatomy, armor and weapons in one shared art style. One neutral pose per monster; never add action variants. Attack displacement, hit shake and spell effects are separate game presentation. No environmental fog, floating debris cloud, detached decorative particles or cast shadow. Keep required appendages and defining ornaments fully inside their own cell; do not crop them. Intentional separated body parts must remain tightly grouped within the same cell, away from neighboring subjects." if static_actor else "Only individual resource shapes, materials and restrained surface details within the shared art family." if spec.get("asset_list") else "Only the specified subject shape, pose, materials and restrained surface details; keep the transparent export contract." if spec["transparent"] else "Only selected poses/states and local props, flame, smoke, aura and lighting feedback; never redesign the room.")),
        "[Must Remain Locked]\nIdentity, subject scale, pixel density, anchor, source cell, action order and counts. "+str(options.get("locked","")),
        "[Text, Quality and Reuse]\nNo baked text or enhancement +N. Do not invent gameplay rarity, quality tiers, stats or effects. Preserve art-family identity and meaningful silhouettes instead of recoloring a generic base.",
        "[Layout]\n"+layout,
        "[Prohibited]\n"+("No baked labels or numbering, showcase backgrounds, poster layouts, drawn slicing guides, neighboring-component leakage or unrequested variants. Requested component borders and fills are allowed; external padding stays transparent." if ui_component else "No labels, numbering, borders, showcase background, encyclopedia frame, poster layout, neighboring-frame leakage, excessive glow or unrequested actions. No animation-driven simulation."),
        "[Final Output Goal]\nProduction-ready sliceable game art, not a presentation sheet. Pixel-perfect; nearest-neighbor and integer display scaling preferred. "+("Keep the background genuinely transparent in the PNG alpha channel; never replace it with white or a checkerboard. " if spec["transparent"] else "Complete scenes retain 16:9 where defined. ")+"Output only requested images. "+str(options.get("notes",""))]
    return "\n\n".join(sections)
