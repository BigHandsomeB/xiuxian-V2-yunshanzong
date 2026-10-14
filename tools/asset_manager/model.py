"""@module Asset contracts; @purpose Validate templates, mappings and slice plans.
@depends standard library; @usedBy catalog, prompts, web; @see asset-pipeline.md
"""
import re

class AssetError(ValueError):
    pass

def require(condition, message):
    if not condition:
        raise AssetError(message)

def identifier(value):
    require(isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_.-]{0,119}", value), "Invalid stable ID")
    return value

def integer(value, minimum=0, maximum=16384):
    require(type(value) is int and minimum <= value <= maximum, "Invalid integer")
    return value

def templates(document):
    require(isinstance(document, dict) and document.get("schema_version") == 2, "Unsupported template schema")
    require(isinstance(document.get("templates"), list) and bool(document["templates"]), "Templates must be a nonempty list")
    import copy
    from .specs import validate_profile
    profiles=document.get("pixel_size_profiles")
    require(isinstance(profiles,dict) and profiles, "Missing pixel profile authority")
    for key, profile in profiles.items():
        require(key==profile.get("profile_id"), "Pixel profile ID mismatch")
        validate_profile(profile)
    result = {}
    for item in document["templates"]:
        require(isinstance(item, dict) and all(k in item for k in ["template_id", "category", "structure", "transparent", "master_required", "layout", "runtime_policy", "rules"]), "Missing template fields")
        item=copy.deepcopy(item)
        integer(item.get("template_version"),1)
        require(type(item.get("creation_enabled", True)) is bool, "Invalid creation availability")
        from .sheets import validate_rules
        validate_rules(item)
        policy=item.get("creation_policy",{})
        for field in ("default_asset_family","asset_namespace","set_namespace","runtime_role"): identifier(policy.get(field))
        require(policy["default_asset_family"]=="default" or policy["default_asset_family"] in item.get("families",{}), "Unknown default asset family")
        require(isinstance(item.get("pixel_size_profile"),str) and item.get("pixel_size_profile") in profiles, "Unknown pixel profile reference")
        require(item.get("output_mode") in ("sprite_sheet","scene_set","independent_scene","icon"), "Invalid output mode")
        for family, value in item.get("families",{}).items():
            identifier(family)
            validate_rules({**item,**value})
            for field,v in value.get("creation_policy",{}).items():
                require(field in ("runtime_role","asset_namespace","set_namespace"),"Invalid family creation policy")
                identifier(v)
            require(isinstance(value.get("pixel_size_profile"),str) and value.get("pixel_size_profile") in profiles, "Unknown family pixel profile")
            structure=value.get("structure",item["structure"])
            for action,bounds in structure.items():
                identifier(action); require(isinstance(bounds,list) and len(bounds)==2,"Invalid family frame policy")
                integer(bounds[0],1,8);integer(bounds[1],bounds[0],8)
            defaults=value.get("default_actions",item["default_actions"])
            require(defaults and len(set(defaults))==len(defaults) and all(a in structure for a in defaults),"Invalid family default actions")
        require(item.get("runtime_export_policy", "frozen") in ("frozen", "current_item_profile"), "Invalid Runtime export policy")
        if item.get("runtime_export_policy") == "current_item_profile":
            require(item["output_mode"] == "icon" and profiles[item["pixel_size_profile"]]["runtime_profile"]["policy"] == "crop_subject", "Item export requires static item profile")
        item["pixel_size_profile"]=copy.deepcopy(profiles[item["pixel_size_profile"]])
        item["available_profiles"]={k:copy.deepcopy(profiles[k]) for k in {item["pixel_size_profile"]["profile_id"],*[v["pixel_size_profile"] for v in item.get("families",{}).values()]}}
        identifier(item["category"])
        require(isinstance(item["structure"], dict), "Invalid action structure")
        require(isinstance(item["rules"], list) and all(isinstance(r, str) and len(r) <= 4000 for r in item["rules"]), "Invalid template rules")
        require(all(isinstance(item[k], str) and bool(item[k]) for k in ["layout", "runtime_policy"]), "Invalid template policy")
        key = identifier(item["template_id"])
        require(key not in result, "Duplicate template_id")
        require(bool(item["structure"]), "Empty template structure")
        for action, bounds in item["structure"].items():
            identifier(action)
            require(len(bounds) == 2, "Invalid frame policy")
            integer(bounds[0], 1, 8); integer(bounds[1], bounds[0], 8)
        require(bool(item.get("default_actions")) and len(set(item["default_actions"])) == len(item["default_actions"]) and all(a in item["structure"] for a in item["default_actions"]), "Invalid default actions")
        require(type(item["transparent"]) is bool and type(item["master_required"]) is bool, "Invalid background/Master policy")
        if item["master_required"]:
            require(item.get("state_count") == [4,6], "Interior state count must be 4–6")
        result[key] = item
    return result

def rectangle(rect, width, height):
    require(isinstance(rect, list) and len(rect) == 4, "Rectangle needs x,y,width,height")
    x, y, w, h = rect
    integer(x); integer(y); integer(w, 1); integer(h, 1)
    require(x + w <= width and y + h <= height, "Slice out of bounds")
    return rect

def grid(width, height, options):
    rows = integer(options.get("rows"), 1, 64)
    columns = integer(options.get("columns"), 1, 64)
    fw = integer(options.get("frame_width"), 1)
    fh = integer(options.get("frame_height"), 1)
    gapx = integer(options.get("horizontal_gap", 0))
    gapy = integer(options.get("vertical_gap", 0))
    top, bottom, left, right = [integer(options.get("margin_" + k, 0)) for k in ["top", "bottom", "left", "right"]]
    require(left + right + columns * fw + (columns - 1) * gapx <= width, "Grid exceeds source width")
    require(top + bottom + rows * fh + (rows - 1) * gapy <= height, "Grid exceeds source height")
    require(rows * columns <= 256, "Too many components")
    return [[left + col * (fw + gapx), top + row * (fh + gapy), fw, fh] for row in range(rows) for col in range(columns)]

def mapping(template, values, counts):
    require(isinstance(counts, dict) and bool(counts), "Choose states/actions")
    for action, count in counts.items():
        require(action in template["structure"], "Unknown state/action")
        low, high = template["structure"][action]
        integer(count, low, high)
    expected = [(action, frame) for action, count in counts.items() for frame in range(1, count + 1)]
    actual = []
    for value in values:
        require(isinstance(value, dict), "Invalid mapping")
        require(value.get("action") in counts, "Unselected state/action")
        integer(value.get("frame"), 1, 8)
        actual.append((value.get("action"), value.get("frame")))
    require(sorted(actual) == sorted(expected), "Mapping must contain every selected frame exactly once")
    return values

REVIEW = ["style", "dimensions", "background", "composition", "mapping", "frame_isolation", "runtime_clarity"]
INTERIOR_REVIEW = ["camera", "architecture", "furniture", "perspective", "base_lighting", "character_scale", "workstations", "pixel_density", "local_changes_only", "master_consistency"]
