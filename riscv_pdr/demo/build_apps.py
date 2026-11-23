"""python3 demo/build_apps.py  ->  demo/apps.js   (window.APPS for index.html; inlined into the notebook embed by build_embed.py)

APPS.asm   assembly examples (source text)
APPS.c     built program images {imem, dmem} + their C source, from sw/c/build.sh (needs the cross compiler; absent = {})
APPS.clip  the clip: sw/rick/rebirth.json (python3 sw/rick/rebirth.py) if it exists, else a test pattern (flagged `test`).
"""
import json, os, subprocess, sys, tempfile
here = os.path.dirname(os.path.abspath(__file__)); root = os.path.dirname(here)
sc = os.path.join(root, 'sw', 'c')

apps = {'asm': {}, 'c': {}, 'clip': None}
sys.path.insert(0, os.path.join(root, 'sw')); import rvasm
for name, f in (('sum10', 'sum10.s'),):
    src = open(os.path.join(root, 'sw', 'asm', f)).read()
    apps['asm'][name] = {'src': src, 'imem': rvasm.assemble(src)[0]}   # typed edits are assembled on the board (sw/rvasm.py)

for name, flags, blurb in (('calc', [], 'a × b and popcount(a): both are libcalls that land in the slot'),
                           ('bench', [], 'software shift-add multiply vs the slot, counted in clock cycles'),
                           ('rick', ['--no-cfu-libcalls'], 'the video decoder')):
    try:
        subprocess.run([os.path.join(sc, 'build.sh'), os.path.join(sc, name + '.c')] + flags, check=True, capture_output=True)
        img = json.load(open(os.path.join(sc, 'out', name + '.json')))
        apps['c'][name] = {'imem': img['imem'], 'dmem': img['dmem'], 'src': open(os.path.join(sc, name + '.c')).read(), 'blurb': blurb}
    except (OSError, subprocess.CalledProcessError) as e:
        print(f'build_apps: {name} not built ({getattr(e, "stderr", e)!s:.120}); the page will not offer it', file=sys.stderr)

clip = next((p for p in (os.path.join(root, 'sw', 'rick', f) for f in ("rebirth.json",)) if os.path.exists(p)), None)
if clip is None:
    clip = os.path.join(tempfile.mkdtemp(), 'synthetic.json')
    subprocess.run([sys.executable, os.path.join(root, 'sw', 'rick', 'encode.py'), '--synthetic', clip], check=True)
    test = True
else:
    test = False
c = json.load(open(clip)); c.pop('ref', None); c['test'] = test
apps['clip'] = c

js = 'window.APPS = ' + json.dumps(apps, separators=(',', ':')) + ';\n'
open(os.path.join(here, 'apps.js'), 'w').write(js)
print(f'apps.js {len(js):,} B: asm {list(apps["asm"])}, c {list(apps["c"])}, clip {len(c["frames"])} frames' + (' (TEST PATTERN)' if test else ''))
