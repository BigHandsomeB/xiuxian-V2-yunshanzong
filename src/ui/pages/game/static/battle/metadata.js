// Runtime-only metadata. Never infer a grid or load Source/Master assets.
const number = (v, min = -Infinity) => Number.isFinite(v) && v >= min;
export function runtimeURL(value) {
  if (typeof value !== 'string' || !value.trim() || /[\s\\]/.test(value)) throw Error('Invalid runtime URL');
  if (/^[a-z][a-z0-9+.-]*:/i.test(value) && !/^https?:\/\/[^/]+/i.test(value)) throw Error('Invalid runtime URL');
  const authority = value.match(/^(?:https?:)?\/\/([^/?#]+)/i);
  if (authority || !/^\/(?:game(?:\/review)?|play)\/runtime\//.test(value) || /(?:\.\.|%2e|%2f|%5c)/i.test(value)) throw Error('Invalid runtime URL');
  return value;
}
export function validateSprite(input) {
  if (!input || !number(input.width, 1) || !number(input.height, 1)) throw Error('Explicit runtime dimensions required');
  const { anchor, actions } = input;
  if (!anchor || !number(anchor.x, 0) || !number(anchor.y, 0) || anchor.x > input.width || anchor.y > input.height) throw Error('Invalid anchor');
  if (!actions || !Object.keys(actions).length) throw Error('Actions required');
  const result = { width: input.width, height: input.height, anchor: { ...anchor }, static: input.static===true, authoredFacing: input.authoredFacing, actions: {} };
  for (const [name, action] of Object.entries(actions)) {
    if (!Number.isInteger(action.frameCount) || action.frameCount < 1 || action.frameCount > 256 || !Array.isArray(action.frames) || action.frames.length !== action.frameCount || typeof action.loop !== 'boolean') throw Error('Invalid frame count/loop');
    const durations = Array.isArray(action.duration) ? [...action.duration] : Array(action.frameCount).fill(action.duration);
    if (durations.length !== action.frameCount || !durations.every(v => number(v, 1))) throw Error('Invalid frame duration');
    const frames = action.frames.map(frame => {
      const url = runtimeURL(frame.url);
      if (!number(frame.sheetWidth, 1) || !number(frame.sheetHeight, 1) || !number(frame.x, 0) || !number(frame.y, 0) || frame.x + input.width > frame.sheetWidth || frame.y + input.height > frame.sheetHeight) throw Error('Invalid explicit frame rectangle');
      return { ...frame, url };
    });
    const triggers = (action.triggers || []).map(t => {
      if (!Number.isInteger(t.frame) || t.frame < 0 || t.frame >= action.frameCount || typeof t.effect !== 'string' || !t.effect || !number(t.x ?? 0) || !number(t.y ?? 0)) throw Error('Invalid effect trigger');
      return { ...t, x: t.x ?? 0, y: t.y ?? 0 };
    });
    result.actions[name] = { frameCount: action.frameCount, frames, durations, loop: action.loop, triggers };
  }
  return result;
}
export function frameAt(action, elapsed) {
  const total = action.durations.reduce((a, b) => a + b, 0);
  let time = action.loop ? elapsed % total : Math.min(elapsed, total - 0.001);
  for (let i = 0; i < action.frameCount; i++) { if (time < action.durations[i]) return i; time -= action.durations[i]; }
  return action.frameCount - 1;
}
