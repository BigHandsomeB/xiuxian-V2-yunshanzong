"""@module Deterministic raster operations; @purpose Verified image import and crop/build.
@depends Pillow; @usedBy catalog; @see pixel-runtime.md
"""
import io, warnings, re, unicodedata
from PIL import Image, UnidentifiedImageError
from .model import require, integer, rectangle, AssetError

MAX_BYTES = 12 * 1024 * 1024
MAX_PIXELS = 16 * 1024 * 1024
EXTENSIONS = {"png": "PNG", "jpg": "JPEG", "jpeg": "JPEG", "webp": "WEBP"}

def decode(data, filename):
    require(isinstance(filename, str) and len(filename) <= 160 and filename not in (".", "..") and not any(c in filename for c in "/\\\x00") and not filename.startswith("."), "Unsafe filename")
    # This is a display name, never a destination: Catalog generates the stored ID.
    # Accept ordinary Unicode punctuation/export spaces; reject controls, bidi/hidden
    # formatting, surrogate code points and Windows drive paths as well as paths above.
    require(re.match(r"^[A-Za-z]:", filename) is None, "Unsafe filename")
    require(all(unicodedata.category(c)[0] in "LMNPS" or unicodedata.category(c) == "Zs"
                for c in filename), "Unsafe filename characters")
    require(isinstance(data, bytes), "Image upload must be bytes")
    extension = filename.rsplit(".", 1)[-1].lower()
    require(extension in EXTENSIONS, "Only PNG, JPEG and WebP images allowed")
    require(0 < len(data) <= MAX_BYTES, "Upload size limit exceeded")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                require(image.format == EXTENSIONS[extension], "Image format does not match extension")
                require(image.width <= 8192 and image.height <= 8192 and image.width * image.height <= MAX_PIXELS, "Image dimensions exceed limit")
                require(getattr(image, "n_frames", 1) == 1, "Animated uploads are not supported; upload a sheet")
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                image.load()
                return image.convert("RGBA")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise AssetError("Invalid or oversized image") from exc

def png(image):
    output = io.BytesIO(); image.save(output, format="PNG")
    return output.getvalue()

def crop(image, rect):
    x, y, w, h = rectangle(rect, image.width, image.height)
    return image.crop((x, y, x + w, y + h))

def runtime(image, width, height, format_name, allow_non_integer=False):
    integer(width, 1, 4096); integer(height, 1, 4096)
    require(width * height <= MAX_PIXELS, "Runtime too large")
    require(format_name in ("png", "webp"), "Runtime format must be PNG or lossless WebP")
    require(image.width * height == image.height * width, "Runtime resize must preserve aspect ratio")
    integral = (width >= image.width and width % image.width == 0) or (width <= image.width and image.width % width == 0)
    require(type(allow_non_integer) is bool and (integral or allow_non_integer), "Non-integer resizing requires explicit acknowledgement and phone review")
    # Never interpolate pixel boundaries; non-integer sizing requires human runtime review.
    resized = image.resize((width, height), Image.Resampling.NEAREST)
    output = io.BytesIO()
    resized.save(output, format=format_name.upper(), **({"lossless": True, "exact": True} if format_name == "webp" else {}))
    return output.getvalue()


def profiled_runtime(image, spec, format_name="png", allow_non_integer=False, subject_region=False):
    """Frozen canvas policy; never equate a sprite body with its transparent cell."""
    target=spec["runtime_profile"]["frame_size"]
    policy=spec["runtime_profile"]["policy"]
    cell=spec["source_cell_size"]
    if policy=='fit_actor':
        # Re-export the approved full-resolution component, never enlarge its old tiny Runtime.
        scale=spec['actor_scale'];w=max(1,round(image.width*scale));h=max(1,round(image.height*scale))
        require(w<=target[0] and h<=target[1]-spec['anchor']['baseline_from_bottom'],'Combat frame exceeds viewport')
        canvas=Image.new('RGBA',tuple(target),(0,0,0,0))
        canvas.alpha_composite(image.convert('RGBA').resize((w,h),Image.Resampling.NEAREST),((target[0]-w)//2,target[1]-spec['anchor']['baseline_from_bottom']-h))
        output=io.BytesIO();canvas.save(output,format=format_name.upper(),**({'lossless':True,'exact':True} if format_name=='webp' else {}));return output.getvalue()
    if policy=='scene_resize' and subject_region and image.width*target[1]!=image.height*target[0]:
        # Actual panel boundaries can differ slightly from the frozen 16:9 viewport.
        # Keep the whole reviewed panel, add padding, never distort or redefine profile.
        factor=max(1,(image.width+target[0]-1)//target[0],(image.height+target[1]-1)//target[1])
        canvas=Image.new('RGBA',(target[0]*factor,target[1]*factor),(0,0,0,0))
        canvas.alpha_composite(image.convert('RGBA'),((canvas.width-image.width)//2,(canvas.height-image.height)//2))
        return runtime(canvas,*target,format_name,allow_non_integer)
    if policy=="preserve_cell" and subject_region:
        # Located sprite body is geometry, not its Runtime viewport. Fit to the frozen
        # logic area, restore transparent canvas and feet baseline with nearest sampling.
        logic=spec['subject_logic_size'];w,h=image.size
        factor=max(1,(w+logic[0]-1)//logic[0],(h+logic[1]-1)//logic[1])
        canvas=Image.new('RGBA',(target[0]*factor,target[1]*factor),(0,0,0,0))
        x=(canvas.width-w)//2
        y=canvas.height-spec['anchor']['baseline_from_bottom']*factor-h if spec['anchor']['type']=='bottom_center' else (canvas.height-h)//2
        require(x>=0 and y>=0,'Detected sprite cannot fit frozen canvas')
        canvas.alpha_composite(image.convert('RGBA'),(x,y))
        return runtime(canvas,*target,format_name,allow_non_integer)
    independent_subject=False
    if policy=="crop_subject" and spec.get("source_container") in ("single_image","image_set"):
        # Some historical independent icons still contain the template's safe padding.
        # Keep that crop only when it cannot remove any visible part of the image.
        logic=spec['subject_logic_size'];w=image.width*logic[0]/cell[0];h=image.height*logic[1]/cell[1]
        bounds=image.convert('RGBA').getchannel('A').getbbox()
        independent_subject=image.width*cell[1]!=image.height*cell[0] or bool(bounds and (bounds[0]<(image.width-w)/2 or bounds[1]<(image.height-h)/2 or bounds[2]>(image.width+w)/2 or bounds[3]>(image.height+h)/2))
    if policy=="crop_subject" and (subject_region or independent_subject or spec["runtime_profile"].get("trim_transparent")):
        # Static actors must not shrink to half size merely because localization
        # retained a few transparent safety pixels around a native128/256px body.
        # Opt-in profiles only: historical item/sprite crop rules stay frozen.
        if spec["runtime_profile"].get("trim_transparent"):
            image=image.convert("RGBA")
            bounds=image.getchannel("A").getbbox()
            require(bounds is not None, "Static actor crop is empty")
            image=image.crop(bounds)
        # Actual subject crops and independent images are not theoretical source cells.
        # Fit the complete image without applying the sheet's central crop fraction.
        # Transparent padding preserves aspect and frozen target; nearest only, no mask removal.
        w,h=image.size; tw,th=target
        factor=max((w+tw-1)//tw,(h+th-1)//th)
        canvas=Image.new("RGBA",(tw*factor,th*factor),(0,0,0,0))
        canvas.alpha_composite(image.convert("RGBA"),((canvas.width-w)//2,(canvas.height-h)//2))
        return runtime(canvas,tw,th,format_name,allow_non_integer)
    if policy=="crop_subject":
        require(image.width*cell[1]==image.height*cell[0], "Component must match source-cell aspect before subject crop")
        logic=spec["subject_logic_size"]
        require(image.width*logic[0] % cell[0] == 0 and image.height*logic[1] % cell[1]==0, "Subject crop requires exact pixel boundaries")
        w=image.width*logic[0]//cell[0];h=image.height*logic[1]//cell[1]
        image=crop(image,[(image.width-w)//2,(image.height-h)//2,w,h])
    elif policy=="preserve_cell" and image.width<=cell[0] and image.height<=cell[1] and image.size!=tuple(cell):
        canvas=Image.new("RGBA",tuple(cell),(0,0,0,0))
        x=(cell[0]-image.width)//2
        y=cell[1]-spec["anchor"]["baseline_from_bottom"]-image.height if spec["anchor"]["type"]=="bottom_center" else (cell[1]-image.height)//2
        require(y>=0,"Component cannot fit the frozen feet baseline")
        canvas.alpha_composite(image.convert("RGBA"),(x,y));image=canvas
    return runtime(image,target[0],target[1],format_name,allow_non_integer)
