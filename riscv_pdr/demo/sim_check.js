// node demo/sim_check.js -- the browser model must reproduce tb/tb_riscv.v's expected values, for both builds.
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const RV = require('./sim.js');
const { Core, BUILDS, PROGRAM, PROGRAM_62M5 } = RV;

const common = { 0: 13, 1: 1 };
const expect = {
  multiplier: { 4: 42, 5: 0, 6: 42, 7: 42, 8: 0, 9: 1, 10: 0 },
  bitwise:    { 4: 2, 5: 6, 6: 1, 7: 6, 8: 1, 9: 0x10000, 10: 0 },
};

for (const build of Object.keys(BUILDS)) {
  for (const variant of Object.keys(expect)) {
    const c = new Core(variant, build).run();
    assert(c.halted, `${build}/${variant}: did not halt`);
    assert.strictEqual(c.pc, BUILDS[build].haltPc, `${build}/${variant}: halted at pc ${c.pc}`);   // tb: "halted at pc"
    assert.strictEqual(c.x[3], 13); assert.strictEqual(c.x[4], 1);
    for (const [k, v] of Object.entries({ ...common, ...expect[variant] }))
      assert.strictEqual(c.dmem[k], v, `${build}/${variant}: mem[${k}] = ${c.dmem[k]}, expected ${v}`);
    console.log(`${build}/${variant}: ok (${c.cycles} cycles)`);
  }
  // swap mid-demo semantics: same Core object, variant changed, reset, rerun
  const c = new Core('multiplier', build).run(); c.variant = 'bitwise'; c.reset(); c.run();
  assert.strictEqual(c.dmem[4], 2, `${build}: swap then rerun`);
}

// the registered CFU is why the nop exists: the 41-instruction program on the registered core reads stale results
{
  const c = new Core('multiplier', '62m5'); c.build = '62m5';
  const saved = BUILDS['62m5'].program; BUILDS['62m5'].program = PROGRAM;
  c.run(); BUILDS['62m5'].program = saved;
  // word 4 is fn0, which the CFU already holds at reset, so it reads right by coincidence; word 5 (fn1, high half) does not
  assert.notStrictEqual(c.dmem[5], 0, 'without the nop the registered core must read a stale result');
  console.log(`62m5 without nop: mem[5] = ${c.dmem[5]}, should be 0 (stale, as expected)`);
}

// the derived 62.5 MHz program must equal the real riscv_pdr_62m5 program.hex, word for word
const hex = path.join(__dirname, '..', '..', 'riscv_pdr_62m5', 'sw', 'program.hex');
if (fs.existsSync(hex)) {
  const words = fs.readFileSync(hex, 'utf8').split(/\s+/).filter(Boolean).map((h) => parseInt(h, 16));
  assert.deepStrictEqual(PROGRAM_62M5.map((i) => i[0]), words, 'PROGRAM_62M5 differs from riscv_pdr_62m5/sw/program.hex');
  console.log(`62m5 program matches program.hex (${words.length} words)`);
} else console.log('62m5 program.hex not found; skipped the word-for-word comparison');

// ---- user programs: disassembler, assembler -> model, byte-op refusal -------------------------------------------------
const { execFileSync } = require('child_process');
const { disasm } = RV;
const norm = (s) => s.replace(/\s+/g, ' ').trim().toLowerCase();
for (const [w, text] of PROGRAM) assert.strictEqual(norm(disasm(w)), norm(text), `disasm(0x${w.toString(16)})`);
console.log(`disasm reproduces all ${PROGRAM.length} baked instructions`);

const asm = (file) => {                                    // sw/rvasm.py is the assembler of record; no second one to drift
  const out = path.join(require('os').tmpdir(), `sim_check_${process.pid}_${path.basename(file)}.json`);
  execFileSync('python3', [path.join(__dirname, '..', 'sw', 'rvasm.py'), file, '-o', out], { stdio: 'pipe' });
  const p = JSON.parse(fs.readFileSync(out, 'utf8')); fs.unlinkSync(out); return p;
};
{
  const dflt = asm(path.join(__dirname, '..', 'sw', 'asm', 'default.s'));
  assert.deepStrictEqual(dflt.imem, PROGRAM.map((i) => i[0]), 'default.s != baked PROGRAM');
  const c = new Core('multiplier').loadProgram(dflt).run();
  assert.strictEqual(c.dmem[4], 42); assert.strictEqual(c.pc, BUILDS.b2.haltPc);
  const s = new Core('bitwise').loadProgram(asm(path.join(__dirname, '..', 'sw', 'asm', 'sum10.s'))).run();
  assert(s.halted && !s.fault); assert.strictEqual(s.dmem[0], 55, 'sum 1..10'); assert.strictEqual(s.cycles, 3 + 10 * 3 + 1 + 1);
  console.log(`asm: default.s == baked program; sum10 -> ${s.dmem[0]} in ${s.cycles} cycles (branch encodings decoded independently)`);
}
{
  const sb = new Core('multiplier').loadProgram({ imem: [0x00500093, 0x00100023, 0x0000006f], dmem: [] }).run();   // addi x1,x0,5 ; sb x1,0(x0)
  assert(sb.fault && sb.halted, 'sb must fault'); console.log('byte store faults:', sb.fault);
  // reset keeps dmem (the rick decoder depends on it); a fresh load restores the program's image
  const k = new Core('multiplier').loadProgram({ imem: [0x0000006f], dmem: [7] }); k.poke(5, 99); k.reset(true);
  assert.strictEqual(k.peek(5), 99); assert.strictEqual(k.peek(0), 7); k.reset(); assert.strictEqual(k.peek(5), 0);
  console.log('reset(keepMem) keeps dmem; reset() restores the loaded image');
}

// the testbench's loaded CFU program (tb/tb_riscv.v step 5): same words, same data, same answers as the RTL
{
  const prog = { imem: [0x19002083, 0x19402103, 0xf00002b7, 0x0012a023, 0x0022a223, 0x00200413, 0x0082a423, 0x00c2a483, 0x18902c23, 0x0000006f], dmem: [] };
  prog.dmem[100] = 0x12345678; prog.dmem[101] = 0x0F0F0F0F;
  const m = new Core('multiplier').loadProgram(prog).run(), b = new Core('bitwise').loadProgram(prog).run();
  assert.strictEqual(m.dmem[102], 0x3b2a1908); assert.strictEqual(b.dmem[102], 0x1d3b5977);
  assert.strictEqual(m.cycles, 10); assert.strictEqual(b.cycles, 10);
  console.log('tb step 5 program: mul 0x3b2a1908 / xor 0x1d3b5977, 10 cycles -- identical to the RTL testbench');
}

// ---- C programs built by sw/c/build.sh (skipped, loudly, when the cross compiler is absent) ---------------------------
const SWC = path.join(__dirname, '..', 'sw', 'c');
const cbuild = (name, ...flags) => {
  try { execFileSync(path.join(SWC, 'build.sh'), [path.join(SWC, name + '.c'), ...flags], { stdio: 'pipe' }); }
  catch (e) { if (/ENOENT|not found/.test(String(e.stderr) + e.message)) return null; throw new Error(`build ${name}: ${e.stderr}`); }
  return JSON.parse(fs.readFileSync(path.join(SWC, 'out', name + '.json'), 'utf8'));
};
const withIn = (p, vals) => { const q = { imem: p.imem, dmem: p.dmem.slice() }; vals.forEach((v, i) => { q.dmem[64 + i] = v; }); return q; };
const calc = cbuild('calc');
if (!calc) console.log('SKIPPED C-program checks: riscv64-linux-gnu-gcc not found');
else {
  // the swap changes THIS program's answers: * and popcount both go to fn 0 of whichever unit is loaded
  const m = new Core('multiplier').loadProgram(withIn(calc, [6, 7])).run(), b = new Core('bitwise').loadProgram(withIn(calc, [6, 7])).run();
  assert(m.halted && !m.fault && b.halted && !b.fault);
  assert.deepStrictEqual([0, 1, 2, 3].map((i) => m.dmem[i]), [42, 0, 6, 43], 'calc, multiplier in the slot');
  assert.deepStrictEqual([0, 1, 2, 3].map((i) => b.dmem[i]), [2, 2, 6, 3], 'calc, bitwise in the slot');
  console.log(`calc.c: multiplier -> [42, popcount 0, 6, 43]; bitwise -> [6*7 gives 2, popcount 2, 6, 3]  (${m.cycles} cycles)`);

  const bench = cbuild('bench'), N = 8, X0 = 1000, Y0 = 2000;
  const want = Array.from({ length: N }, (_, k) => Math.imul(X0 + k + 1, Y0 + k + 1)).reduce((a, v) => (a + v) | 0, 0) >>> 0;
  const run = (variant, mode) => new Core(variant).loadProgram(withIn(bench, [N, X0, Y0, mode])).run();
  const sm = run('multiplier', 0), cm = run('multiplier', 1), sb = run('bitwise', 0), cb = run('bitwise', 1);
  assert.strictEqual(sm.dmem[0], want); assert.strictEqual(cm.dmem[0], want); assert.strictEqual(sb.dmem[0], want);
  assert.notStrictEqual(cb.dmem[0], want, 'bitwise unit: `*` must NOT be a multiply');
  assert(cm.cycles < sm.cycles, 'the multiplier slot must beat the software loop');
  console.log(`bench.c: soft ${sm.cycles} cycles, slot ${cm.cycles} cycles, same checksum 0x${want.toString(16)}; bitwise slot: \`*\` -> 0x${cb.dmem[0].toString(16)} (wrong, as it should be)`);
}

// ---- rick: encoder -> C decoder -> model == the source frames, and the swap really breaks it ---------------------------
const rick = cbuild('rick', '--no-cfu-libcalls');
if (rick) {
  const synth = path.join(require('os').tmpdir(), `rick_synth_${process.pid}.json`);
  execFileSync('python3', [path.join(__dirname, '..', 'sw', 'rick', 'encode.py'), '--synthetic', synth], { stdio: 'pipe' });
  const R = JSON.parse(fs.readFileSync(synth, 'utf8')); fs.unlinkSync(synth);
  // variantAt(n) = which unit is in the slot while frame n is decoded (a partial reconfiguration between two frames)
  const decodeAll = (variantAt) => {
    const core = new Core('bitwise').loadProgram(rick), shown = []; let cycles = 0;
    R.frames.forEach((f, n) => {
      core.variant = variantAt(n);
      for (let k = 0; k < Math.max(1, f.p.length); k += 400) {                     // at most 200 pairs per run, as the server feeds it
        const part = f.p.slice(k, k + 400);
        core.poke(576, k === 0 ? f.c : 0); core.poke(577, part.length / 2); part.forEach((v, i) => core.poke(578 + i, v));
        core.reset(true); core.run(100000);                                        // dmem (the framebuffer) survives the reset
        assert(core.halted && !core.fault, `frame ${n}`);
        cycles += core.cycles;
      }
      shown.push(Array.from(core.dmem.subarray(0, 576)));
    });
    return { shown, cycles };
  };
  const ok = decodeAll(() => 'bitwise');
  ok.shown.forEach((fb, n) => assert.deepStrictEqual(fb, R.ref[n], `rick frame ${n} != source`));
  console.log(`rick.c: ${R.frames.length} frames decoded through CFU fn2 == the source frames; ${Math.round(ok.cycles / R.frames.length)} cycles/frame`);
  // multiplier in the slot for frames 12..15, bitwise again from 16 (mid-GOP; key frames are at 0, 10, 20)
  const swapped = decodeAll((n) => (n >= 12 && n < 16 ? 'multiplier' : 'bitwise')).shown;
  const right = (n) => JSON.stringify(swapped[n]) === JSON.stringify(R.ref[n]);
  assert(right(11), 'before the swap: fine');
  assert(!right(13) && !right(15), 'multiplier in the slot: XOR is replaced by a product, the picture is wrong');
  assert(!right(17) && !right(19), 'bitwise is back but the framebuffer is still corrupt: deltas XOR onto garbage');
  assert(right(20) && right(21) && right(29), 'the key frame at 20 clears and rebuilds the picture; it stays right after');
  console.log('rick swap gag: right to frame 11, wrong with the multiplier in frames 12-15, still wrong until the key frame at 20, right again from there');
}
