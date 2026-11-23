`timescale 1ns / 1ps
// -----------------------------------------------------------------------------
// imem.v -- instruction memory (word-addressed, async read, sync write).
// Based on the original instructions_set.v.  Power-on contents come from
// program.hex via $readmemh, so a board that has just been configured still runs
// the baked demo program.  The write port is the PS-side loader (riscv_top.v
// only enables it while the core is held in reset), which is how a program is
// put on the board without rebuilding the bitstream.
// 256 words = 1 KB of instruction space; infers distributed RAM (async read is
// what keeps fetch single-cycle -- BRAM would be synchronous-read).  It was 1024 words in the
// first b3 build: the PC then fanned out to 539 RAM cells through a 16-bank mux and the core
// only just met 50 MHz (WNS +0.05 ns, worst path 19.3 ns).  Words 256.. alias (pc[9:2] is
// used, higher bits ignored), so a program must fit: sw/rvasm.py, sw/c/mkimg.py and
// demo/loader.py all refuse anything longer.
// -----------------------------------------------------------------------------
module imem(
    input             clk,
    input             we,
    input      [9:0]  waddr,    // word index (bits above 7 ignored)
    input      [31:0] wdata,
    input      [31:0] addr,
    output     [31:0] ins
);
    reg [31:0] mem [0:255];
    initial $readmemh("program.hex", mem);
    always @(posedge clk)
        if (we) mem[waddr[7:0]] <= wdata;
    assign ins = mem[addr[9:2]];   // byte->word address
endmodule
