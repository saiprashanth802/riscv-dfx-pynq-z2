#!/usr/bin/env python3
"""rebirth.py -- the board clip: an original 8-colour animation, drawn here, encoded for sw/c/rick.c.

    python3 sw/rick/rebirth.py [-o sw/rick/rebirth.json]     # also writes rebirth_preview.gif and rebirth_preview_sheet.png

The face is the real firmware face, exported from the portfolio's face engine into sw/rick/face/.  The story follows a CRT:
it switches off (the picture collapses to a line, then a dot), the signal passes through green phosphor, a violet arc and
yellow collider tracks, then the tube switches back on and the face returns, ending on a test card that uses all 8 colours.
Nothing flashes the whole field.
"""
import argparse, json, math, os, random, sys
from PIL import Image, ImageDraw
here = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, here)
from encode import W, H, encode, decode, rgb_words

K, R, G, B, C, M, Y, WH = (0,0,0), (1,0,0), (0,1,0), (0,0,1), (0,1,1), (1,0,1), (1,1,0), (1,1,1)
FACE_H = 60

def canvas(): return Image.new('RGB', (W, H), K)
def px(c): return tuple(255 * v for v in c)

def face(name):
    """The sprite at 96 x 60, hard-thresholded, as a cyan-on-black image centred on the frame."""
    src = Image.open(os.path.join(here, 'face', name + '.png')).convert('L').resize((W, FACE_H), Image.LANCZOS)
    m = src.point(lambda v: 255 if v > 70 else 0)
    im = canvas(); im.paste(Image.new('RGB', (W, FACE_H), px(C)), (0, (H - FACE_H) // 2), m)
    return im

def squash(im, sy, sx=1.0):
    """The collapse of a CRT raster: height to sy, width to sx, about the centre."""
    h, w = max(1, round(H * sy)), max(1, round(W * sx))
    out = canvas(); out.paste(im.resize((w, h), Image.NEAREST), ((W - w) // 2, (H - h) // 2))
    return out

def graticule(d):
    for x in range(8, W, 16):
        for y in range(8, H, 16): d.point((x, y), fill=px(B))

def trace(n, total):
    im = canvas(); d = ImageDraw.Draw(im); graticule(d)
    amp = 3 + 22 * n / total
    pts = [(x, H / 2 + amp * math.sin(x / 7 + n * .55) * math.cos(x / 31)) for x in range(W)]
    d.line(pts, fill=px(G), width=1)
    return im

def arc(n):
    rng = random.Random(n // 2 + 7)
    im = canvas(); d = ImageDraw.Draw(im)
    d.rectangle((40, 0, 55, 3), fill=px(R)); d.rectangle((40, H - 4, 55, H - 1), fill=px(R))
    for k, col in ((0, M), (1, M), (2, WH)):
        x, pts = W / 2, []
        for y in range(4, H - 3, 5):
            x += rng.uniform(-7, 7) * (1 if k < 2 else .5); x = min(W - 6, max(5, x)); pts.append((x, y))
        d.line(pts, fill=px(col), width=1)
    return im

def tracks(n, total):
    rng = random.Random(3)
    im = canvas(); d = ImageDraw.Draw(im); t = (n + 1) / total
    for i in range(12):
        a0, bend, col = rng.uniform(0, 6.283), rng.uniform(-.05, .05), (Y, Y, R, G)[i % 4]
        x, y, a, pts = W / 2, H / 2, a0, [(W / 2, H / 2)]
        for s in range(int(46 * t)):
            a += bend; x += math.cos(a) * 1.4; y += math.sin(a) * 1.4; pts.append((x, y))
        if len(pts) > 1: d.line(pts, fill=px(col), width=1)
    d.rectangle((W // 2 - 1, H // 2 - 1, W // 2 + 1, H // 2 + 1), fill=px(WH))
    return im

def test_card():
    im = face('joy'); d = ImageDraw.Draw(im)
    bars = (WH, Y, C, G, M, R, B, K); bw = W // 8
    for i, c in enumerate(bars): d.rectangle((i * bw, H - 7, (i + 1) * bw - 1, H - 1), fill=px(c))
    return im

def frames():
    out, happy, joy = [], face('happy'), face('joy')
    out += [face('neutral')] * 3 + [happy] * 7 + [face('surprised')] * 4
    for k in range(6): out.append(squash(happy, 1 - (k + 1) / 6.2))                  # off: collapse to a line
    for k in range(4): out.append(squash(Image.new('RGB', (W, H), px(WH)), .02, 1 - (k + 1) / 4.3))   # the line shrinks to a dot
    out += [trace(n, 12) for n in range(12)]
    out += [arc(n) for n in range(10)]
    out += [tracks(n, 10) for n in range(10)]
    for k in range(4): out.append(squash(Image.new('RGB', (W, H), px(WH)), .02, (k + 1) / 4))         # on: a dot opens to a line
    for k in range(6): out.append(squash(joy, (k + 1) / 6))                          # the line unfolds into the face
    out += [joy] * 6 + [test_card()] * 18
    return out

def to_words(im):
    d = im.convert('RGB').load()
    return rgb_words([[tuple(1 if v > 127 else 0 for v in d[x, y]) for x in range(W)] for y in range(H)])

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('-o', '--out', default=os.path.join(here, 'rebirth.json')); ap.add_argument('--key', type=int, default=10)
    a = ap.parse_args()
    ims = frames(); ref = [to_words(i) for i in ims]; enc = encode(ref, a.key)
    assert decode(enc) == ref, 'decode != source'
    json.dump({'w': W, 'h': H, 'words': len(ref[0]), 'fps': 10, 'key': a.key, 'ref': ref, 'frames': [{'c': c, 'p': p} for c, p in enc]},
              open(a.out, 'w'), separators=(',', ':'))
    pairs = sorted(len(p) // 2 for _, p in enc)
    print(f'rebirth: {len(ims)} frames, {len(ims) / 10:.1f} s; pairs per frame min {pairs[0]} median {pairs[len(pairs) // 2]} max {pairs[-1]}; {os.path.getsize(a.out):,} B')
    big = [i.resize((W * 4, H * 4), Image.NEAREST) for i in ims]
    big[0].save(os.path.join(here, 'rebirth_preview.gif'), save_all=True, append_images=big[1:], duration=100, loop=0)
    picks = ims[::max(1, len(ims) // 24)][:24]; sheet = Image.new('RGB', (6 * 196, 4 * 132), (40, 40, 40))
    for n, i in enumerate(picks): sheet.paste(i.resize((192, 128), Image.NEAREST), ((n % 6) * 196 + 2, (n // 6) * 132 + 2))
    sheet.save(os.path.join(here, 'rebirth_preview_sheet.png'))

if __name__ == '__main__': main()
