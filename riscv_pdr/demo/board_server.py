"""board_server.py -- serves demo/ and a small swap API from the PYNQ-Z2, for the live mode of index.html.

On the board, as the last cell of sw/demo.ipynb (after cell 1 has loaded the overlay):
    exec(open('demo/board_server.py').read()); start(8000)
then browse to http://<board-ip>:8000.  It reuses the notebook's ctl, dbg, RST, PART and swap() (raw() too, if the timing cell ran),
so there is one Overlay, and the page is same-origin: no CORS, no Jupyter token.

Off the board, with a fake core (for testing the page):
    python3 demo/board_server.py            -> http://localhost:8000
"""
import json, os, random, subprocess, sys, threading, time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

WORDS = (0, 1, 4, 5, 8, 9)
EXPECT_W4 = {'multiplier': 42, 'bitwise': 2}
HEAD = (b'<!doctype html><html lang="en"><meta charset="utf-8">'
        b'<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">')
_lock = threading.Lock()   # one swap at a time; the board has one PCAP
STATS = {'swaps': 0, 'misses': 0, 'recoveries': 0, 'programs': 0, 'frames': 0, 'since': time.time()}   # this server session; /api/soak reports them beside the overnight soak
# Two bundles can sit on the board: B2 (50 MHz, the original) and the 62.5 MHz registered-CFU build. Same file names
# inside each directory, so /lib/firmware is re-primed on every switch. 'dir' is relative to the server's root.
BUILDS = {
    'b2':   {'dir': '.',      'mhz': 50.0, 'label': 'Build B2 · 50 MHz',            'instr': 41},
    '62m5': {'dir': 'b62m5',  'mhz': 62.5, 'label': '62.5 MHz · registered CFU',    'instr': 48},
    'b3':   {'dir': 'b3',     'mhz': 40.0, 'label': 'b3 · 40 MHz · program loader', 'instr': 41, 'loader': True},
}
_build = 'b2'
BASE = os.getcwd()   # the bundle directory (parent of demo/); start() sets it
FAKE = False         # True only for the laptop rehearsal at the bottom of this file

# ---- b3: PS program loader (demo/loader.py).  LDR is None on the B2 / 62.5 MHz bundles, whose bitstreams have no loader. ----
for _d in (os.path.dirname(os.path.abspath(globals().get('__file__', 'demo/x'))), os.path.join(os.getcwd(), 'demo'), 'demo'):
    if os.path.exists(os.path.join(_d, 'loader.py')):
        exec(open(os.path.join(_d, 'loader.py')).read()); break
else:
    raise FileNotFoundError('demo/loader.py not found next to board_server.py')
LDR = None
_prog = None        # {'name', 'imem', 'dmem', 'inputs'}: the image last loaded.  A full bitstream load (the miss recovery) wipes
                    # imem back to program.hex and dmem to zero, so it is kept here and put back.  None = the baked program.
RICK_FB, RICK_CHUNK = 576, 200   # sw/c/rick.c: framebuffer words; pairs per run, so a key frame stops below the stack
_clip = []          # rick frames uploaded by /api/clip: [{'c': clear, 'p': [idx, val, ...]}, ...]


def _read_words():
    """Reset the core, release it, let the program halt, read dmem over AXI GPIO (same as the notebook's run())."""
    ctl.write(RST, 0x7FF); ctl.write(0, 0x7FF); time.sleep(0.001)
    out = {}
    for a in WORDS:
        ctl.write(a, 0x3FF); out[a] = dbg.read()
    return out


def _variant(words):
    return next((v for v, w4 in EXPECT_W4.items() if words[4] == w4), 'unknown')


FULL = {'multiplier': 'config1.bit', 'bitwise': 'config2.bit'}   # full bitstreams with that variant in the slot

if 'raw' not in globals():   # the notebook defines raw() only in its timing cell; the server must not depend on that
    def raw(bit, partial):
        """Kernel-driver load of the .bin that swap()/start() left in /lib/firmware; returns seconds."""
        binf = os.path.basename(bit).replace('.bit', '.bin')
        ctl.write(RST, 0x7FF); open('/sys/class/fpga_manager/fpga0/flags', 'w').write('1' if partial else '0')
        t = time.perf_counter(); open('/sys/class/fpga_manager/fpga0/firmware', 'w').write(binf)
        return time.perf_counter() - t

if 'full' not in globals():
    def full(name):
        # the full bitstream of the build that is loaded (the b3 bundle lives in its own directory; B2 is '.')
        Bitstream(os.path.join(BASE, BUILDS[_build]['dir'], FULL[name])).download()


def _devcfg():
    """devcfg INT_STS / STATUS, for the next miss (healthy baseline 2026-09-26: 0x00020004 / 0x60000f30)."""
    try:
        from pynq import MMIO
        m = MMIO(0xF8007000, 0x100)
        return {'int_sts': hex(m.read(0x0C)), 'status': hex(m.read(0x14))}
    except Exception as e:
        return {'error': repr(e)}


def _probe_value():
    """Run the slot probe and put the user's first imem words back.  dmem 0..1022 is never touched and the core is left in reset,
    so nothing of the user's program re-executes (a re-run of rick.c would apply its last frame's XOR deltas a second time)."""
    LDR.program(PROBE); halted, _ = LDR.run()
    got = LDR.read_dmem(PROBE_WORD, 1)[0] if halted else None
    LDR.hold(); LDR.put_imem((_prog['imem'] if _prog else BAKED)[:len(PROBE)])
    return got


def _verify(to):
    """Is `to` really in the slot?  -> (ok, words, probe).  Without a loader: run the baked program, check dmem[4] (as before).
    With one: the slot probe, because a user program's results are not where the baked program's are."""
    if LDR is None:
        words = _read_words(); return words[4] == EXPECT_W4[to], words, None
    got = _probe_value()
    if _prog is None: LDR.run(); words = _read_words()   # baked program in place: the old UI's words, fresh
    else: words = None
    return got == PROBE_EXPECT[to], words, got


def _reload_prog():
    """After a full bitstream load: put the user's program (and its last inputs) back.  The baked one needs nothing."""
    if LDR is None or _prog is None: return
    LDR.program(_prog['imem'], _prog['dmem'])
    for base, vals in _prog['inputs'].items(): LDR.put_dmem(vals, base)


def _swap(to, path):
    """One swap, with the phases that make it up timed on the board's own clock (perf_counter, ms from the start)."""
    t0 = time.perf_counter(); ph = []

    def mark(name, a, b):
        ph.append({'name': name, 't0_ms': round((a - t0) * 1e3, 3), 'dur_ms': round((b - a) * 1e3, 3)})

    ta = time.perf_counter()
    load_s = swap(to) if path == 'pynq' else raw(PART[to], True)   # both hold the core in reset, then time only the load
    tb = time.perf_counter()
    load_s = min(load_s, tb - ta)   # the load happens inside the call, so it cannot be longer than the call
    ms = load_s * 1e3
    mark('reset', ta, tb - load_s); mark('load', tb - load_s, tb)
    ok, words, probe = _verify(to); tc = time.perf_counter(); mark('readback', tb, tc)
    out = {'to': to, 'path': path, 'ms': ms, 'retried': False, 'build': _active(), 'probe': probe}
    STATS['swaps'] += 1
    if not ok:
        # The miss (2026-09-26): driver reports success, fabric keeps the old variant, and every later
        # partial is ignored too until a full reconfiguration. So: re-read once, then reload the full bitstream.
        STATS['misses'] += 1
        out.update(retried=True, first_words=words, devcfg=_devcfg())
        ok, words, probe = _verify(to); td = time.perf_counter(); mark('re-read', tc, td)
        if not ok:
            full(to); _reload_prog(); ok, words, probe = _verify(to); out['recovery'] = 'full'; out['probe'] = probe; STATS['recoveries'] += 1
            mark('full reload', td, time.perf_counter())
            print(f'[board_server] miss on ->{to} ({path}); devcfg {out["devcfg"]}; full reload -> {"probe" if probe is not None else "w4"}='
                  f'{probe if probe is not None else (words or {}).get(4)}', flush=True)
    out['words'] = words; out['phases'] = ph; out['total_ms'] = round((time.perf_counter() - t0) * 1e3, 3)
    return out


def fclk_mhz():
    """The live FCLK0 from the PS clock registers (the bitstream cannot tell you what the PLLs are really doing)."""
    import pynq
    return float(pynq.ps.Clocks.fclk0_mhz)


def _fclk():
    return fclk_mhz()


def _active():
    """Which build is really loaded, from the live clock. Re-running this module (Run All) resets _build; the hardware does not."""
    try:
        f = fclk_mhz()
        for k in [_build] + [k for k in BUILDS if k != _build]:   # prefer the build we loaded, in case two ever share a clock
            if abs(f - BUILDS[k]['mhz']) < 0.02 * BUILDS[k]['mhz']: return k
    except Exception:
        pass
    return _build


def _md5(path):
    import hashlib
    return hashlib.md5(open(path, 'rb').read()).hexdigest()


def _pl_owner():
    """The bitfile PYNQ last full-loaded, from its state file.  pynq.PL is no use here: a long-lived kernel keeps its own stale copy
    (2026-11-05: ours still said config2.bit while the PL held another user's overlay)."""
    import pynq.pl_server.global_state as g
    try:
        return json.load(open(os.path.join(g.STATE_DIR, 'global_pl_state_.json'))).get('bitfile_name') or ''
    except FileNotFoundError:   # a fresh board: PYNQ has never loaded an overlay, so nothing in the PL is anyone's
        return ''


def _pl_foreign(pl):
    """The board is shared: a design from outside riscv_pdr/ is someone else's work, and a full load would wipe it."""
    return bool(pl) and '/riscv_pdr/' not in pl


_pl_base = None   # the bundle directory whose design this process loaded or adopted; None = nothing of ours in the PL


def _pl_ours():
    """Is the PL still ours?  Checked before every AXI access, not only at load: the board is shared, and an AXI read to a design
    without our GPIOs can hang the PS (2026-11-05: the board went dark mid-Play, 4 minutes after another user's load).
    ponytail: PYNQ writes its state file after a load finishes, so a foreign load still in flight is not seen; only telling the
    other users closes that gap."""
    return FAKE or (_pl_base is not None and os.path.dirname(os.path.normpath(_pl_owner())) == _pl_base)


def _already_loaded(b, base, cfg):
    """True only if THIS build's bitstream was loaded in THIS boot and the PL still runs its clock.  pynq's Overlay.is_loaded() is not
    enough: it said True for both the B2 and the b3 bundle (same file names).  A wrong "yes" would send loader writes to a bitstream
    without the second GPIO, so every condition has to hold, and the cost of a "no" is only a normal full load."""
    try:
        m = json.load(open(os.path.join(base, 'loaded_marker.json')))
        boot = open('/proc/sys/kernel/random/boot_id').read().strip()
        return (m['build'] == b and m['md5'] == _md5(os.path.join(base, 'config1.bit')) and m['boot'] == boot
                and os.path.dirname(os.path.normpath(_pl_owner())) == base
                and abs(fclk_mhz() - cfg['mhz']) < 0.01 * cfg['mhz']
                and open('/sys/class/fpga_manager/fpga0/state').read().strip() == 'operating')
    except Exception:
        return False


def _use_build(b, adopt_ok=False):
    """Full-load build b's static design (this replaces whatever the PL held), re-prime both partials, and check the clock.
    adopt_ok=True (the notebook's setup cell): if _already_loaded(), keep what is in the PL instead of loading it again --
    every full load carries a small wedge risk (1 in 99 in the 2026-10-14 soak), and a kernel restart is routine."""
    global _build, ol, ctl, dbg, PART, LDR, _prog, _pl_base
    cfg = BUILDS[b]
    base = os.path.abspath(os.path.join(BASE, cfg['dir']))
    _pl_base = None
    if not FAKE and not os.path.exists(os.path.join(base, 'config1.bit')):
        raise FileNotFoundError(f'{b}: {base}/config1.bit is not on the board')
    adopted = False
    if not FAKE:
        import pynq
        adopted = adopt_ok and _already_loaded(b, base, cfg)
        if not adopted and _pl_foreign(_pl_owner()) and not globals().get('TAKE_PL'):
            raise RuntimeError(f'the PL holds {_pl_owner()}, not ours. Nothing was loaded. Agree it with its owner, then set TAKE_PL = True and rerun.')
        ol = pynq.Overlay(os.path.join(base, 'config1.bit'), download=not adopted)
        _pl_base = base
        ctl, dbg = ol.axi_gpio_0.channel1, ol.axi_gpio_0.channel2
        LDR = Loader(ol.axi_gpio_0.mmio, ol.axi_gpio_1.mmio) if cfg.get('loader') else None
        PART = {'multiplier': os.path.join(base, 'config1_pblock_cfu_partial.bit'),
                'bitwise': os.path.join(base, 'config2_pblock_cfu_partial.bit')}
    _build, _prog = b, None
    for v in ('multiplier', 'bitwise'):   # ends on the bitwise unit: the video decodes first, then a swap to the multiplier breaks it
        swap(v)
    if adopted and LDR is not None:
        LDR.program(BAKED)   # an adopted design still holds the previous session's program and data: put the baked program back
    got = _fclk()
    words = _read_words()
    ok = abs(got - cfg['mhz']) < 0.01 * cfg['mhz'] and words[4] == EXPECT_W4['bitwise']
    if ok and not FAKE:
        json.dump({'build': b, 'md5': _md5(os.path.join(base, 'config1.bit')), 'fclk_mhz': got,
                   'boot': open('/proc/sys/kernel/random/boot_id').read().strip()}, open(os.path.join(base, 'loaded_marker.json'), 'w'))
    return {'build': b, 'fclk_mhz': got, 'expected_mhz': cfg['mhz'], 'clock_ok': abs(got - cfg['mhz']) < 0.01 * cfg['mhz'],
            'variant': _variant(words), 'words': words, 'ok': ok, 'adopted': adopted}


def _ips():
    """The board's IPv4 addresses, so the page (and whoever runs it) can say where to browse to."""
    try:
        return [a for a in subprocess.run(['hostname', '-I'], capture_output=True, text=True, timeout=3).stdout.split() if '.' in a]
    except Exception:
        return []


def _system():
    """Read-only board snapshot for the page: uptime, load, memory, the busiest processes (name and %CPU only), PL state."""
    def rd(p):
        try: return open(p).read().strip()
        except Exception: return None
    mem = {}
    for line in (rd('/proc/meminfo') or '').splitlines():
        k, _, v = line.partition(':')
        if k in ('MemTotal', 'MemAvailable'): mem[k] = int(v.split()[0]) // 1024
    procs = []
    try:
        ps = subprocess.run(['ps', '-eo', 'pid,pcpu,pmem,comm', '--sort=-pcpu'], capture_output=True, text=True, timeout=3).stdout.splitlines()[1:9]
        procs = [dict(zip(('pid', 'cpu', 'mem', 'name'), l.split(None, 3))) for l in ps]
    except Exception:
        pass
    up = rd('/proc/uptime')
    return {'uptime_s': float(up.split()[0]) if up else None, 'load': (rd('/proc/loadavg') or '').split()[:3], 'mem_mb': mem,
            'procs': procs, 'fpga_state': rd('/sys/class/fpga_manager/fpga0/state'), 'fclk_mhz': _fclk(),
            'build': _active(), 'stats': STATS, 'cores': os.cpu_count(), 'ips': _ips()}


SOAK = 'soak/summary.json'   # written by demo/soak_summary.py from the overnight JSONL
M32 = 0xFFFFFFFF


def _run_loaded(read=(0, 64)):
    """Run the loaded program from pc 0 (dmem kept) and read a window of dmem back."""
    t = time.perf_counter()
    halted, cycles = LDR.run()
    words = LDR.read_dmem(int(read[0]), int(read[1]))
    return {'halted': halted, 'cycles': cycles, 'read': [int(read[0]), int(read[1])], 'words': words,
            'run_ms': round((time.perf_counter() - t) * 1e3, 3), 'slot': _slot_hint()}


def _slot_hint():
    return None   # which unit is in the slot is known to the page from its own swaps and from /api/swap's probe


def _inputs(b):
    return {int(k): [int(v) & M32 for v in vals] for k, vals in (b.get('inputs') or {}).items()}


def _load_program(b):
    """POST /api/program {src | imem[, dmem], inputs?: {word: [values]}, read?: [start, n], run?: bool, name?}.
    Assemble (on the board, with sw/rvasm.py) or take a built image, write it with the core in reset, write the inputs, run."""
    global _prog
    t0 = time.perf_counter(); out = {}
    if 'src' in b:
        sys.path.insert(0, os.path.join(BASE, 'sw')); import rvasm
        imem, listing = rvasm.assemble(b['src']); dmem = []; out['listing'] = [[pc, w, txt] for pc, w, txt in listing]
    else:
        imem, dmem = [int(w) & M32 for w in b['imem']], [int(w) & M32 for w in b.get('dmem', [])]
    inputs = _inputs(b)
    LDR.zero_regs()                                   # registers AND data memory start as in the model: zeros plus the program's image
    LDR.program(imem)
    LDR.put_dmem((dmem + [0] * 1024)[:1024])          # the previous program's data is still in dmem; the model has none of it
    for base, vals in inputs.items(): LDR.put_dmem(vals, base)
    _prog = {'name': b.get('name', 'asm' if 'src' in b else 'prog'), 'imem': imem, 'dmem': dmem, 'inputs': inputs}
    STATS['programs'] += 1
    out.update(name=_prog['name'], instr=len(imem), load_ms=round((time.perf_counter() - t0) * 1e3, 3))
    if b.get('run', True): out.update(_run_loaded(b.get('read', (0, 64))))
    return out


def _rerun(b):
    """POST /api/run {inputs?, read?}: same program, new inputs, core reset and run again."""
    if _prog is None: return 409, {'error': 'no program loaded yet (POST /api/program first)'}
    LDR.zero_regs(); LDR.put_imem(_prog['imem'][:len(CLEAR)])   # the clear routine sat in imem[0:32]: put the program's first words back
    inputs = _inputs(b)
    for base, vals in inputs.items(): LDR.put_dmem(vals, base)
    _prog['inputs'].update(inputs)
    return 200, _run_loaded(b.get('read', (0, 64)))


def _decode_frames(start, n):
    """POST /api/rick?from=&n=: decode n frames of the uploaded clip ON THE CORE (sw/c/rick.c must be the loaded program).
    Per frame, in chunks of at most RICK_CHUNK pairs: write clear/count/pairs, release reset, wait for the halt loop.
    Then read the framebuffer back."""
    if _prog is None or _prog['name'] != 'rick': return 409, {'error': 'load the rick program first (/api/program name=rick)'}
    if not _clip: return 409, {'error': 'no clip uploaded (POST /api/clip)'}
    start = max(0, min(start, len(_clip))); frames = _clip[start:start + max(1, n)]
    shown, cycles, t0 = [], [], time.perf_counter()
    for f in frames:
        if not _pl_ours(): return 409, {'error': f'the PL now holds {_pl_owner()}: stopped before touching it', 'frame': start + len(shown)}
        total = 0
        for k in range(0, max(1, len(f['p'])), 2 * RICK_CHUNK):
            part = f['p'][k:k + 2 * RICK_CHUNK]
            LDR.hold(); LDR.put_dmem([f['c'] if k == 0 else 0, len(part) // 2] + part, RICK_FB)
            halted, cyc = LDR.run(); total += cyc
            if not halted: return 500, {'error': 'the decoder did not reach its halt loop', 'frame': start + len(shown)}
        shown.append(LDR.read_dmem(0, RICK_FB)); cycles.append(total)
    STATS['frames'] += len(frames)
    ms = (time.perf_counter() - t0) * 1e3
    return 200, {'from': start, 'n': len(frames), 'total': len(_clip), 'frames': shown, 'cycles': cycles,
                 'ms': round(ms, 2), 'per_frame_ms': round(ms / len(frames), 2)}


MMIO_PATHS = {'/api/status', '/api/read', '/api/swap', '/api/program', '/api/run', '/api/rick'}   # /api/build checks the PL itself


def api(method, url, body=None):
    """Every /api/ endpoint, as (http status, object). Used by the HTTP handler below and by bridge() for the notebook."""
    u = urlparse(url); q = parse_qs(u.query); body = body or {}
    try:
        if u.path in MMIO_PATHS and not _pl_ours():   # never touch AXI unless our design is still the one in the PL
            return 409, {'error': f'the PL holds {_pl_owner() or "nothing known"}, not this bundle: no AXI access. Reload b3 (agree it with that owner first).'}
        if method == 'GET':
            if u.path == '/api/status':
                with _lock:
                    if LDR is not None and _prog is not None:   # a user program is loaded: ask the slot, do not re-run the program
                        got = _probe_value()
                        return 200, {'fclk_mhz': fclk_mhz(), 'words': None, 'probe': got,
                                     'variant': next((k for k, x in PROBE_EXPECT.items() if x == got), 'unknown')}
                    words = _read_words()
                return 200, {'fclk_mhz': fclk_mhz(), 'variant': _variant(words), 'words': words}
            if u.path == '/api/system':
                return 200, _system()
            if u.path == '/api/builds':
                return 200, {'active': _active(), 'builds': [dict(id=k, **v, available=FAKE or os.path.exists(os.path.join(BASE, v['dir'], 'config1.bit')))
                                                          for k, v in BUILDS.items()]}
            if u.path == '/api/soak':
                try: soak = json.load(open(os.path.join(BASE, SOAK)))
                except Exception: soak = None
                return 200, {'soak': soak, 'session': STATS}
            if u.path == '/api/read':
                with _lock:
                    return 200, {'words': _read_words()}
            if u.path == '/api/loader':
                return 200, {'available': LDR is not None, 'program': _prog and {'name': _prog['name'], 'instr': len(_prog['imem'])},
                             'clip_frames': len(_clip), 'stats': STATS}
        if method == 'POST':
            if u.path == '/api/build':
                b = q.get('b', [''])[0]
                if b not in BUILDS:
                    return 400, {'error': 'b must be ' + '|'.join(BUILDS)}
                with _lock:
                    return 200, _use_build(b)
            if u.path == '/api/swap':
                to, path = q.get('to', [''])[0], q.get('path', ['driver'])[0]
                if to not in PART or path not in ('driver', 'pynq'):   # only the two partials this bundle ships
                    return 400, {'error': 'to must be multiplier|bitwise, path driver|pynq'}
                with _lock:
                    return 200, _swap(to, path)
            if u.path in ('/api/program', '/api/run', '/api/clip', '/api/rick'):
                if LDR is None: return 409, {'error': 'this build has no program loader (load b3)'}
                with _lock:
                    if u.path == '/api/program': return 200, _load_program(body)
                    if u.path == '/api/run': return _rerun(body)
                    if u.path == '/api/clip':
                        _clip[:] = [{'c': int(f['c']), 'p': [int(v) & M32 for v in f['p']]} for f in body['frames']]
                        return 200, {'frames': len(_clip)}
                    return _decode_frames(int(q.get('from', ['0'])[0]), int(q.get('n', ['30'])[0]))
        return 404, {'error': 'not found'}
    except Exception as e:                                  # report to the page instead of a dropped socket
        return (400 if type(e).__name__ == 'AsmError' else 500), {'error': str(e) if type(e).__name__ == 'AsmError' else repr(e)}


def bridge(url, method='GET', body=None):
    """For the notebook embed: the page asks the kernel it is running in, instead of an HTTP port. Prints one marked JSON line.
    body: a JSON string (the page sends JSON.stringify(JSON.stringify(obj)) so the code it executes stays a plain literal)."""
    code, obj = api(method, '/' + url.lstrip('/'), json.loads(body) if isinstance(body, str) else body)
    print('@@JSON@@' + json.dumps(obj) + '@@END@@')


class Handler(SimpleHTTPRequestHandler):
    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == '/favicon.ico':   # browsers ask for it unprompted; an empty answer keeps the console clean
            self.send_response(204); self.end_headers(); return
        if u.path.startswith('/api/'):
            return self._json(*reversed(api('GET', self.path)))
        if u.path in ('/', '/index.html'):   # index.html is written without a doctype/head (Artifact skeleton); add one
            body = HEAD + open(os.path.join(self.directory, 'index.html'), 'rb').read()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        return super().do_GET()

    def do_POST(self):
        n = int(self.headers.get('Content-Length') or 0)
        return self._json(*reversed(api('POST', self.path, json.loads(self.rfile.read(n) or b'{}') if n else None)))

    def log_message(self, fmt, *args):
        if '/api/swap' in self.path or '/api/build' in self.path:
            print('[board_server]', self.path, flush=True)


def start(port=8000, root='demo'):
    """Prime /lib/firmware with both .bin files (the driver path needs them), then serve on a daemon thread."""
    global BASE
    BASE = os.path.dirname(os.path.abspath(root))
    for v in ('multiplier', 'bitwise'):   # ends with the bitwise unit loaded, the demo's starting state
        swap(v)
    srv = ThreadingHTTPServer(('0.0.0.0', port), partial(Handler, directory=os.path.abspath(root)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f'serving {os.path.abspath(root)} on port {port}; words now {_read_words()}')
    print('browse to: ' + '  '.join(f'http://{a}:{port}/' for a in _ips()))
    return srv


if __name__ == '__main__' and 'ol' not in globals():   # exec() in Jupyter is also __main__; ol = real overlay
    # Fake board: demo/fakecore.py runs real RV32I and models the b3 loader, so every program endpoint works here too.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from fakecore import FakeBoard
    FB = FakeBoard('bitwise'); RST = 1 << 10

    class _Ctl:
        def write(self, v, m): FB.m0.write(0, (FB.ctl & ~m) | (v & m))

    class _Dbg:
        def read(self): return FB.m0.read(8)

    ctl, dbg = _Ctl(), _Dbg()
    PART = {'multiplier': 'config1_pblock_cfu_partial.bit', 'bitwise': 'config2_pblock_cfu_partial.bit'}
    FAKE, LDR, _build = True, Loader(FB.m0, FB.m1), 'b3'

    def _load(name, s, partial=True):
        time.sleep(s)
        if partial:
            if random.random() < float(os.environ.get('MISS_RATE', 1 / 65)): FB.stuck = True   # the real fault: ignored until a full reload
            FB.load_partial(name)
        else:
            FB.load_full(name)
        return s

    swap = lambda name: (FB.m0.write(0, RST), _load(name, 0.062 * random.uniform(.97, 1.04)))[1]
    raw = lambda bit, _p: (FB.m0.write(0, RST), _load(next(k for k, b in PART.items() if b == bit), 0.0025 * random.uniform(.9, 1.6)))[1]
    full = lambda name: _load(name, 0.585, partial=False)
    fclk_mhz = lambda: BUILDS[_build]['mhz']
    start(int(os.environ.get('PORT', 8000)), os.path.dirname(os.path.abspath(__file__)))
    threading.Event().wait()
