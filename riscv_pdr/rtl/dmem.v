`timescale 1ns / 1ps
// -----------------------------------------------------------------------------
// dmem.v -- data memory (word-addressed distributed RAM).  Sync write, async read.
// This module DID NOT EXIST in the original project -- load_word.v/store_word.v
// only computed effective addresses (and store_word/load_word had a 1-bit addr
// bug), so LW/SW could never actually move data.  Word (LW/SW) only; byte/half
// access (LB/LH/SB/SH) is left as documented future work -- and control.v does
// not decode funct3 on loads/stores, so those instructions run as lw/sw.
//
// A second, READ-ONLY debug port (dbg_addr/dbg_data) is brought out so the
// board top level can show banked results on the LEDs without the CPU having to
// cooperate.  Distributed RAM gives extra async read ports essentially free.
//
// ps_we/ps_addr/ps_wdata is the PS-side write port (program data in, board
// only).  riscv_top.v raises ps_we only while the core is in reset, and gates
// the core's own write with ~reset, so the two sources never collide.
// -----------------------------------------------------------------------------
module dmem(
    input             clk,
    input             we,
    input      [31:0] addr,
    input      [31:0] wdata,
    output     [31:0] rdata,
    input             ps_we,
    input      [9:0]  ps_addr,      // word index
    input      [31:0] ps_wdata,
    input      [9:0]  dbg_addr,     // word index
    output     [31:0] dbg_data
);
    reg [31:0] mem [0:1023];
    always @(posedge clk)
        if (ps_we)    mem[ps_addr]    <= ps_wdata;
        else if (we)  mem[addr[11:2]] <= wdata;
    assign rdata    = mem[addr[11:2]];
    assign dbg_data = mem[dbg_addr];
endmodule
