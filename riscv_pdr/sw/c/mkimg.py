#!/usr/bin/env python3
"""mkimg.py prog.elf out.json [--no-cfu-libcalls] [--objdump PATH]

ELF -> {"imem": [word...], "dmem": [word...]} for the riscv_pdr loader, after a strict check of every instruction.

The guard exists because the core is quieter than it should be: control.v ignores funct3 on loads/stores (lb/sb run as
lw/sw) and treats unknown opcodes as nops.  A program that uses either would run and give wrong answers.  So only the
RV32I subset the RTL implements is let through, byte/half/M/CSR/system instructions are an error.
--no-cfu-libcalls additionally forbids calls to __mulsi3/__popcountsi2 (programs whose own addressing must not depend on
which unit is in the slot, e.g. rick.c).
"""
import json, re, struct, subprocess, sys

ALLOWED = set('add sub sll slt sltu xor srl sra or and addi slti sltiu xori ori andi slli srli srai lw sw '
              'beq bne blt bge bltu bgeu lui auipc jal jalr'.split())
IMEM_WORDS, DMEM_BASE, DMEM_WORDS = 256, 0x10000000, 1024

def guard(elf, objdump, no_libcalls):
    text = subprocess.run([objdump, '-d', '-M', 'no-aliases,numeric', '--no-show-raw-insn', elf],
                          check=True, capture_output=True, text=True).stdout
    bad = {}
    for line in text.splitlines():
        m = re.match(r'\s*[0-9a-f]+:\s+(\S+)', line)          # "  1c:  addi  x1,x0,5"
        if m and m.group(1) not in ALLOWED: bad.setdefault(m.group(1), line.strip())
    if bad:
        sys.exit('mkimg: instructions the core does not implement:\n' +
                 '\n'.join(f'  {mn:8} first at: {ln}' for mn, ln in sorted(bad.items())) +
                 '\n  (lb/lh/sb/sh run as lw/sw on this core; M, CSR and system instructions are absent -- use int/unsigned words only)')
    if no_libcalls:
        for sym in ('__mulsi3', '__popcountsi2', '__muldi3', '__divsi3', '__modsi3', '__umodsi3'):
            if re.search(r'\bjalr?\b[^\n]*<%s>' % sym, text): sys.exit(f'mkimg: --no-cfu-libcalls but the program calls {sym} (it would run on whatever unit is in the slot)')

def load(elf):
    d = open(elf, 'rb').read()
    if d[:4] != b'\x7fELF' or d[4] != 1 or d[5] != 1: sys.exit('mkimg: not a 32-bit little-endian ELF')
    entry, phoff = struct.unpack_from('<I', d, 24)[0], struct.unpack_from('<I', d, 28)[0]
    phentsize, phnum = struct.unpack_from('<HH', d, 42)
    imem, dmem, top = {}, {}, 0
    for k in range(phnum):
        t, off, va, pa, fsz, msz = struct.unpack_from('<IIIIII', d, phoff + k * phentsize)
        if t != 1 or msz == 0: continue                         # PT_LOAD only
        for i in range(msz):                                    # bytes beyond filesz are .bss: zero, written explicitly
            b = d[off + i] if i < fsz else 0
            a = va + i
            if a < IMEM_WORDS * 4: imem[a] = b
            elif DMEM_BASE <= a < DMEM_BASE + DMEM_WORDS * 4: dmem[a - DMEM_BASE] = b
            else: sys.exit(f'mkimg: section at 0x{a:08x} is outside imem (0..0x3FF) and dmem (0x10000000..0x10000FFF)')
    if entry != 0: sys.exit(f'mkimg: entry 0x{entry:x}, the core starts at pc 0')
    def words(m):
        n = (max(m) + 4) // 4 if m else 0
        return [sum(m.get(4 * w + j, 0) << (8 * j) for j in range(4)) for w in range(n)]
    return words(imem), words(dmem)

def main():
    a = [x for x in sys.argv[1:] if not x.startswith('--')]
    objdump = sys.argv[sys.argv.index('--objdump') + 1] if '--objdump' in sys.argv else 'riscv64-linux-gnu-objdump'
    if '--objdump' in sys.argv: a.remove(objdump)
    elf, out = a
    guard(elf, objdump, '--no-cfu-libcalls' in sys.argv)
    imem, dmem = load(elf)
    json.dump({'imem': imem, 'dmem': dmem}, open(out, 'w'))
    print(f'{out}: {len(imem)} instructions, {len(dmem)} dmem words')

if __name__ == '__main__':
    main()
