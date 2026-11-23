"""python3 demo/loader_check.py -- demo/loader.py against demo/fakecore.py.  Numbers that must agree with tb/tb_riscv.v and
demo/sim.js are asserted, so the three models stay tied together: baked program 41 cycles, sum10 35, tb step 5 program 10."""
import json, os, subprocess, sys, tempfile
here = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, here); sys.path.insert(0, os.path.join(here, '..', 'sw'))
from fakecore import FakeBoard
from loader import Loader, RST
import rvasm

def asm(path): return rvasm.assemble(open(os.path.join(here, '..', 'sw', 'asm', path)).read())[0]

import loader
assert loader.PROBE == rvasm.assemble(loader.PROBE_ASM)[0], 'PROBE words != PROBE_ASM'
assert loader.BAKED == [int(l, 16) for l in open(os.path.join(here, '..', 'sw', 'program.hex')).read().split()], 'BAKED != sw/program.hex'
for v, want in loader.PROBE_EXPECT.items():                    # the probe tells the two units apart and leaves dmem[0..1022] alone
    b = FakeBoard(v); L = Loader(b.m0, b.m1); L.program(asm('sum10.s')); L.put_dmem([7, 8, 9], base=3)
    L.program(loader.PROBE); assert L.run()[0] and L.read_dmem(loader.PROBE_WORD, 1) == [want] and L.read_dmem(3, 3) == [7, 8, 9], v

def fresh(variant='multiplier'):
    b = FakeBoard(variant); return b, Loader(b.m0, b.m1)

# the baked program runs at power-on exactly as the old demo expects
b, L = fresh(); L.hold(); assert L.run() == (True, 41)
assert L.read_dmem(4, 2) == [42, 0] and L.read_dmem(0, 2) == [13, 1]
b, L = fresh('bitwise'); L.hold(); L.run(); assert L.read_dmem(4, 2) == [2, 6]

# load + run a different program
b, L = fresh(); L.program(asm('sum10.s')); assert L.run() == (True, 35); assert L.read_dmem(0, 1) == [55]
assert L.read_dmem(0, 1) == [55] and (b.ctl & RST) == 0, 'read_dmem keeps the reset bit as it found it'

# strobes while the core runs are ignored; held strobe writes once; registers survive reset (HW has no regfile reset)
word0 = b.imem[0]; b.m1.write(0, 0xDEADBEEF); b.m0.write(0, 0x1800); assert b.imem[0] == word0 and b.dmem[0] == 55
b.m0.write(0, 0)
L.hold(); b.m1.write(0, 0xA1); b.m0.write(0, RST | 700 | (1 << 12)); b.m1.write(0, 0xB2); b.m0.write(0, RST | 700 | (1 << 12)); b.m0.write(0, RST | 700)
assert b.dmem[700] == 0xA1

# registers survive a core reset (the RTL has no regfile reset), so a program that reads one it never set sees the last program's value;
# zero_regs() makes every user program start from zeros like the model
leak = rvasm.assemble('add x4, x4, x0\naddi x4, x4, 1\nsw x4, 0(x0)\ndone: j done')[0]            # x4 = x4 + 1, never initialised
b, L = fresh(); L.program(asm('sum10.s')); L.run()                                                    # leaves x1..x3 non-zero
L.program(rvasm.assemble('addi x4, x4, 5\nsw x4, 0(x0)\ndone: j done')[0]); L.run(); first = L.read_dmem(0, 1)[0]
L.program(leak); L.run(); dirty = L.read_dmem(0, 1)[0]
L.zero_regs(); L.program(leak); L.run(); clean = L.read_dmem(0, 1)[0]
assert first == 5 and dirty == 6 and clean == 1, (first, dirty, clean)
assert loader.CLEAR == [rvasm.assemble(f'addi x{n}, x0, 0')[0][0] for n in range(1, 32)] + rvasm.assemble('j 0')[0], 'CLEAR words'

# the tb step 5 program, both variants: lw lw CFU(fn2) sw
tb5 = [0x19002083, 0x19402103, 0xf00002b7, 0x0012a023, 0x0022a223, 0x00200413, 0x0082a423, 0x00c2a483, 0x18902c23, 0x0000006f]
for variant, want in (('multiplier', 0x3b2a1908), ('bitwise', 0x1d3b5977)):
    b, L = fresh(variant); L.program(tb5); L.put_dmem([0x12345678, 0x0F0F0F0F], base=100)
    assert L.run() == (True, 10) and L.read_dmem(102, 1) == [want], variant

# a program that never halts times out and leaves the core in reset
b, L = fresh(); L.program([0x00108093, 0xffdff06f]); halted, _ = L.run(); assert not halted and b.ctl & RST   # loop: addi x1,x1,1 ; j loop

# C programs and the rick frames, if the cross compiler is there
sc = os.path.join(here, '..', 'sw', 'c')
try:
    for n, flags in (('calc', []), ('rick', ['--no-cfu-libcalls'])):
        subprocess.run([os.path.join(sc, 'build.sh'), os.path.join(sc, n + '.c')] + flags, check=True, capture_output=True)
except (OSError, subprocess.CalledProcessError) as e:
    print('SKIPPED C checks:', getattr(e, 'stderr', e)); sys.exit(0)
load = lambda n: json.load(open(os.path.join(sc, 'out', n + '.json')))
calc = load('calc')
for variant, want in (('multiplier', [42, 0, 6, 43]), ('bitwise', [2, 2, 6, 3])):
    b, L = fresh(variant); L.program(calc['imem'], calc['dmem']); L.put_dmem([6, 7], base=64)
    assert L.run() == (True, 46) and L.read_dmem(0, 4) == want, variant        # 46 cycles in demo/sim.js too
rick = load('rick')
with tempfile.TemporaryDirectory() as d:
    out = os.path.join(d, 'r.json')
    subprocess.run([sys.executable, os.path.join(here, '..', 'sw', 'rick', 'encode.py'), '--synthetic', out], check=True)
    R = json.load(open(out))
b, L = fresh('bitwise'); L.program(rick['imem'], rick['dmem'])
for n, f in enumerate(R['frames']):
    for k in range(0, max(1, len(f['p'])), 400):                     # at most 200 pairs per run, as board_server feeds it
        part = f['p'][k:k + 400]
        L.hold(); L.put_dmem([f['c'] if k == 0 else 0, len(part) // 2] + part, base=576)
        assert L.run()[0], f'rick frame {n}'
    assert L.read_dmem(0, 576) == R['ref'][n], f'rick frame {n}'
print('loader_check: OK (baked program 41, sum10 35, tb step 5 10, calc 46 cycles; %d rick frames == source; %d AXI writes)' % (len(R['frames']), b.writes))
