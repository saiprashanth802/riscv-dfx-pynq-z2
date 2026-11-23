"""fakecore.py -- a stand-in for the b3 board for testing demo/loader.py and demo/board_server.py off the board.

Models what rtl/ does, as seen through the two AXI GPIOs: write strobes honoured only in reset and only on a rising edge,
the register file NOT cleared by reset (the RTL has no reset on it), dmem kept across a core reset, the cycle counter cleared
by reset and frozen at the halt loop, loads/stores that ignore funct3 (word only).  A second, independent implementation of
RV32I next to demo/sim.js: tests compare the two (and tb/tb_riscv.v) on cycle counts.

Timing is not modelled: releasing reset runs the program to its halt immediately.
"""
import os

M = 0xFFFFFFFF
RST, IWE, DWE = 1 << 10, 1 << 11, 1 << 12
MAX_CYCLES = 200000


def _s32(v):
    v &= M
    return v - (1 << 32) if v & 0x80000000 else v


def cfu(variant, a, b, fn):
    if variant == 'multiplier':
        p = a * b
        return (p >> 32) & M if fn == 1 else p & M
    if fn == 0: return bin(a).count('1')
    if fn == 1: return a & b
    if fn == 2: return a ^ b
    return a


class _Port:
    def __init__(self, board, which): self.b, self.which = board, which
    def write(self, off, val): self.b._write(self.which, off, val & M)
    def read(self, off): return self.b._read(self.which, off)


class FakeBoard:
    def __init__(self, variant='multiplier', program_hex=None):
        self.variant = variant
        path = program_hex or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'sw', 'program.hex')
        self.imem = [0] * 256                                                         # rtl/imem.v: 256 words, higher addresses alias
        for i, l in enumerate(open(path).read().split()): self.imem[i] = int(l, 16)    # power-on image, like $readmemh
        self.dmem = [0] * 1024
        self.x = [0] * 32
        self.ctl, self.wdata, self.stat = RST, 0, 0                                    # the PS holds the core in reset at power-on
        self.cfu_regs = [0, 0, 0]
        self.stuck = False                                                             # the silent-miss fault of the config engine
        self.m0, self.m1 = _Port(self, 0), _Port(self, 1)
        self.writes = 0                                                                # AXI writes seen, for cost estimates

    # ---- the partial / full bitstream loads (what swap(), raw() and full() do on the board) ----
    def load_partial(self, name):
        if not self.stuck: self.variant = name

    def load_full(self, name):
        """A full reload: the static design is configured again, so imem returns to program.hex and dmem to zero."""
        self.variant, self.stuck = name, False
        self.__init__(name)

    # ---- AXI GPIO registers ----
    def _write(self, which, off, val):
        self.writes += 1
        if which == 1:
            if off == 0: self.wdata = val
            return
        if off != 0: return
        old, self.ctl = self.ctl, val
        addr = val & 0x3FF
        if val & RST:
            if (val & IWE) and not (old & IWE): self.imem[addr & 255] = self.wdata
            if (val & DWE) and not (old & DWE): self.dmem[addr] = self.wdata
            if not (old & RST): self.stat = 0                                          # counter cleared while in reset
        elif old & RST:
            self._run()

    def _read(self, which, off):
        if which == 1: return self.wdata if off == 0 else self.stat if off == 8 else 0
        return self.ctl if off == 0 else self.dmem[self.ctl & 0x3FF] if off == 8 else 0

    # ---- the core ----
    def _load(self, addr):
        addr &= M
        if addr >> 28 == 0xF: return cfu(self.variant, *self.cfu_regs) if (addr & 0xF) == 0xC else 0
        return self.dmem[(addr >> 2) & 1023]

    def _store(self, addr, v):
        addr &= M
        if addr >> 28 == 0xF:
            o = addr & 0xF
            if o in (0, 4, 8): self.cfu_regs[o // 4] = v & (0xF if o == 8 else M)
        else: self.dmem[(addr >> 2) & 1023] = v & M

    def _run(self):
        x, pc, cyc, halted = self.x, 0, 0, False
        self.cfu_regs = [0, 0, 0]                                                      # cfu_mmio clears its registers in reset
        while cyc < MAX_CYCLES:
            w = self.imem[(pc >> 2) & 255]
            op, rd, f3, rs1, rs2, f7 = w & 0x7F, (w >> 7) & 31, (w >> 12) & 7, (w >> 15) & 31, (w >> 20) & 31, w >> 25
            a, b = x[rs1] & M, x[rs2] & M
            immI = _s32(w) >> 20
            immS = (_s32(w) >> 25 << 5) | ((w >> 7) & 31)
            immB = _s32(((w >> 31) << 31) | (((w >> 7) & 1) << 30) | (((w >> 25) & 63) << 24) | (((w >> 8) & 15) << 20)) >> 19
            immJ = _s32(((w >> 31) << 31) | (((w >> 12) & 255) << 23) | (((w >> 20) & 1) << 22) | (((w >> 21) & 1023) << 12)) >> 11
            nxt, wr = (pc + 4) & M, None
            if op == 0x33 or op == 0x13:
                bb = b if op == 0x33 else immI & M
                alt = f7 == 0x20 and (op == 0x33 or f3 == 5)
                sh = bb & 31
                wr = {0: (a - bb if alt and op == 0x33 else a + bb), 1: a << sh, 2: int(_s32(a) < _s32(bb)), 3: int(a < bb), 4: a ^ bb,
                      5: (_s32(a) >> sh) if alt else a >> sh, 6: a | bb, 7: a & bb}[f3]
            elif op == 0x03: wr = self._load(a + immI)                                 # funct3 ignored, like control.v
            elif op == 0x23: self._store(a + immS, b)
            elif op == 0x63:
                t = {0: a == b, 1: a != b, 4: _s32(a) < _s32(b), 5: _s32(a) >= _s32(b), 6: a < b, 7: a >= b}.get(f3, False)
                if t: nxt = (pc + immB) & M
            elif op == 0x37: wr = w & 0xFFFFF000
            elif op == 0x17: wr = pc + (w & 0xFFFFF000)
            elif op == 0x6F: wr, nxt = pc + 4, (pc + immJ) & M
            elif op == 0x67: wr, nxt = pc + 4, (a + immI) & ~1 & M
            if wr is not None and rd: x[rd] = wr & M
            cyc += 1
            if nxt == pc: halted = True; break
            pc = nxt
        self.stat = (0x80000000 if halted else 0) | cyc
