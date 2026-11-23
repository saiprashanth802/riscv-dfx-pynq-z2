#!/usr/bin/env python3
"""encode.py -- turn a short video clip into XOR-delta frames the RISC-V core can decode through the CFU.

    python3 sw/rick/encode.py clip.mp4 -o sw/rick/rick.json [--fps 10] [--seconds 8] [--key 10]
    python3 sw/rick/encode.py --selfcheck

Frame format: 96 x 64, three 1 bpp planes (R, G, B: a CRT's three guns, so 8 colours), 192 words each, 576 in all; pixel
(x, y) of plane c is bit (x & 31) of word 192*c + 3*y + (x >> 5), 1 = on.  A gray clip sets all three planes alike.  A frame
is stored as `clear` plus (idx, val) pairs; the core (sw/c/rick.c) does
    if clear: fb[:] = 0
    for (idx, val) in pairs: fb[idx] = cfu_call(2, fb[idx], val)        # fn 2 of the bitwise unit is XOR
A key frame is clear + the frame's non-zero words, so it also repairs a framebuffer that went wrong (e.g. while the
multiplier was in the slot).  Every other frame is the XOR against the previous one.  A frame can have up to 576 pairs, more
than dmem has room for beside the framebuffer, so the PS feeds it to the core in chunks of at most 200 pairs.

The original animation comes from sw/rick/rebirth.py.  Needs ffmpeg and Pillow for a video clip.
"""
import argparse, json, os, subprocess, sys, tempfile

W, H, PLANE = 96, 64, 192
WORDS = 3 * PLANE

def grab(clip, fps, seconds, vf_extra):
    """ffmpeg -> list of 8-bit gray frames (bytes, W*H each), centre-cropped to 4:3."""
    vf = f'fps={fps},scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H}' + (',' + vf_extra if vf_extra else '')
    cmd = ['ffmpeg', '-v', 'error', '-i', clip, '-vf', vf, '-pix_fmt', 'gray', '-f', 'rawvideo']
    if seconds: cmd += ['-t', str(seconds)]
    raw = subprocess.run(cmd + ['-'], check=True, stdout=subprocess.PIPE).stdout
    n = len(raw) // (W * H)
    if n == 0: sys.exit('encode: ffmpeg produced no frames')
    return [raw[k * W * H:(k + 1) * W * H] for k in range(n)]

def to_words(gray, cutoff=3, threshold=False):
    """8-bit gray -> 576 words (white: all three planes alike).  Stretch the contrast first (cutoff = % clipped at each end; 0 = off): a flat grey source dithers to mid-grey
    noise otherwise.  Then Floyd-Steinberg to 1 bit (Pillow's convert('1')), or a hard threshold at the frame's median (--threshold)."""
    from PIL import Image, ImageOps
    im = Image.frombytes('L', (W, H), gray)
    if cutoff: im = ImageOps.autocontrast(im, cutoff=cutoff)
    if threshold:
        t = sorted(gray)[len(gray) // 2]; im = im.point(lambda p: 255 if p > t else 0)
    px = im.convert('1').convert('L').tobytes()   # one byte per pixel, 0 or 255
    words = [0] * WORDS
    for y in range(H):
        for x in range(W):
            if px[y * W + x]:
                for c in range(3): words[c * PLANE + 3 * y + (x >> 5)] |= 1 << (x & 31)
    return words

def rgb_words(px):
    """px[y][x] = (r, g, b), each 0 or 1 -> 576 words."""
    words = [0] * WORDS
    for y in range(H):
        for x in range(W):
            for c in range(3):
                if px[y][x][c]: words[c * PLANE + 3 * y + (x >> 5)] |= 1 << (x & 31)
    return words

def encode(frames, key):
    """frames: list of 576-word lists -> list of (clear, [idx, val, idx, val, ...])."""
    out, prev = [], [0] * WORDS
    for n, f in enumerate(frames):
        if n % key == 0:
            out.append((1, [v for i, w in enumerate(f) if w for v in (i, w)]))
        else:
            out.append((0, [v for i in range(WORDS) if f[i] ^ prev[i] for v in (i, f[i] ^ prev[i])]))
        prev = f
    return out

def decode(enc):
    """Exactly what the core does, in Python."""
    fb, frames = [0] * WORDS, []
    for clear, pairs in enc:
        if clear: fb = [0] * WORDS
        for k in range(0, len(pairs), 2): fb[pairs[k]] ^= pairs[k + 1]
        frames.append(list(fb))
    return frames

def selfcheck():
    with tempfile.TemporaryDirectory() as d:
        clip = os.path.join(d, 'test.mp4')
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=10:duration=3',
                        '-pix_fmt', 'yuv420p', clip], check=True)
        frames = [to_words(g) for g in grab(clip, 10, 0, '')]
    assert len(frames) == 30, len(frames)
    assert any(any(f) for f in frames) and any(f != frames[0] for f in frames[1:]), 'test clip is blank or still'
    for key in (1, 7, 10, 100):
        enc = encode(frames, key)
        assert decode(enc) == frames, f'decode != source (key={key})'
        assert all(len(p) <= 2 * WORDS for _, p in enc)
        assert all(c == (n % key == 0) for n, (c, _) in enumerate(enc))
    # a framebuffer corrupted mid-clip is repaired by the next key frame, and not before
    enc = encode(frames, 10)
    fb = [0xA5A5A5A5] * WORDS
    for n, (clear, pairs) in enumerate(enc[10:], 10):
        if clear: fb = [0] * WORDS
        for k in range(0, len(pairs), 2): fb[pairs[k]] ^= pairs[k + 1]
        assert (fb == frames[n]) == (n == 10), f'frame {n}'
        if n == 10: break
    print('rick encoder selfcheck: OK (30 frames, decode == source for key 1/7/10/100, key frame repairs corruption)')

def synthetic(out, key=10):
    """A 3 s test pattern, encoded like a real clip, plus the source frames ('ref') for end-to-end checks of the decoder."""
    with tempfile.TemporaryDirectory() as d:
        clip = os.path.join(d, 'test.mp4')
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=10:duration=3',
                        '-pix_fmt', 'yuv420p', clip], check=True)
        frames = [to_words(g) for g in grab(clip, 10, 0, '')]
    enc = encode(frames, key)
    json.dump({'w': W, 'h': H, 'words': WORDS, 'fps': 10, 'key': key, 'ref': frames,
               'frames': [{'c': c, 'p': p} for c, p in enc]}, open(out, 'w'), separators=(',', ':'))

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('clip', nargs='?'); ap.add_argument('-o', '--out', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'rick.json'))
    ap.add_argument('--fps', type=int, default=10); ap.add_argument('--seconds', type=float, default=0, help='0 = whole clip')
    ap.add_argument('--key', type=int, default=10, help='key frame every N frames'); ap.add_argument('--vf', default='', help='extra ffmpeg filters, e.g. eq=contrast=1.4')
    ap.add_argument('--cutoff', type=float, default=3, help='auto-contrast clip %%, 0 = off'); ap.add_argument('--threshold', action='store_true', help='hard threshold instead of dithering')
    ap.add_argument('--selfcheck', action='store_true'); ap.add_argument('--synthetic', metavar='OUT', help='encode a test pattern (with reference frames) instead of a clip')
    a = ap.parse_args()
    if a.selfcheck: return selfcheck()
    if a.synthetic: return synthetic(a.synthetic)
    if not a.clip: ap.error('give a clip, or --selfcheck')
    frames = [to_words(g, a.cutoff, a.threshold) for g in grab(a.clip, a.fps, a.seconds, a.vf)]
    enc = encode(frames, a.key)
    assert decode(enc) == frames
    json.dump({'w': W, 'h': H, 'words': WORDS, 'fps': a.fps, 'key': a.key,
               'frames': [{'c': c, 'p': p} for c, p in enc]}, open(a.out, 'w'), separators=(',', ':'))
    pairs = [len(p) // 2 for _, p in enc]
    print(f'{len(enc)} frames @ {a.fps} fps -> {a.out} ({os.path.getsize(a.out):,} B); pairs/frame mean {sum(pairs) / len(pairs):.0f}, max {max(pairs)}')

if __name__ == '__main__':
    main()
