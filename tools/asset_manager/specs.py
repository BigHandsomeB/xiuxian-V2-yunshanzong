"""Shared asset specification authority: validate, resolve, freeze and derive slice geometry.
Data lives only in assets/templates/templates.json; no frontend or importer size tables.
"""
import copy
from .model import require, integer, identifier, mapping

def size(value):
    require(isinstance(value, list) and len(value) == 2, "Size needs width and height")
    return [integer(n, 1, 4096) for n in value]

def validate_profile(profile):
    require(isinstance(profile, dict), "Invalid pixel profile")
    identifier(profile.get("profile_id")); integer(profile.get("version"), 1)
    logic=size(profile.get("subject_logic_size")); cell=size(profile.get("source_cell_size"))
    pad=integer(profile.get("inner_safe_padding")); integer(profile.get("spacing"))
    choices=profile.get("subject_options")
    require(isinstance(choices,list) and logic in choices, "Missing subject size choices")
    for option in choices:
        size(option)
        require(all(n + 2*pad <= c for n,c in zip(option,cell)), "Subject and safety padding exceed Source Cell")
    anchor=profile.get("anchor",{})
    require(anchor.get("type") in ("center","bottom_center"), "Invalid anchor")
    integer(anchor.get("baseline_from_bottom"), 0, cell[1])
    runtime=profile.get("runtime_profile",{})
    require(type(runtime.get("trim_transparent", False)) is bool, "Invalid transparent crop policy")
    identifier(runtime.get("profile_id")); size(runtime.get("frame_size"))
    require(runtime.get("policy") in ("preserve_cell","crop_subject","scene_resize") and runtime.get("sampling")=="nearest", "Invalid runtime profile")
    require(runtime["frame_size"] == (cell if runtime["policy"]=="preserve_cell" else logic), "Runtime profile dimensions disagree with policy")
    return profile

def resolve_template(template, family=None):
    result=copy.deepcopy(template)
    if family and family != "default":
        require(family in template.get("families",{}), "Unknown asset family")
        choice=template["families"][family]
        for key in ("structure","default_actions","transparent","output_mode","default_source_container","allowed_source_containers","default_sheet_semantics","allowed_sheet_semantics","default_generation_scope"):
            if key in choice: result[key]=copy.deepcopy(choice[key])
        result["pixel_size_profile"]=copy.deepcopy(template["available_profiles"][choice["pixel_size_profile"]])
        result["rules"]+=choice.get("rules",[])
        if choice.get("creation_policy"):result["creation_policy"].update(copy.deepcopy(choice["creation_policy"]))
    result["family"]=family or "default"
    return result

def freeze_spec(template, options=None):
    options=copy.deepcopy(options or {})
    selected=resolve_template(template, options.get("family"))
    require(options.get("expected_template_version",selected["template_version"])==selected["template_version"],"Template version changed; refresh the page before generating/importing")
    profile=copy.deepcopy(selected["pixel_size_profile"])
    choice=options.get("subject_logic_size",profile["subject_logic_size"])
    require(choice in profile["subject_options"], "Choose a supported logic size or enable advanced override")
    profile["subject_logic_size"]=copy.deepcopy(choice)
    if profile["runtime_profile"]["policy"] != "preserve_cell": profile["runtime_profile"]["frame_size"]=copy.deepcopy(choice)
    override=options.get("profile_override")
    if override:
        require(options.get("advanced_override") is True and isinstance(override,dict), "Pixel override requires explicit advanced selection")
        require(set(override) <= {"subject_logic_size","source_cell_size","spacing","inner_safe_padding","runtime_frame_size"}, "Unknown pixel override field")
        for key in ("subject_logic_size","source_cell_size","spacing","inner_safe_padding"):
            if key in override: profile[key]=copy.deepcopy(override[key])
        require(profile["spacing"] >= selected["pixel_size_profile"]["spacing"] and profile["inner_safe_padding"] >= selected["pixel_size_profile"]["inner_safe_padding"], "Do not reduce template cut safety")
        profile["subject_options"]=[profile["subject_logic_size"]]
        derived=profile["source_cell_size"] if profile["runtime_profile"]["policy"]=="preserve_cell" else profile["subject_logic_size"]
        require("runtime_frame_size" not in override or override["runtime_frame_size"] == derived, "Runtime override must respect canvas policy")
        profile["runtime_profile"]["frame_size"]=copy.deepcopy(derived)
        profile["anchor"]["baseline_from_bottom"]=profile["inner_safe_padding"] if profile["anchor"]["type"]=="bottom_center" else 0
    validate_profile(profile)
    counts=options.get("counts",{a:selected["structure"][a][0] for a in selected["default_actions"]})
    require(isinstance(counts,dict), "Invalid frame counts")
    counts={a:counts[a] for a in selected["structure"] if a in counts}
    require(len(counts)==len(options.get("counts",counts)), "Unknown state/action")
    mapping(selected,[dict(action=a,frame=f) for a,n in counts.items() for f in range(1,integer(n,1,8)+1)],counts)
    state=options.get("state")
    require(not state or state=="master" or state in selected["structure"], "Unknown state/action")
    if state=="master":
        counts={"master":1}
    elif state and state not in counts:
        require(False,"Selected asset state is not enabled")
    mode=selected["output_mode"]
    rows=len(counts); columns=max(counts.values())
    if state=="master" or mode in ("scene_set","independent_scene","icon"):
        mode="master" if state=="master" else mode
        columns=1
    if options.get("extra_columns") is not None:
        require(mode=="sprite_sheet", "Extra columns are only for sprite sheets")
        columns=integer(options["extra_columns"],columns,64)
    cell=profile["source_cell_size"]; gap=profile["spacing"]
    grid=dict(rows=rows,columns=columns,frame_width=cell[0],frame_height=cell[1],horizontal_gap=gap,vertical_gap=gap,margin_top=0,margin_bottom=0,margin_left=0,margin_right=0)
    runtime=profile["runtime_profile"]
    if mode=="sprite_sheet":
        sheet_w=columns*cell[0]+(columns-1)*gap;sheet_h=rows*cell[1]+(rows-1)*gap
        require(sheet_w<=8192 and sheet_h<=8192 and sheet_w*sheet_h<=16*1024*1024,"Planned sheet exceeds upload limits")
    if options.get("runtime_size"):
        # Compatibility for clients passing an explicit size: it must match this authority.
        require(isinstance(options["runtime_size"],str) and options["runtime_size"].replace("×","x")=="x".join(map(str,runtime["frame_size"])), "Runtime size must match pixel profile; use advanced profile override")
    transparent=options.get("transparent",selected["transparent"])
    require(type(transparent) is bool and transparent==selected["transparent"], "Background must match selected template/family")
    if mode=="sprite_sheet": require(transparent, "Sprite sheets require transparency")
    spec = dict(runtime_role=selected["creation_policy"]["runtime_role"],schema_version=1,template_id=selected["template_id"],template_version=selected["template_version"],family=selected["family"],pixel_size_profile_id=profile["profile_id"],pixel_size_profile_version=profile["version"],subject_logic_size=profile["subject_logic_size"],source_cell_size=cell,spacing=gap,inner_safe_padding=profile["inner_safe_padding"],anchor=profile["anchor"],runtime_profile=runtime,action_spec=selected["structure"],frame_counts=counts,row_order=list(counts),column_count=columns,row_count=rows,output_mode=mode,transparent=transparent,grid_spec=grid,profile_override=override or None,template_snapshot=selected)
    from .sheets import freeze_container
    return freeze_container(spec,options)

def grid_regions(spec, geometry=None):
    # Historical call name; geometry is owned by the common Sheet module.
    from .sheets import regions
    return [dict(action=r['action'],frame=r['frame'],rect=r['rect']) for r in regions(spec,geometry)]


def export_spec(template, frozen, policy="frozen"):
    """Runtime export only: never rewrite generation/crop rules or historical snapshots."""
    require(policy in ("frozen", "current_item_profile", "player_combat_profile"), "Unknown Runtime export policy")
    result = copy.deepcopy(frozen)
    if policy == "frozen":
        return result, dict(policy=policy, template_id=frozen.get("template_id"),
                            template_version=frozen.get("template_version"),
                            pixel_profile_version=frozen.get("pixel_size_profile_version"))
    if policy=='player_combat_profile':
        require(template['template_id']=='character_compact_v1' and frozen.get('runtime_role')=='character_sprite' and frozen.get('output_mode')=='sprite_sheet','Combat profile requires character frames')
        profile=copy.deepcopy(template['combat_runtime_profile'])
        result['runtime_profile']=profile;result['subject_logic_size']=profile['subject_logic_size']
        result['anchor']={'type':'bottom_center','baseline_from_bottom':profile['baseline_from_bottom']}
        return result,dict(policy=policy,template_id=template['template_id'],template_version=template['template_version'],pixel_profile_id=profile['profile_id'],pixel_profile_version=profile['version'],subject_logic_size=profile['subject_logic_size'])
    require(not frozen.get("legacy") and template.get("runtime_export_policy") == policy,
            "Current item export is only available for game item icon templates")
    require(frozen["template_id"] == template["template_id"] and frozen["output_mode"] in ("icon", "static_sheet", "static_independent"),
            "Runtime export Template mismatch")
    current = resolve_template(template, frozen.get("family"))
    profile = current["pixel_size_profile"]
    require(profile["runtime_profile"]["policy"] == "crop_subject", "Item export needs subject policy")
    # Keep historical source_cell/subject crop fractions: changing them would recrop approved art.
    result["runtime_profile"] = copy.deepcopy(profile["runtime_profile"])
    origin = dict(policy=policy, template_id=current["template_id"], template_version=current["template_version"],
                  pixel_profile_id=profile["profile_id"], pixel_profile_version=profile["version"],
                  subject_logic_size=copy.deepcopy(profile["subject_logic_size"]),
                  source_cell_size=copy.deepcopy(profile["source_cell_size"]))
    return result, origin


def default_export_policy(template, frozen):
    # Item families can also define growth states; their scene exports stay frozen.
    return template.get('runtime_export_policy','frozen') if frozen.get('output_mode') in ('icon','static_sheet','static_independent') else 'frozen'
