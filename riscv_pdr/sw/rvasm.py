#!/usr/bin/env python3
"""rvasm.py -- tiny RV32I assembler for the riscv_pdr core (runs on the laptop and on the board's Python 3).

    python3 sw/rvasm.py prog.s            # prints the listing, writes nothing
    python3 sw/rvasm.py prog.s -o p.json  # {"imem": [word, ...]}
    python3 sw/rvasm.py --selfcheck

Accepts what rtl/control.v implements and nothing else: R/I ALU ops, lw/sw, branches, lui, auipc, jal, jalr.
Pseudo-ops: nop li la mv j jr ret beqz bnez neg not.  Labels are byte addresses in imem (4 bytes per word).

Loads and stores are WORD-ONLY.  control.v never looks at funct3 on loads/stores, so lb/sb would silently run as
lw/sw.  They are rejected here (and in sw/c/build.sh) instead of being allowed to compute the wrong thing.
The encoders below are copies of sw/gen_hex.py's: importing that file rewrites program.hex as a side effect.
"""
import json, os, re, sys

class AsmError(Exception):
    pass

# ---- encoders ---------------------------------------------------------------------------------------------
def enc_r(f7, rs2, rs1, f3, rd, op): return (f7 << 25) | (rs2 << 20) | (rs1 << 15) | (f3 << 12) | (rd << 7) | op
def enc_i(imm, rs1, f3, rd, op):     return ((imm & 0xFFF) << 20) | (rs1 << 15) | (f3 << 12) | (rd << 7) | op
def enc_u(imm20, rd, op):            return ((imm20 & 0xFFFFF) << 12) | (rd << 7) | op

def enc_s(imm, rs2, rs1, f3, op):
    imm &= 0xFFF
    return ((imm >> 5) << 25) | (rs2 << 20) | (rs1 << 15) | (f3 << 12) | ((imm & 0x1F) << 7) | op

def enc_b(imm, rs2, rs1, f3, op):
    imm &= 0x1FFF
    return (((imm >> 12) & 1) << 31) | (((imm >> 5) & 0x3F) << 25) | (rs2 << 20) | (rs1 << 15) | (f3 << 12) \
        | (((imm >> 1) & 0xF) << 8) | (((imm >> 11) & 1) << 7) | op

def enc_j(imm, rd, op):
    imm &= 0x1FFFFF
    return (((imm >> 20) & 1) << 31) | (((imm >> 1) & 0x3FF) << 21) | (((imm >> 11) & 1) << 20) \
        | (((imm >> 12) & 0xFF) << 12) | (rd << 7) | op

OP_R, OP_I, OP_LD, OP_S, OP_B, OP_LUI, OP_AUIPC, OP_JAL, OP_JALR = 0x33, 0x13, 0x03, 0x23, 0x63, 0x37, 0x17, 0x6F, 0x67

# ---- tables ------------------------------------------------------------------------------------------------
REGS = {f'x{i}': i for i in range(32)}
REGS.update(zero=0, ra=1, sp=2, gp=3, tp=4, fp=8, s0=8, s1=9, t0=5, t1=6, t2=7)
REGS.update({f'a{i}': 10 + i for i in range(8)})
REGS.update({f's{i}': 16 + i for i in range(2, 12)})
REGS.update({f't{i}': 25 + i for i in range(3, 7)})

R_OPS  = {'add': (0, 0), 'sub': (0x20, 0), 'sll': (0, 1), 'slt': (0, 2), 'sltu': (0, 3),
          'xor': (0, 4), 'srl': (0, 5), 'sra': (0x20, 5), 'or': (0, 6), 'and': (0, 7)}
I_OPS  = {'addi': 0, 'slti': 2, 'sltiu': 3, 'xori': 4, 'ori': 6, 'andi': 7}
SH_OPS = {'slli': (0, 1), 'srli': (0, 5), 'srai': (0x20, 5)}
B_OPS  = {'beq': 0, 'bne': 1, 'blt': 4, 'bge': 5, 'bltu': 6, 'bgeu': 7}
PSEUDO_SIZE = {'li': None, 'la': 2}          # li: 1 or 2 words, decided from the constant

REJECT = {
    **{m: 'byte/halfword access: the core is word-only (control.v ignores funct3 on loads/stores), use lw/sw'
       for m in ('lb', 'lh', 'lbu', 'lhu', 'sb', 'sh')},
    **{m: 'no M extension: multiply with the CFU slot or a software loop'
       for m in ('mul', 'mulh', 'mulhu', 'mulhsu', 'div', 'divu', 'rem', 'remu')},
    **{m: 'not implemented by the core' for m in ('ecall', 'ebreak', 'fence', 'fence.i', 'csrr', 'csrw', 'csrrw', 'csrrs', 'csrrc')},
}

IMEM_WORDS = 256     # rtl/imem.v

def reg(tok, ln):
    t = tok.strip().lower()
    if t not in REGS:
        raise AsmError(f'line {ln}: unknown register {tok!r}')
    return REGS[t]

def num(tok):
    return int(tok.strip().replace('_', ''), 0)

def is_num(tok):
    try:
        num(tok); return True
    except ValueError:
        return False

def fits(v, bits):
    return -(1 << (bits - 1)) <= v < (1 << (bits - 1))

def s32(v):
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v

def split_hi_lo(v):
    """32-bit value -> (lui imm20, addi imm12) such that (hi << 12) + lo == v mod 2**32."""
    v &= 0xFFFFFFFF
    lo = v & 0xFFF
    if lo >= 0x800: lo -= 0x1000
    return ((v - lo) >> 12) & 0xFFFFF, lo

def parse(text):
    """-> (items, labels).  items: (lineno, mnemonic, [operands], word_index, source_line)."""
    items, labels, widx = [], {}, 0
    for ln, raw in enumerate(text.splitlines(), 1):
        line = re.split(r'#|;|//', raw, maxsplit=1)[0].strip()
        while True:
            m = re.match(r'([A-Za-z_.][\w.]*)\s*:\s*(.*)$', line)
            if not m: break
            if m.group(1) in labels: raise AsmError(f'line {ln}: label {m.group(1)!r} defined twice')
            labels[m.group(1)] = widx * 4
            line = m.group(2)
        if not line: continue
        parts = line.split(None, 1)
        mn = parts[0].lower()
        ops = [o.strip() for o in parts[1].split(',')] if len(parts) > 1 else []
        if mn in REJECT: raise AsmError(f'line {ln}: {mn}: {REJECT[mn]}')
        if mn == 'li':
            size = 1 if (len(ops) == 2 and is_num(ops[1]) and fits(s32(num(ops[1])), 12)) else 2
        else:
            size = PSEUDO_SIZE.get(mn, 1)
        items.append((ln, mn, ops, widx, raw.rstrip()))
        widx += size
    if widx > IMEM_WORDS: raise AsmError(f'program is {widx} words, imem holds {IMEM_WORDS}')
    return items, labels

def assemble(text):
    """-> (words, listing).  listing: list of (byte address, word, source line)."""
    items, labels = parse(text)
    words, listing = [], []

    def value(tok, ln):
        tok = tok.strip()
        if is_num(tok): return num(tok)
        if tok in labels: return labels[tok]
        raise AsmError(f'line {ln}: unknown label or number {tok!r}')

    def memop(tok, ln):
        m = re.match(r'^(.*)\((\w+)\)$', tok.strip())
        if not m: raise AsmError(f'line {ln}: expected imm(reg), got {tok!r}')
        imm = value(m.group(1), ln) if m.group(1).strip() else 0
        if not fits(imm, 12): raise AsmError(f'line {ln}: offset {imm} does not fit 12 bits')
        return imm, reg(m.group(2), ln)

    def need(ops, n, ln, mn):
        if len(ops) != n: raise AsmError(f'line {ln}: {mn} takes {n} operand(s), got {len(ops)}')

    for ln, mn, ops, widx, src in items:
        pc = widx * 4
        out = []
        if mn == 'nop':
            need(ops, 0, ln, mn); out = [enc_i(0, 0, 0, 0, OP_I)]
        elif mn in R_OPS:
            need(ops, 3, ln, mn); f7, f3 = R_OPS[mn]
            out = [enc_r(f7, reg(ops[2], ln), reg(ops[1], ln), f3, reg(ops[0], ln), OP_R)]
        elif mn in I_OPS:
            need(ops, 3, ln, mn); imm = value(ops[2], ln)
            if not fits(imm, 12): raise AsmError(f'line {ln}: immediate {imm} does not fit 12 bits')
            out = [enc_i(imm, reg(ops[1], ln), I_OPS[mn], reg(ops[0], ln), OP_I)]
        elif mn in SH_OPS:
            need(ops, 3, ln, mn); sh = value(ops[2], ln); f7, f3 = SH_OPS[mn]
            if not 0 <= sh < 32: raise AsmError(f'line {ln}: shift amount {sh} out of 0..31')
            out = [enc_i((f7 << 5) | sh, reg(ops[1], ln), f3, reg(ops[0], ln), OP_I)]
        elif mn == 'lw':
            need(ops, 2, ln, mn); imm, rs1 = memop(ops[1], ln)
            out = [enc_i(imm, rs1, 2, reg(ops[0], ln), OP_LD)]
        elif mn == 'sw':
            need(ops, 2, ln, mn); imm, rs1 = memop(ops[1], ln)
            out = [enc_s(imm, reg(ops[0], ln), rs1, 2, OP_S)]
        elif mn in B_OPS or mn in ('beqz', 'bnez'):
            if mn in ('beqz', 'bnez'):
                need(ops, 2, ln, mn); ops = [ops[0], 'x0', ops[1]]; f3 = 0 if mn == 'beqz' else 1
            else:
                need(ops, 3, ln, mn); f3 = B_OPS[mn]
            off = value(ops[2], ln) - pc if ops[2].strip() in labels else value(ops[2], ln)
            if off % 2 or not fits(off, 13): raise AsmError(f'line {ln}: branch offset {off} out of range (even, +-4 KB)')
            out = [enc_b(off, reg(ops[1], ln), reg(ops[0], ln), f3, OP_B)]
        elif mn in ('jal', 'j'):
            if mn == 'j': need(ops, 1, ln, mn); rd, tgt = 0, ops[0]
            else:         need(ops, 2, ln, mn); rd, tgt = reg(ops[0], ln), ops[1]
            off = value(tgt, ln) - pc if tgt.strip() in labels else value(tgt, ln)
            if off % 2 or not fits(off, 21): raise AsmError(f'line {ln}: jump offset {off} out of range')
            out = [enc_j(off, rd, OP_JAL)]
        elif mn == 'jalr':
            need(ops, 2, ln, mn); imm, rs1 = memop(ops[1], ln)
            out = [enc_i(imm, rs1, 0, reg(ops[0], ln), OP_JALR)]
        elif mn == 'jr':
            need(ops, 1, ln, mn); out = [enc_i(0, reg(ops[0], ln), 0, 0, OP_JALR)]
        elif mn == 'ret':
            need(ops, 0, ln, mn); out = [enc_i(0, 1, 0, 0, OP_JALR)]
        elif mn in ('lui', 'auipc'):
            need(ops, 2, ln, mn); imm = value(ops[1], ln)
            if not 0 <= imm < (1 << 20) and not fits(imm, 20): raise AsmError(f'line {ln}: {mn} immediate {imm} does not fit 20 bits')
            out = [enc_u(imm, reg(ops[0], ln), OP_LUI if mn == 'lui' else OP_AUIPC)]
        elif mn == 'mv':
            need(ops, 2, ln, mn); out = [enc_i(0, reg(ops[1], ln), 0, reg(ops[0], ln), OP_I)]
        elif mn == 'neg':
            need(ops, 2, ln, mn); out = [enc_r(0x20, reg(ops[1], ln), 0, 0, reg(ops[0], ln), OP_R)]
        elif mn == 'not':
            need(ops, 2, ln, mn); out = [enc_i(-1, reg(ops[1], ln), 4, reg(ops[0], ln), OP_I)]
        elif mn in ('li', 'la'):
            need(ops, 2, ln, mn); rd = reg(ops[0], ln); v = s32(value(ops[1], ln))
            if mn == 'li' and fits(v, 12) and (is_num(ops[1])):
                out = [enc_i(v, 0, 0, rd, OP_I)]
            else:                                   # fixed 2 words, matching the size chosen in parse()
                hi, lo = split_hi_lo(v)
                out = [enc_u(hi, rd, OP_LUI), enc_i(lo, rd, 0, rd, OP_I)]
        else:
            raise AsmError(f'line {ln}: unknown instruction {mn!r}')
        for k, w in enumerate(out):
            words.append(w & 0xFFFFFFFF)
            listing.append((pc + 4 * k, w & 0xFFFFFFFF, src.strip() if k == 0 else '   (continued)'))
    return words, listing

# ---- self-check --------------------------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))

def selfcheck():
    # 1. the whole of gen_hex.py's program, assembled from text, matches program.hex word for word
    ref = [int(l, 16) for l in open(os.path.join(HERE, 'program.hex')).read().split()]
    words, _ = assemble(open(os.path.join(HERE, 'asm', 'default.s')).read())
    assert words == ref, 'default.s does not reproduce program.hex'
    # 2. encodings fixed by the ISA spec
    one = lambda s: assemble(s)[0]
    assert one('addi x1,x0,6') == [0x00600093]
    assert one('jal x0,0') == [0x0000006F]
    assert one('here: beq x0,x0,here') == [0x00000063]
    assert one('nop') == [0x00000013]
    assert one('ret') == [0x00008067]
    assert one('a: nop\nbne x1,x2,a') == [0x00000013, 0xFE209EE3]       # offset -4
    assert one('lw x9,12(x5)') == [0x00C2A483]
    assert one('li x5, 0xF0000000') == one('lui x5,0xF0000\naddi x5,x5,0')   # fixed two-word li
    assert one('li x5, 0x12345FFF') == one('lui x5,0x12346\naddi x5,x5,-1')  # low half sign-extends, hi compensates
    assert one('li t0, -5') == one('addi x5,x0,-5')
    # 3. forward label, and a label on its own line
    assert one('j end\nnop\nend:\nj end') == [one('jal x0,8')[0], 0x00000013, one('jal x0,0')[0]]
    # 3b. every label size decision made in parse() matches what encoding emitted (a mismatch skews all later labels)
    assert one('li t0,5\nli t1,0x12345\nla t2,end\nend: j end')[-1] == one('jal x0,0')[0]
    assert assemble('la t2,end\nend: nop')[1][2][0] == 8                      # la = 2 words, so 'end' is at byte 8
    # 4. everything unsupported is refused with a reason
    for bad in ('lb x1,0(x2)', 'sb x1,0(x2)', 'lhu x1,0(x2)', 'mul x1,x2,x3', 'ecall', 'frob x1',
                'addi x1,x0,5000', 'lw x1,0(x99)', 'slli x1,x1,32', 'j nowhere'):
        try: assemble(bad)
        except AsmError: continue
        raise AssertionError(f'accepted {bad!r}')
    print('rvasm selfcheck: OK (program.hex reproduced, %d words)' % len(ref))

def main(argv):
    if argv[:1] == ['--selfcheck']: return selfcheck()
    if not argv: sys.exit(__doc__)
    try: words, listing = assemble(open(argv[0]).read())
    except AsmError as e: sys.exit(f'rvasm: {e}')
    if '-o' in argv:
        json.dump({'imem': words}, open(argv[argv.index('-o') + 1], 'w'))
    for pc, w, src in listing: print('%04x  %08x  %s' % (pc, w, src))

if __name__ == '__main__':
    main(sys.argv[1:])
