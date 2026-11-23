// sim.js -- RV32I model of rtl/riscv_top.v running sw/program.hex (build B2 at 50 MHz, or the 62.5 MHz registered-CFU build), for demo/index.html.
// Single-cycle, like the core: one step() = one instruction = one clock.
// CFU behaviour is copied from rtl/cfu_mul.v and rtl/cfu_bitwise.v; MMIO map from sw/gen_hex.py.
(function (root) {
  // sw/gen_hex.py output, verbatim (41 instructions)
  const PROGRAM = [
    [0x00600093, 'addi x1,x0,6'], [0x00700113, 'addi x2,x0,7'],
    [0x002081b3, 'add  x3,x1,x2'], [0x40110233, 'sub  x4,x2,x1'],
    [0x00302023, 'sw   x3,0(x0)'], [0x00402223, 'sw   x4,4(x0)'],
    [0xf00002b7, 'lui  x5,0xF0000'], [0x0012a023, 'sw   x1,0(x5)'],
    [0x0022a223, 'sw   x2,4(x5)'],
    [0x00000413, 'addi x8,x0,0'], [0x0082a423, 'sw   x8,8(x5)'], [0x00c2a483, 'lw   x9,12(x5)'], [0x00902823, 'sw   x9,16(x0)'],
    [0x00100413, 'addi x8,x0,1'], [0x0082a423, 'sw   x8,8(x5)'], [0x00c2a483, 'lw   x9,12(x5)'], [0x00902a23, 'sw   x9,20(x0)'],
    [0x00200413, 'addi x8,x0,2'], [0x0082a423, 'sw   x8,8(x5)'], [0x00c2a483, 'lw   x9,12(x5)'], [0x00902c23, 'sw   x9,24(x0)'],
    [0x00300413, 'addi x8,x0,3'], [0x0082a423, 'sw   x8,8(x5)'], [0x00c2a483, 'lw   x9,12(x5)'], [0x00902e23, 'sw   x9,28(x0)'],
    [0x000103b7, 'lui  x7,0x10'], [0x0072a023, 'sw   x7,0(x5)'], [0x0072a223, 'sw   x7,4(x5)'],
    [0x00000413, 'addi x8,x0,0'], [0x0082a423, 'sw   x8,8(x5)'], [0x00c2a483, 'lw   x9,12(x5)'], [0x02902023, 'sw   x9,32(x0)'],
    [0x00100413, 'addi x8,x0,1'], [0x0082a423, 'sw   x8,8(x5)'], [0x00c2a483, 'lw   x9,12(x5)'], [0x02902223, 'sw   x9,36(x0)'],
    [0x00200413, 'addi x8,x0,2'], [0x0082a423, 'sw   x8,8(x5)'], [0x00c2a483, 'lw   x9,12(x5)'], [0x02902423, 'sw   x9,40(x0)'],
    [0x0000006f, 'jal  x0,0'],
  ];

  // 62.5 MHz build (riscv_pdr_62m5/sw/gen_hex.py): the CFU result is registered, so one nop follows every
  // `sw x8,8(x5)` (the fn write that starts a CFU op). Derived here so the two programs cannot drift apart.
  const NOP = [0x00000013, 'nop'];
  const PROGRAM_62M5 = PROGRAM.flatMap((ins) => (ins[1].startsWith('sw   x8,8(x5)') ? [ins, NOP] : [ins]));
  const BUILDS = {
    b2:    { program: PROGRAM,       registered: false, mhz: 50,   haltPc: 160 },
    '62m5': { program: PROGRAM_62M5, registered: true,  mhz: 62.5, haltPc: 188 },
    b3:    { program: PROGRAM,       registered: false, mhz: 40,   haltPc: 160 },   // B2 + PS program loader (rtl/imem.v, dmem.v): same timing model
  };

  const CFU_BASE = 0xF0000000;
  const CFU = {
    multiplier(a, b, fn) {                      // rtl/cfu_mul.v
      const p = BigInt(a) * BigInt(b);
      return Number(fn === 1 ? (p >> 32n) & 0xFFFFFFFFn : p & 0xFFFFFFFFn);
    },
    bitwise(a, b, fn) {                         // rtl/cfu_bitwise.v
      if (fn === 0) { let c = 0; for (let i = 0; i < 32; i++) c += (a >>> i) & 1; return c; }
      if (fn === 1) return (a & b) >>> 0;
      if (fn === 2) return (a ^ b) >>> 0;
      return a;
    },
  };

  const sx = (v, bits) => (v << (32 - bits)) >> (32 - bits);

  function decode(w) {
    const op = w & 0x7f, rd = (w >>> 7) & 31, f3 = (w >>> 12) & 7, rs1 = (w >>> 15) & 31,
      rs2 = (w >>> 20) & 31, f7 = w >>> 25;
    const immI = w >> 20;
    const immS = ((w >> 25) << 5) | ((w >>> 7) & 31);
    const immB = sx(((w >>> 31) << 12) | (((w >>> 7) & 1) << 11) | (((w >>> 25) & 63) << 5) | (((w >>> 8) & 15) << 1), 13);
    const immU = (w & 0xFFFFF000) | 0;
    const immJ = sx(((w >>> 31) << 20) | (((w >>> 12) & 255) << 12) | (((w >>> 20) & 1) << 11) | (((w >>> 21) & 1023) << 1), 21);
    return { op, rd, f3, rs1, rs2, f7, immI, immS, immB, immU, immJ };
  }

  function alu(f3, a, b, alt) {                 // signed 32-bit in, signed 32-bit out
    switch (f3) {
      case 0: return alt ? (a - b) | 0 : (a + b) | 0;
      case 1: return a << (b & 31);
      case 2: return a < b ? 1 : 0;
      case 3: return (a >>> 0) < (b >>> 0) ? 1 : 0;
      case 4: return a ^ b;
      case 5: return alt ? a >> (b & 31) : (a >>> (b & 31)) | 0;
      case 6: return a | b;
      case 7: return a & b;
    }
  }

  const REGN = (r) => 'x' + r;
  const hex8 = (w) => (w >>> 0).toString(16).padStart(8, '0');
  function disasm(w) {                          // RV32I subset the core implements; anything else prints as .word
    const d = decode(w), rd = REGN(d.rd), a = REGN(d.rs1), b = REGN(d.rs2), alt = d.f7 === 0x20;
    if (w === 0x13) return 'nop';
    switch (d.op) {
      case 0x33: return `${['add', 'sll', 'slt', 'sltu', 'xor', 'srl', 'or', 'and'][d.f3].replace('add', alt ? 'sub' : 'add').replace('srl', alt ? 'sra' : 'srl')} ${rd},${a},${b}`;
      case 0x13: return d.f3 === 1 || d.f3 === 5
        ? `${d.f3 === 1 ? 'slli' : alt ? 'srai' : 'srli'} ${rd},${a},${d.immI & 31}`
        : `${['addi', '', 'slti', 'sltiu', 'xori', '', 'ori', 'andi'][d.f3]} ${rd},${a},${d.immI}`;
      case 0x03: return d.f3 === 2 ? `lw ${rd},${d.immI}(${a})` : `.word 0x${hex8(w)}   (byte/half load: unsupported)`;
      case 0x23: return d.f3 === 2 ? `sw ${b},${d.immS}(${a})` : `.word 0x${hex8(w)}   (byte/half store: unsupported)`;
      case 0x63: return `${['beq', 'bne', '', '', 'blt', 'bge', 'bltu', 'bgeu'][d.f3]} ${a},${b},${d.immB}`;
      case 0x37: return `lui ${rd},0x${((d.immU >>> 12) & 0xFFFFF).toString(16)}`;
      case 0x17: return `auipc ${rd},0x${((d.immU >>> 12) & 0xFFFFF).toString(16)}`;
      case 0x6f: return `jal ${rd},${d.immJ}`;
      case 0x67: return `jalr ${rd},${d.immI}(${a})`;
    }
    return `.word 0x${hex8(w)}`;
  }

  class Core {
    constructor(variant = 'multiplier', build = 'b2') { this.variant = variant; this.build = build; this.custom = null; this.reset(); }

    get prog() { return this.custom ? this.custom.prog : BUILDS[this.build].program; }

    // A user program ({imem: [word...], dmem: [word...]}), as produced by sw/rvasm.py or sw/c/build.sh.
    // Uses the unregistered-CFU (B2 / b3) timing. null goes back to the baked demo program.
    loadProgram(p) {
      if (!p) { this.custom = null; this.reset(); return this; }
      if (p.imem.length > 256) throw new Error(`program is ${p.imem.length} words, imem holds 256`);
      this.custom = { prog: p.imem.map((w) => [w >>> 0, disasm(w)]), dmem: Uint32Array.from(p.dmem || []) };
      this.reset(); return this;
    }

    // Like the board: reset restarts the core but dmem keeps its contents (keepMem), or returns to the image loaded
    // with the program (power-on state).  poke/peek are the PS-side write and debug ports.
    reset(keepMem = false) {
      const old = this.dmem;
      this.pc = 0; this.x = new Int32Array(32);
      this.dmem = new Uint32Array(1024);
      if (keepMem && old) this.dmem.set(old); else if (this.custom) this.dmem.set(this.custom.dmem.subarray(0, 1024));
      this.cfu = { a: 0, b: 0, fn: 0, q: 0 }; this.cycles = 0; this.halted = false; this.last = null; this.fault = null;
    }
    peek(word) { return this.dmem[word & 1023]; }
    poke(word, v) { this.dmem[word & 1023] = v >>> 0; }

    load(addr) {
      addr >>>= 0;
      if (addr >= CFU_BASE) {
        if (addr !== CFU_BASE + 12) return 0;
        return BUILDS[this.build].registered ? this.cfu.q : CFU[this.variant](this.cfu.a, this.cfu.b, this.cfu.fn);
      }
      return this.dmem[(addr >>> 2) & 1023];
    }

    store(addr, v) {
      addr >>>= 0; v >>>= 0;
      if (addr >= CFU_BASE) { this.cfu[['a', 'b', 'fn'][(addr - CFU_BASE) >>> 2]] = addr === CFU_BASE + 8 ? v & 15 : v; return 'cfu'; }
      this.dmem[(addr >>> 2) & 1023] = v; return 'dmem';
    }

    // one clock: fetch, decode, execute, write back. Returns what happened, for the UI.
    step() {
      const P = this.prog, idx = this.pc >>> 2, w = P[idx] ? P[idx][0] : 0x13;   // off the end = nop
      const d = decode(w), x = this.x, a = x[d.rs1], b = x[d.rs2];
      // result_q <= result at every clock edge, computed from the operand registers as they were BEFORE this edge
      const qNext = CFU[this.variant](this.cfu.a, this.cfu.b, this.cfu.fn);
      let next = (this.pc + 4) | 0, wr = null, mem = null;
      switch (d.op) {
        case 0x33: wr = alu(d.f3, a, b, d.f7 === 0x20); break;
        case 0x13: wr = alu(d.f3, a, d.f3 === 5 ? d.immI & 31 : d.immI, d.f3 === 5 && d.f7 === 0x20); break;
        // rtl/control.v never looks at funct3 on loads/stores: lb/lh/sb/sh would run as lw/sw on the board and
        // quietly compute the wrong thing.  The model refuses to run them, so sim == board holds for every program that runs.
        case 0x03: {
          if (d.f3 !== 2) { this.fault = `byte/half load at pc ${this.pc}: the core is word-only`; next = this.pc; break; }
          const addr = (a + d.immI) | 0;
          wr = this.load(addr) | 0;
          mem = { kind: addr >>> 0 >= CFU_BASE ? 'cfu-read' : 'load', addr: addr >>> 0 }; break;
        }
        case 0x23: {
          if (d.f3 !== 2) { this.fault = `byte/half store at pc ${this.pc}: the core is word-only`; next = this.pc; break; }
          const addr = (a + d.immS) | 0;
          mem = { kind: this.store(addr, b), addr: addr >>> 0 }; break;
        }
        case 0x63: {
          const t = [a === b, a !== b, 0, 0, a < b, a >= b, (a >>> 0) < (b >>> 0), (a >>> 0) >= (b >>> 0)][d.f3];
          if (t) next = (this.pc + d.immB) | 0; break;
        }
        case 0x37: wr = d.immU; break;
        case 0x17: wr = (this.pc + d.immU) | 0; break;
        case 0x6f: wr = next; next = (this.pc + d.immJ) | 0; break;
        case 0x67: wr = next; next = ((a + d.immI) & ~1) | 0; break;
      }
      if (wr !== null && d.rd !== 0) x[d.rd] = wr;
      this.cfu.q = qNext;
      this.halted = next === this.pc;
      this.last = { pc: this.pc, idx, word: w, asm: P[idx] ? P[idx][1] : 'nop', rd: wr !== null ? d.rd : 0, mem };
      this.pc = next; this.cycles++;
      return this.last;
    }

    run(max = 1000) { while (!this.halted && max--) this.step(); return this; }
  }

  const RV = { PROGRAM, PROGRAM_62M5, BUILDS, CFU, Core, disasm };
  root.RV = RV;
  if (typeof module !== 'undefined') module.exports = RV;
})(typeof globalThis !== 'undefined' ? globalThis : this);
