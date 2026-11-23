# python3 demo/server_check.py -- board_server._swap against a fake board that wedges like the 2026-09-26 miss
import time
g = {'__name__': 'check'}
exec(open(__file__.replace('server_check.py', 'board_server.py')).read(), g)
assert callable(g['fclk_mhz']) and callable(g['bridge']), 'the module alone must provide fclk_mhz and bridge (notebook mode never calls start())'
st = {'v': 'multiplier', 'addr': 0, 'stuck': False, 'loads': 0}
MEM = {'multiplier': {0: 13, 1: 1, 4: 42, 5: 0, 8: 0, 9: 1}, 'bitwise': {0: 13, 1: 1, 4: 2, 5: 6, 8: 1, 9: 0x10000}}


class Ctl:
    def write(self, v, m): st['addr'] = v & 0x3FF


class Dbg:
    def read(self): return MEM[st['v']].get(st['addr'], 0)


def partial_load(name):
    st['loads'] += 1
    if st['loads'] == 2: st['stuck'] = True      # second partial wedges the engine: ignored until a full reload
    if not st['stuck']: st['v'] = name
    time.sleep(0.0025)                           # the real load takes the time it reports
    return 0.0025


def full(name): st['stuck'] = False; st['v'] = name


g.update(ctl=Ctl(), dbg=Dbg(), RST=1 << 10, PART={'multiplier': 'm.bit', 'bitwise': 'b.bit'},
         swap=partial_load, raw=lambda bit, p: partial_load('multiplier' if bit == 'm.bit' else 'bitwise'), full=full)
r1 = g['_swap']('bitwise', 'driver');    assert r1['words'][4] == 2 and not r1['retried'], r1
r2 = g['_swap']('multiplier', 'driver'); assert r2['recovery'] == 'full' and r2['words'][4] == 42 and r2['first_words'][4] == 2, r2
r3 = g['_swap']('bitwise', 'pynq');      assert r3['words'][4] == 2 and not r3['retried'], r3
print('server_check: ok')

# ---- phases, builds, system, soak (added with the live-timeline / build-toggle / reliability panels) ----
st.update(v='multiplier', stuck=False, loads=0)
r = g['_swap']('bitwise', 'driver')
names = [p['name'] for p in r['phases']]
assert names == ['reset', 'load', 'readback'], names
assert all(p['dur_ms'] >= 0 for p in r['phases']) and 2.4 <= r['phases'][1]['dur_ms'] <= 2.5, r['phases']   # load = what raw() reported
assert r['phases'][0]['t0_ms'] <= r['phases'][1]['t0_ms'] <= r['phases'][2]['t0_ms'], 'phases are in order'
st.update(v='multiplier', stuck=False, loads=1)      # the next partial wedges: the miss path must show its recovery phases
r = g['_swap']('bitwise', 'driver')
assert [p['name'] for p in r['phases']] == ['reset', 'load', 'readback', 're-read', 'full reload'], r['phases']
assert r['recovery'] == 'full' and r['words'][4] == 2 and g['STATS']['misses'] >= 2 and g['STATS']['recoveries'] >= 2, (r, g['STATS'])

g['fclk_mhz'] = lambda: 50.0
sysd = g['_system']()
assert set(sysd) >= {'uptime_s', 'load', 'mem_mb', 'procs', 'fpga_state', 'fclk_mhz', 'build', 'stats'}, sysd.keys()
assert all(set(p) == {'pid', 'cpu', 'mem', 'name'} for p in sysd['procs']), 'process rows carry names only, never command lines'

g.update(FAKE=True, fclk_mhz=lambda: g['BUILDS'][g['_build']]['mhz'])
for b, mhz in (('62m5', 62.5), ('b2', 50.0)):
    out = g['_use_build'](b)
    assert out['clock_ok'] and out['ok'] and out['fclk_mhz'] == mhz and out['variant'] == 'bitwise', out
g['fclk_mhz'] = lambda: 31.25                        # the PLL trap: bitstream says 62.5, board runs something else
bad = g['_use_build']('62m5')
assert not bad['clock_ok'] and not bad['ok'], 'a clock that does not match the build must be reported, not hidden'
g['_build'] = 'b2'; g['fclk_mhz'] = lambda: 62.5
assert g['_active']() == '62m5', 'active build comes from the live clock, not the remembered one'
J = '/home/xilinx/jupyter_notebooks/'
assert g['_pl_foreign'](J + 'someone/overlays/x.bit') and not g['_pl_foreign'](J + 'riscv_pdr/b3/./config2.bit') and not g['_pl_foreign'](''), 'only a design outside riscv_pdr/ blocks a full load'
print('server_check: phases, builds, system ok')

# ---- b3: program loader through the server, against demo/fakecore.py ------------------------------------------------------
import json, os, subprocess, sys
here = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, here)
from fakecore import FakeBoard
FB = FakeBoard('multiplier'); RSTB = 1 << 10


class FCtl:
    def write(self, v, m): FB.m0.write(0, (FB.ctl & ~m) | (v & m))


class FDbg:
    def read(self): return FB.m0.read(8)


def f_swap(name): FB.m0.write(0, RSTB); FB.load_partial(name); return 0.0025
def f_full(name): FB.load_full(name)


g.update(ctl=FCtl(), dbg=FDbg(), RST=RSTB, swap=f_swap, raw=lambda bit, p: f_swap('multiplier' if bit == 'm.bit' else 'bitwise'), full=f_full,
         LDR=g['Loader'](FB.m0, FB.m1), _prog=None, _build='b3', FAKE=True, fclk_mhz=lambda: 50.0)
post = lambda path, body=None: g['api']('POST', path, body)
api_get = lambda path: g['api']('GET', path)

# status with a user program loaded must not re-run it (rick's XOR deltas would apply twice and corrupt the picture):
# the program counts its own executions in dmem word 500
counter = 'lw x1, 2000(x0)\naddi x1, x1, 1\nsw x1, 2000(x0)\ndone: j done'
code, o = post('/api/program', {'src': counter, 'name': 'counter', 'read': [500, 1]}); assert o['words'] == [1], o
for _ in range(3):
    code, o = api_get('/api/status')
    assert code == 200 and o['variant'] == 'multiplier' and o['words'] is None and o['probe'] == 42, (code, o)
code, o = post('/api/run', {'read': [500, 1]}); assert o['words'] == [2], ('status re-ran the program', o)
g['_prog'] = None; FB.load_full('multiplier'); g['LDR'] = g['Loader'](FB.m0, FB.m1)

# no loader on B2/62.5: refused, not guessed at
saved = g['LDR']; g['LDR'] = None
assert post('/api/program', {'src': 'j 0'})[0] == 409; g['LDR'] = saved

# baked program in place: the slot probe replaces the dmem[4] check, and the old UI still gets its words
r = g['_swap']('bitwise', 'driver')
assert r['probe'] == 2 and not r['retried'] and r['words'][4] == 2 and r['words'][5] == 6, r
assert FB.imem[:41] == g['BAKED'][:41], 'the probe must put imem back'

# registers carry over between runs on the real core: the server zeroes them before every user program, so a program that reads an
# unset register is deterministic and equals the model (which starts at zero)
code, o = post('/api/program', {'src': 'addi x1, x0, 77\nsw x1, 0(x0)\ndone: j done'}); assert o['words'][0] == 77
code, o = post('/api/program', {'src': 'add x3, x3, x1\nsw x3, 0(x0)\ndone: j done'}); assert o['words'][0] == 0, ('registers leaked between programs', o)
code, o = post('/api/run', {}); assert o['words'][0] == 0, ('re-run must also start from zeros', o)

# data memory persists too: a program must not see the previous program's results in words it never wrote
code, o = post('/api/program', {'src': 'addi x1, x0, 5\nsw x1, 4(x0)\nsw x1, 8(x0)\nsw x1, 12(x0)\ndone: j done', 'read': [0, 4]}); assert o['words'] == [0, 5, 5, 5], o
code, o = post('/api/program', {'src': 'addi x1, x0, 9\nsw x1, 0(x0)\ndone: j done', 'read': [0, 4]}); assert o['words'] == [9, 0, 0, 0], ('dmem leaked from the previous program', o)

# assemble + run on the "board"; assembler errors come back as 400 with the line
src = open(os.path.join(here, '..', 'sw', 'asm', 'sum10.s')).read()
code, o = post('/api/program', {'src': src})
assert code == 200 and o['halted'] and o['cycles'] == 35 and o['words'][0] == 55 and o['instr'] == 8 and len(o['listing']) == 8, (code, o)
code, e = post('/api/program', {'src': 'addi x1,x0,1\nlb x2,0(x1)'}); assert code == 400 and 'line 2' in e['error'] and 'word-only' in e['error'], (code, e)
assert g['_prog']['name'] == 'asm', 'a rejected program must not replace the loaded one'

# swap WITH a user program loaded: verified by the probe, program and data untouched, no false "miss"
FB.m1.write(0, 0); before = list(FB.dmem[:64])
r = g['_swap']('multiplier', 'driver')
assert r['probe'] == 42 and not r['retried'] and r['words'] is None, r
assert FB.dmem[:64] == before and FB.imem[:8] == g['_prog']['imem'], 'swap must not disturb the user program'
code, o = api_get('/api/loader'); assert o['available'] and o['program']['name'] == 'asm'
code, o = post('/api/run', {}); assert o['cycles'] == 35 and o['words'][0] == 55

# the dangerous one: a miss on a real swap with a user program loaded -> full reload wipes imem/dmem -> program must come back
FB.dmem[100] = 1234; g['_prog']['inputs'] = {100: [1234]}      # an input the user supplied
FB.stuck = True
r = g['_swap']('bitwise', 'driver')
assert r['retried'] and r['recovery'] == 'full' and r['probe'] == 2, r
assert FB.dmem[100] == 1234, 'inputs are written again after the reload'
code, o = post('/api/run', {}); assert code == 200 and o['halted'] and o['words'][0] == 55, 'the user program survived the full reload'
STATS = g['STATS']; assert STATS['recoveries'] >= 3
print('server_check: loader, probe, swap-with-program, recovery-restores-program ok')

# C programs: calc changes with the slot; rick decodes on the core
sc = os.path.join(here, '..', 'sw', 'c')
try:
    for n, fl in (('calc', []), ('rick', ['--no-cfu-libcalls'])):
        subprocess.run([os.path.join(sc, 'build.sh'), os.path.join(sc, n + '.c')] + fl, check=True, capture_output=True)
except (OSError, subprocess.CalledProcessError) as e:
    print('SKIPPED C checks in server_check:', e); raise SystemExit(0)
img = lambda n: json.load(open(os.path.join(sc, 'out', n + '.json')))
for to, want in (('multiplier', [42, 0, 6, 43]), ('bitwise', [2, 2, 6, 3])):
    g['_swap'](to, 'driver')                                    # swap first, then load: the program does not care which order
    code, o = post('/api/program', dict(img('calc'), name='calc', inputs={64: [6, 7]}, read=[0, 4]))
    assert o['words'] == want and o['cycles'] == 46, (to, o)
code, o = post('/api/run', {'inputs': {64: [10, 11]}, 'read': [0, 2]}); assert o['words'] == [2, 2], o      # bitwise: popcount(10)=2 for both
g['_swap']('bitwise', 'driver')
import tempfile; RS = os.path.join(tempfile.mkdtemp(), 'rs.json')
subprocess.run([sys.executable, os.path.join(here, '..', 'sw', 'rick', 'encode.py'), '--synthetic', RS], check=True)
R = json.load(open(RS))
assert post('/api/rick?from=0&n=5')[0] == 409                  # before the program/clip are there
post('/api/program', dict(img('rick'), name='rick', run=False)); post('/api/clip', {'frames': R['frames']})
code, o = post('/api/rick?from=0&n=12'); assert code == 200 and o['frames'] == R['ref'][:12] and o['n'] == 12, code
g['_swap']('multiplier', 'driver')                              # mid-video swap: still the same loaded program
code, o = post('/api/rick?from=12&n=4'); assert o['frames'][0] != R['ref'][12] and o['frames'][3] != R['ref'][15], 'multiplier must break the picture'
g['_swap']('bitwise', 'driver')
code, o = post('/api/rick?from=16&n=14'); assert o['frames'][0] != R['ref'][16], 'still corrupt until a key frame'
assert o['frames'][4:] == R['ref'][20:30], 'the key frame at 20 repairs it'
FB.stuck = True; g['_swap']('multiplier', 'driver')              # a miss mid-video: full reload, rick program put back
code, o = post('/api/rick?from=20&n=2'); assert code == 200 and o['n'] == 2, (code, o)
print('server_check: C programs, rick decode, mid-video swap and recovery ok')
