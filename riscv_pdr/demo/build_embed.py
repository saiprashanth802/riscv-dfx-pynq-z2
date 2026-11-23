"""python3 demo/build_embed.py -> embed.html: index.html with its scripts inlined, shown in an iframe by run_demo.ipynb.

Two cells. Cell 1 loads the overlay and the server code (no HTTP port). Cell 2 shows the page in an iframe; its JavaScript
talks to the board through the notebook's own, already-authenticated kernel (parent.Jupyter.notebook.kernel). Run All.
"""
import html, json, os
here = os.path.dirname(os.path.abspath(__file__)); root = os.path.dirname(here)
page = open(f'{here}/index.html').read()
import subprocess, sys
subprocess.run([sys.executable, f'{here}/build_apps.py'], check=True)          # apps.js: program images, examples, the rick clip
for name in ('sim', 'apps', 'panels'):                                          # inline the scripts the page loads from files
    tag = f'<script src="{name}.js"></script>'
    assert tag in page, tag
    page = page.replace(tag, '<script>\n' + open(f'{here}/{name}.js').read().replace('</script', '<\\/script') + '\n</script>')
doc = ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">' + page)
open(f'{here}/embed.html', 'w').write(doc)

