// panels.js -- "Run a program on the core" and "A video, decoded by the core" for index.html.
// Everything here has two sources: the board (LIVE: /api/program, /api/run, /api/clip, /api/rick through the page's transport,
// window.RVDEMO.api) and the page's own RV32I model (sim.js).  In LIVE mode every board result is also run through the model
// and compared, word for word and cycle for cycle.
(() => {
  const A = window.APPS, D = window.RVDEMO, RVm = window.RV;
  if (!A || !D || !RVm) return;
  const $ = (id) => document.getElementById(id);
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const hex = (v) => '0x' + (v >>> 0).toString(16);
  const fmt = (v) => { v >>>= 0; return v > 0xFFFF ? hex(v) : String(v); };
  const esc = (t) => String(t).replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
  const VARN = { multiplier: 'multiplier in the slot', bitwise: 'bitwise unit in the slot' };
  $('usr').hidden = false;

  // ----- model runs -----
  function simRun(img, variant, inputs, read) {
    const c = new RVm.Core(variant).loadProgram({ imem: img.imem, dmem: img.dmem || [] });
    for (const [b, vals] of Object.entries(inputs || {})) vals.forEach((v, i) => c.poke(+b + i, v));
    c.run(200000);
    return { words: Array.from(c.dmem.subarray(read[0], read[0] + read[1])), cycles: c.cycles, halted: c.halted, fault: c.fault };
  }
  const post = (path, body) => D.api(path, 'POST', 120000, body);
  const same = (board, sim) => board.cycles === sim.cycles && board.words.join() === sim.words.join();

  // ----- program panel -----
  const PROGS = [
    { id: 'sum10', label: 'Assembly: sum 1 … 10 (editable)', kind: 'asm', text: A.asm.sum10.src },
    ...(A.c.calc ? [{ id: 'calc', label: 'C: a × b and popcount(a)', kind: 'calc', text: A.c.calc.src, inputs: [['a', 6], ['b', 7]] }] : []),
    ...(A.c.bench ? [{ id: 'bench', label: 'C: software multiply vs the slot', kind: 'bench', text: A.c.bench.src, inputs: [['n', 8]] }] : []),
  ];
  const sel = $('progSel');
  sel.innerHTML = PROGS.map((p, i) => `<option value="${i}">${esc(p.label)}</option>`).join('');
  const cur = () => PROGS[+sel.value];
  function pick() {
    const p = cur();
    $('progSrcTxt').value = p.text; $('progSrcTxt').readOnly = p.kind !== 'asm';
    $('progIn').innerHTML = (p.inputs || []).map(([k, v]) => `<label>${k} <input type="number" id="in_${k}" value="${v}" min="0" max="4294967295"></label>`).join('');
    $('progOut').hidden = true;
    $('progNote').textContent = {
      asm: 'Assembled and written into the core\'s instruction memory by the PS while the core is held in reset, then released. The cycle count comes from a counter in the fabric.',
      calc: 'The source is C. gcc has no multiply or popcount instruction for RV32I, so it calls library routines; here they send their operands to the slot. Swap the slot and run again: the same program gives different answers.',
      bench: 'The same multiplications once with a software shift-and-add loop and once through the slot. With the bitwise unit loaded, * no longer multiplies.',
    }[p.kind];
  }
  sel.onchange = pick; pick();

  const where = (live) => (live ? 'On the board' : 'Simulation (this page\'s model)');
  function show(html, bad) {
    const o = $('progOut'); o.hidden = false; o.className = 'boardres prog-out' + (bad ? ' bad' : ''); o.innerHTML = html;
  }
  const row = (k, v) => `<tr><th>${k}</th><td>${v}</td></tr>`;
  const agreeTxt = (ok, live) => (live ? (ok ? '<span>The board agrees with the model, word for word and cycle for cycle.</span>' : '<strong>The board does NOT match the model.</strong>') : '');

  async function runProgram() {
    const p = cur(), live = D.isLive(), v = D.variant(), btn = $('progRun');
    rickPause(); btn.disabled = true;
    try {
      if (p.kind === 'asm') {
        const src = $('progSrcTxt').value;
        if (!live && src.trim() !== A.asm.sum10.src.trim()) return show('Editing assembly needs the board: it is assembled there (sw/rvasm.py). The unedited example runs in simulation.', true);
        const read = [0, 4];
        let board = null, imem = A.asm.sum10.imem;
        if (live) {
          board = await post('api/program', { src, name: 'asm', read });
          if (board.error) return show(`<strong>${esc(board.error)}</strong>`, true);
          imem = board.listing.map((l) => l[1]);
        }
        const sim = simRun({ imem }, v, {}, read), m = board || sim, ok = !board || same(board, sim);
        show(`<div><strong>${where(live)}: ${m.halted ? 'halted' : 'did not halt'} after ${m.cycles} cycles</strong> <span class="muted">(${imem.length} instructions, ${VARN[v]})</span></div>` +
          `<table>${[0, 1, 2, 3].map((i) => row(`mem[${i}]`, fmt(m.words[i]))).join('')}</table>` + agreeTxt(ok, live), !ok);
      } else if (p.kind === 'calc') {
        const a = +$('in_a').value >>> 0, b = +$('in_b').value >>> 0, read = [0, 4], inputs = { 64: [a, b] };
        const img = A.c.calc;
        const board = live ? await post('api/program', { imem: img.imem, dmem: img.dmem, name: 'calc', inputs, read }) : null;
        if (board && board.error) return show(`<strong>${esc(board.error)}</strong>`, true);
        const sim = simRun(img, v, inputs, read), m = board || sim, ok = !board || same(board, sim);
        const exact = Math.imul(a, b) >>> 0, pc = a.toString(2).split('1').length - 1;
        show(`<div><strong>${where(live)}: ${m.cycles} cycles · ${VARN[v]}</strong></div><table>` +
          row(`${fmt(a)} × ${fmt(b)}`, `${fmt(m.words[0])} ${m.words[0] === exact ? '<span class="muted">(correct)</span>' : `<strong>(a real multiply gives ${fmt(exact)})</strong>`}`) +
          row(`popcount(${fmt(a)})`, `${fmt(m.words[1])} ${m.words[1] === pc ? '<span class="muted">(correct)</span>' : `<strong>(the right answer is ${pc})</strong>`}`) +
          row('a &amp; b', `${fmt(m.words[2])} <span class="muted">(plain RV32I, same either way)</span>`) + `</table>` + agreeTxt(ok, live), !ok);
      } else {
        const n = Math.max(1, Math.min(200, +$('in_n').value | 0)), img = A.c.bench, read = [0, 1];
        const mk = (mode) => ({ 64: [n, 1000, 2000, mode] });
        const out = [];
        for (const mode of [0, 1]) {
          const board = live ? await (mode === 0 ? post('api/program', { imem: img.imem, dmem: img.dmem, name: 'bench', inputs: mk(0), read }) : post('api/run', { inputs: mk(1), read })) : null;
          if (board && board.error) return show(`<strong>${esc(board.error)}</strong>`, true);
          const sim = simRun(img, v, mk(mode), read);
          out.push({ m: board || sim, ok: !board || same(board, sim) });
        }
        const [soft, slot] = out, ok = out.every((o) => o.ok), agree = soft.m.words[0] === slot.m.words[0];
        show(`<div><strong>${where(live)} · ${VARN[v]}</strong></div><table>` +
          row('software loop', `${soft.m.cycles} cycles · checksum ${hex(soft.m.words[0])}`) +
          row('through the slot', `${slot.m.cycles} cycles · checksum ${hex(slot.m.words[0])}`) + `</table>` +
          (agree ? `<span>The slot takes <strong>${(soft.m.cycles / slot.m.cycles).toFixed(1)}× fewer cycles</strong> and gives the same answer.</span>`
                 : `<strong>Different checksums: with the ${v} unit in the slot, * is not a multiply.</strong>`) + agreeTxt(ok, live), !ok);
      }
      $('progSrc').textContent = where(live);
    } catch (e) { show(`<strong>${esc(e.message || e)}</strong>`, true); } finally { btn.disabled = false; }
  }
  $('progRun').onclick = runProgram;

  // ----- video panel -----
  const clip = A.clip, img = A.c.rick, W = 96, H = 64, PLANE = 192, FB = 576, CHUNK = 200;
  const cv = $('rickCv'), ctx = cv.getContext('2d'), px = ctx.createImageData(W, H);
  function draw(fb) {
    for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
      const o = 4 * (y * W + x), i = 3 * y + (x >> 5);
      for (let c = 0; c < 3; c++) px.data[o + c] = (fb[c * PLANE + i] >>> (x & 31)) & 1 ? 240 : 10;
      px.data[o + 3] = 255;
    }
    ctx.putImageData(px, 0, 0);
  }
  $('rickSrc').textContent = clip.test ? 'test pattern: encode a clip with sw/rick/encode.py' : `${clip.frames.length} frames · ${clip.fps} fps · 96 × 64 · 8 colours`;
  const simCore = img ? new RVm.Core('bitwise').loadProgram(img) : null;
  function simFrames(from, n, variant) {
    const frames = [], cycles = [];
    for (let i = 0; i < n && from + i < clip.frames.length; i++) {
      const f = clip.frames[from + i];
      simCore.variant = variant; let total = 0;
      for (let k = 0; k < Math.max(1, f.p.length); k += 2 * CHUNK) {          // same chunks as the board: see sw/c/rick.c
        const part = f.p.slice(k, k + 2 * CHUNK);
        simCore.poke(FB, k === 0 ? f.c : 0); simCore.poke(FB + 1, part.length / 2); part.forEach((v, j) => simCore.poke(FB + 2 + j, v));
        simCore.reset(true); simCore.run(100000); total += simCore.cycles;
      }
      frames.push(Array.from(simCore.dmem.subarray(0, FB))); cycles.push(total);
    }
    return { frames, cycles };
  }
  let playing = false, nextIdx = 0, buf = [], inflight = false, hold = false, tick = null, st = { cyc: 0, n: 0, ms: 0 };
  const slotPill = () => {
    const v = D.variant(), p = $('rickSlot');
    p.textContent = v === 'bitwise' ? 'bitwise unit · fn 2 = XOR · picture decodes' : 'multiplier · fn 2 = a × b · picture breaks';
    p.className = 'pill ' + (v === 'bitwise' ? 'run' : 'warn');
  };
  function info(extra) {
    const live = D.isLive(), per = st.n ? Math.round(st.cyc / st.n) : null;
    $('rickInfo').textContent = (live ? 'Decoded on the board' : 'Decoded by the page\'s model') + (per ? ` · ${per} clock cycles per frame` : '') +
      (live && st.n ? ` · ${(st.ms / st.n).toFixed(0)} ms per frame including the AXI traffic` : '') + (extra ? ' · ' + extra : '');
  }
  async function ensureBoard() {
    const s = await D.api('api/loader');
    if (s.error || !s.available) throw new Error(s.error || 'this build has no program loader: switch to b3');
    if (!s.program || s.program.name !== 'rick') { const r = await post('api/program', { imem: img.imem, dmem: img.dmem, name: 'rick', run: false }); if (r.error) throw new Error(r.error); }
    if (s.clip_frames !== clip.frames.length) { const r = await post('api/clip', { frames: clip.frames }); if (r.error) throw new Error(r.error); }
  }
  async function pump() {
    if (inflight || !playing || hold || buf.length >= 4) return;
    inflight = true;
    try {
      const live = D.isLive(), n = 5; let r;
      if (live) { r = await post(`api/rick?from=${nextIdx}&n=${n}`); if (r.error) throw new Error(r.error); }
      else r = simFrames(nextIdx, n, D.variant());
      buf.push(...r.frames); nextIdx = (nextIdx + r.frames.length) % clip.frames.length;
      st.cyc += r.cycles.reduce((a, b) => a + b, 0); st.n += r.frames.length; st.ms += live ? r.ms : 0;
    } catch (e) { rickPause(); info('stopped: ' + (e.message || e)); } finally { inflight = false; }
  }
  function rickPause() { playing = false; clearInterval(tick); tick = null; $('rickPlay').textContent = 'Play'; }
  $('rickPlay').onclick = async () => {
    if (playing) return rickPause();
    if (!img) return info('rick.c is not built (no cross compiler)');
    $('rickPlay').disabled = true;
    try {
      if (D.isLive()) await ensureBoard();
      nextIdx = 0; buf = []; st = { cyc: 0, n: 0, ms: 0 };
      if (!D.isLive()) simCore.reset();   // power-on state
      playing = true; $('rickPlay').textContent = 'Pause'; slotPill();
      tick = setInterval(() => { if (buf.length) draw(buf.shift()); pump(); info(buf.length ? '' : 'buffering'); }, 1000 / clip.fps);
      pump();
    } catch (e) { info(e.message || String(e)); } finally { $('rickPlay').disabled = false; }
  };
  $('rickSwap').onclick = async () => {
    if (D.busy()) return;
    hold = true; while (inflight) await sleep(20);
    D.swapClick();                                  // the page's own swap: animation, and the real partial bitstream on the board
    await sleep(150); while (D.busy()) await sleep(100);
    hold = false; slotPill(); pump();
  };
  slotPill();
  if (img) { draw(simFrames(0, 1, 'bitwise').frames[0]); simCore.reset(); }   // something on the canvas before Play
  info();
})();
