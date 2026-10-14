"""Static CSS contracts only: phone layout/painting remains separate acceptance."""
import re,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/'src/ui/pages/game'
class UIStyleTests(unittest.TestCase):
 def test_shared_variables_complete_and_no_legacy_palette(self):
  files=[ROOT/'static'/name for name in ['theme.css','game.css','battle/battle.css','review.css']]
  css='\n'.join(p.read_text() for p in files)
  definitions=set(re.findall(r'(--[\w-]+)\s*:',css));uses=set(re.findall(r'var\((--[\w-]+)',css))
  self.assertFalse((uses-definitions)-{'--battle-primary','--battle-secondary'}) # Optional art variables injected by battle-skin.js.
  self.assertNotRegex(css,r'--(?:tone|night)-');self.assertNotRegex(css,r'font(?:-size)?:\s*(?:9|10|11)px')
  for p in files:self.assertEqual(p.read_text().count('{'),p.read_text().count('}'))
 def test_palette_dark_mode_and_quality_contrast(self):
  css=(ROOT/'static/theme.css').read_text();roots=re.findall(r':root(?:\[data-theme=dark\])?\{([^{}]*)\}',css)
  self.assertEqual(len(roots),2)
  def luminance(hex):
   rgb=[int(hex[i:i+2],16)/255 for i in (1,3,5)];linear=[n/12.92 if n<=.04045 else ((n+.055)/1.055)**2.4 for n in rgb];return sum(n*w for n,w in zip(linear,[.2126,.7152,.0722]))
  def contrast(a,b):
   x,y=sorted([luminance(a),luminance(b)]);return (y+.05)/(x+.05)
  for root in roots:
   colors=dict(re.findall(r'(--[\w-]+):\s*(#[a-f0-9]{6})(?:;|$)',root))
   for fg,bg in [('ink','surface'),('muted','surface'),('on-accent','accent'),('header-ink','header-bg'),('danger','danger-bg')]:self.assertGreaterEqual(contrast(colors['--'+fg],colors['--'+bg]),4.5,(fg,bg))
   for quality in ['uncommon','rare','epic','legendary']:self.assertGreaterEqual(contrast(colors['--q-'+quality],colors['--surface']),3,quality)
 def test_shell_single_header_and_accessible_controls(self):
  html=(ROOT/'index.html').read_text();self.assertLess(html.index('id="world-bar"'),html.index('</header>'))
  css=(ROOT/'static/game.css').read_text();self.assertNotIn('calc(122px',css);self.assertNotIn('calc(66px',css)
  self.assertIn('top:var(--header-h)',css);self.assertIn('.danger-action',css);self.assertIn('.item-icon::after',css)
  self.assertFalse(any(selector.strip()=='.primary' and 'width:100%' in body for selector,body in re.findall(r'([^{}]+)\{([^{}]*)\}',css)), 'Bare primary controls must not occupy a full row')
  battle=(ROOT/'static/battle/battle.css').read_text();self.assertIn('aspect-ratio:16/9',battle);self.assertIn('repeat(3,minmax(0,1fr))',battle)
  self.assertNotIn('progressbar',battle);self.assertIn('font:var(--text-min)/1.5 var(--font-ui)',battle)
