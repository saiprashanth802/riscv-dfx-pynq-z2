"""loader.py -- the PS side of the b3 program loader (rtl/pynq_axi_top.v).  Pure Python, no pynq import, so the same code
runs on the board (with pynq MMIO objects) and in demo/server_check.py (with demo/fakecore.py).

Registers (AXI GPIO, 4 bytes apart): +0x0 data/ch1, +0x8 ch2.
    m0 = ol.axi_gpio_0.mmio   ch1 (write) ctl:  [9:0] word address  [10] hold the core in reset  [11] imem write  [12] dmem write
                              ch2 (read)  dmem[ctl[9:0]]
    m1 = ol.axi_gpio_1.mmio   ch1 (write) data for the writes
                              ch2 (read)  {halted, cycles[30:0]}  -- clocks since reset release, frozen at the halt loop

Every write is: data, then address+strobe, then address without strobe (the RTL writes on the strobe's rising edge, so the
strobe has to fall between two words).  Every operation ends with the strobes low.  Writes are only honoured while the core is
held in reset; run() releases it and waits for the halt.
"""
import time

RST, IWE, DWE = 1 << 10, 1 << 11, 1 << 12
IMEM_WORDS, DMEM_WORDS = 256, 1024

# Which unit is in the slot, asked without touching the user's program data.  A slot probe cannot use the baked program: with
# a user program loaded its results are not at words 4/5/8, and a wrong "miss" would trigger a full reload (1 in 99 of those
# wedged the config engine).  It overwrites imem[0:10] (restored by the caller) and dmem word 1023, the dead top of the stack.
PROBE_ASM = """lui  x5, 0xF0000      # CFU window
addi x1, x0, 6
addi x2, x0, 7
sw   x1, 0(x5)        # op_a = 6
sw   x2, 4(x5)        # op_b = 7
sw   x0, 8(x5)        # fn 0
lw   x3, 12(x5)       # multiplier: 6*7 = 42   bitwise: popcount(6) = 2
lui  x6, 0x10001
sw   x3, -4(x6)       # dmem word 1023
done: j done"""
PROBE = [
    0xf00002b7, 0x00600093, 0x00700113, 0x0012a023, 0x0022a223, 0x0002a423,
    0x00c2a183, 0x10001337, 0xfe332e23, 0x0000006f,
]
PROBE_WORD, PROBE_EXPECT = 1023, {'multiplier': 42, 'bitwise': 2}

# The register file has no reset in the RTL: it keeps whatever the previous program left.  demo/sim.js starts every register at 0, so a
# hand-written program that reads a register it never set would differ between board and model.  zero_regs() runs this (addi xN,x0,0
# for N = 1..31, then a halt) so a user program starts from the same state in both.
CLEAR = [0x00000013 | (n << 7) for n in range(1, 32)] + [0x0000006F]

# The baked power-on program (sw/program.hex): what imem holds after any full bitstream load.
BAKED = [
    0x00600093, 0x00700113, 0x002081b3, 0x40110233, 0x00302023, 0x00402223,
    0xf00002b7, 0x0012a023, 0x0022a223, 0x00000413, 0x0082a423, 0x00c2a483,
    0x00902823, 0x00100413, 0x0082a423, 0x00c2a483, 0x00902a23, 0x00200413,
    0x0082a423, 0x00c2a483, 0x00902c23, 0x00300413, 0x0082a423, 0x00c2a483,
    0x00902e23, 0x000103b7, 0x0072a023, 0x0072a223, 0x00000413, 0x0082a423,
    0x00c2a483, 0x02902023, 0x00100413, 0x0082a423, 0x00c2a483, 0x02902223,
    0x00200413, 0x0082a423, 0x00c2a483, 0x02902423, 0x0000006f,
]


class Loader:
    def __init__(self, m0, m1):
        self.m0, self.m1 = m0, m1

    def hold(self):
        self.m0.write(0, RST)

    def _put(self, strobe, base, words):
        m0, m1 = self.m0, self.m1
        for i, w in enumerate(words):
            a = base + i
            m1.write(0, w & 0xFFFFFFFF)
            m0.write(0, RST | a | strobe)
            m0.write(0, RST | a)

    def put_imem(self, words, base=0):
        assert 0 <= base and base + len(words) <= IMEM_WORDS, 'program does not fit in imem'
        self.hold(); self._put(IWE, base, words)

    def put_dmem(self, words, base=0):
        assert 0 <= base and base + len(words) <= DMEM_WORDS, 'data does not fit in dmem'
        self.hold(); self._put(DWE, base, words)

    def read_dmem(self, start=0, n=64):
        """Works with the core running, halted or in reset: it is the debug read port.  Keeps the reset bit as it is."""
        m0, held, out = self.m0, self.m0.read(0) & RST, []
        for a in range(start, start + n):
            m0.write(0, held | a)
            out.append(m0.read(8))
        return out

    def run(self, timeout=0.5):
        """Release reset, wait for the halt loop.  Returns (halted, cycles); on a timeout the core is put back in reset."""
        self.m0.write(0, 0)
        t_end = time.perf_counter() + timeout
        while True:
            s = self.m1.read(8)
            if s & 0x80000000:
                return True, s & 0x7FFFFFFF
            if time.perf_counter() > t_end:
                self.hold()
                return False, s & 0x7FFFFFFF

    def zero_regs(self):
        """Zero x1..x31.  Leaves the core in reset and imem[0:32] holding the clear routine: write the program after this."""
        self.hold(); self.put_imem(CLEAR)
        halted, _ = self.run(); self.hold()
        assert halted, 'the register-clear routine did not halt'

    def program(self, imem, dmem=None):
        """Load a whole program image (the core stays in reset)."""
        self.hold(); self.put_imem(imem)
        if dmem: self.put_dmem(dmem)
