// Run in a native JavaScript engine with the actual app.js text; no Node/browser dependency.
function testAssetUiOptions(source) {
  const prefix = source.slice(0, source.indexOf('const field ='));
  const render = new Function('document', prefix + '\nreturn options;')({querySelector: () => null});
  const html = render(['static', 'draft', ['custom', '自定义'], 'unknown'], 'draft');
  for (const expected of ['value="static"', '静态', 'value="draft" selected', '草稿', '自定义', 'unknown']) {
    if (!html.includes(expected)) throw new Error('Missing option output: ' + expected);
  }
  if (!render([['<unsafe>', '<标签>']]).includes('&lt;标签&gt;')) throw new Error('Unsafe option text');
  return 'PASS: actual dropdown renderer localizes labels, preserves values, selection and escaping';
}
