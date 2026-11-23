#!/usr/bin/env python3
"""preview.py rick.json [-o sheet.png] [--gif out.gif] [--n 12]  -- what the core's output will look like: decode the XOR-delta frames
exactly as the core does (encode.decode), then draw a contact sheet (and optionally a gif) at 6x nearest-neighbour."""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from encode import decode, W, H
from PIL import Image

def img(fb, s=6):
    im = Image.new('L', (W, H))
    im.putdata([255 if (fb[2 * y + (x >> 5)] >> (x & 31)) & 1 else 12 for y in range(H) for x in range(W)])
    return im.resize((W * s, H * s), Image.NEAREST)

a = argparse.ArgumentParser(); a.add_argument('json'); a.add_argument('-o', default='sheet.png'); a.add_argument('--gif'); a.add_argument('--n', type=int, default=12)
a = a.parse_args()
R = json.load(open(a.json)); frames = decode([(f['c'], f['p']) for f in R['frames']])
idx = [round(i * (len(frames) - 1) / (a.n - 1)) for i in range(a.n)]
cols = 4; rows = (a.n + cols - 1) // cols; s = 6; pad = 8
sheet = Image.new('L', (cols * (W * s + pad) + pad, rows * (H * s + pad) + pad), 60)
for k, i in enumerate(idx): sheet.paste(img(frames[i], s), (pad + (k % cols) * (W * s + pad), pad + (k // cols) * (H * s + pad)))
sheet.save(a.o); print(f'{len(frames)} frames; sheet of frames {idx} -> {a.o}')
if a.gif:
    ims = [img(f, 4) for f in frames]; ims[0].save(a.gif, save_all=True, append_images=ims[1:], duration=int(1000 / R['fps']), loop=0); print('gif ->', a.gif)
