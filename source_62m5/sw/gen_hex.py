#!/usr/bin/env python3
"""Tiny RV32I assembler for the week-1 smoke-test program.
Emits program.hex (one 32-bit word per line, hex) for $readmemh.

The program is deliberately CFU-VARIANT-AGNOSTIC: it drives the reconfigurable
slot through the full memory map (op_a, op_b, fn, result) and banks every
answer into data memory.  The testbench -- not the program -- knows which
variant is loaded and what it should have returned.  That is what lets the same
program.hex validate both cfu_mul.v and cfu_bitwise.v.

CFU memory map (base 0xF000_0000):
    +0x0  W  op_a      +0x8  W  fn (also pulses start)
    +0x4  W  op_b      +0xC  R  result

Core (variant-independent) results:
    mem[0] = 13        x1+x2
    mem[1] = 1         x2-x1

CFU results, phase 1 (op_a=6, op_b=7):
    mem[4]=fn0  mem[5]=fn1  mem[6]=fn2  mem[7]=fn3

CFU results, phase 2 (op_a=op_b=0x0001_0000):
    mem[8]=fn0  mem[9]=fn1  mem[10]=fn2

Phase 2 exists so the multiplier's high-word path is actually exercised:
0x10000 * 0x10000 = 0x1_0000_0000, so fn0 (low) = 0 and fn1 (high) = 1.
With 6*7 the high word is 0 either way and the test proves nothing.
"""

def r(f7, rs2, rs1, f3, rd, op):
    return (f7 << 25) | (rs2 << 20) | (rs1 << 15) | (f3 << 12) | (rd << 7) | op

def i(imm, rs1, f3, rd, op):
    return ((imm & 0xFFF) << 20) | (rs1 << 15) | (f3 << 12) | (rd << 7) | op

def s(imm, rs2, rs1, f3, op):
    imm &= 0xFFF
    return ((imm >> 5) << 25) | (rs2 << 20) | (rs1 << 15) | (f3 << 12) | ((imm & 0x1F) << 7) | op

def u(imm20, rd, op):
    return ((imm20 & 0xFFFFF) << 12) | (rd << 7) | op

def j(imm, rd, op):
    imm &= 0x1FFFFF
    b20 = (imm >> 20) & 1
    b10_1 = (imm >> 1) & 0x3FF
    b11 = (imm >> 11) & 1
    b19_12 = (imm >> 12) & 0xFF
    return (b20 << 31) | (b10_1 << 21) | (b11 << 20) | (b19_12 << 12) | (rd << 7) | op

OP_R, OP_I, OP_LD, OP_S, OP_LUI, OP_JAL = 0x33, 0x13, 0x03, 0x23, 0x37, 0x6F

# register use: x1=6  x2=7  x3=sum  x4=diff  x5=CFU base  x7=big operand
#               x8=fn scratch  x9=result scratch
prog = []
asm  = []

def emit(word, text):
    prog.append(word)
    asm.append(text)

def cfu_call(fn, mem_word):
    """fn -> CFU+0x8, then read CFU+0xC and bank it at dmem word `mem_word`."""
    emit(i(fn, 0, 0, 8, OP_I),       "addi x8,x0,%d" % fn)
    emit(s(8, 8, 5, 2, OP_S),        "sw   x8,8(x5)        # fn=%d" % fn)
    emit(i(0, 0, 0, 0, OP_I),        "nop                  # result_q settles (62.5 MHz registered CFU)")
    emit(i(12, 5, 2, 9, OP_LD),      "lw   x9,12(x5)       # read result")
    emit(s(mem_word * 4, 9, 0, 2, OP_S),
                                     "sw   x9,%d(x0)       # mem[%d]" % (mem_word * 4, mem_word))

# ---- core datapath, no CFU involved ----
emit(i(6, 0, 0, 1, OP_I),        "addi x1,x0,6")
emit(i(7, 0, 0, 2, OP_I),        "addi x2,x0,7")
emit(r(0x00, 2, 1, 0, 3, OP_R),  "add  x3,x1,x2        # 13")
emit(r(0x20, 1, 2, 0, 4, OP_R),  "sub  x4,x2,x1        # 1")
emit(s(0, 3, 0, 2, OP_S),        "sw   x3,0(x0)        # mem[0]=13")
emit(s(4, 4, 0, 2, OP_S),        "sw   x4,4(x0)        # mem[1]=1")
emit(u(0xF0000, 5, OP_LUI),      "lui  x5,0xF0000      # CFU base")

# ---- phase 1: op_a=6, op_b=7, sweep fn 0..3 ----
emit(s(0, 1, 5, 2, OP_S),        "sw   x1,0(x5)        # op_a=6")
emit(s(4, 2, 5, 2, OP_S),        "sw   x2,4(x5)        # op_b=7")
for fn in range(4):
    cfu_call(fn, 4 + fn)

# ---- phase 2: op_a=op_b=0x00010000, sweep fn 0..2 ----
emit(u(0x00010, 7, OP_LUI),      "lui  x7,0x10         # 0x00010000")
emit(s(0, 7, 5, 2, OP_S),        "sw   x7,0(x5)        # op_a")
emit(s(4, 7, 5, 2, OP_S),        "sw   x7,4(x5)        # op_b")
for fn in range(3):
    cfu_call(fn, 8 + fn)

emit(j(0, 0, OP_JAL),            "jal  x0,0            # halt")

with open("program.hex", "w") as fh:
    for w in prog:
        fh.write("%08x\n" % (w & 0xFFFFFFFF))

print("wrote program.hex (%d instructions)" % len(prog))
for k, (w, text) in enumerate(zip(prog, asm)):
    print("  [%2d] 0x%08x   %s" % (k, w & 0xFFFFFFFF, text))
