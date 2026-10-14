"""Single-purpose pause semantics on the existing simulation time/wall watermark."""
from src.core.validation import ValidationError,integer
class WorldPaused(ValidationError):
    def __init__(self):super().__init__('世界已暂停，请先继续运行')
def paused(time):return time.get('world_paused',False)
def require_running(time):
    if paused(time):raise WorldPaused()
def pause(time):
    if time['pending'] is not None:raise ValidationError('请先完成宗门进度续算，再暂停世界')
    return {**time,'world_paused':True}
def resume(time,now_ms):
    integer(now_ms,'resume wall now')
    if not paused(time):return dict(time)
    return {**time,'world_paused':False,'last_settled_at_ms':max(time['last_settled_at_ms'],now_ms)}
