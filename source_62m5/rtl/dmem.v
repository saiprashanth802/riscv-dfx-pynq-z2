`timescale 1ns / 1ps
// -----------------------------------------------------------------------------
// dmem.v -- data memory (word-addressed BRAM).  Sync write, async read.
// This module DID NOT EXIST in the original project -- load_word.v/store_word.v
// only computed effective addresses (and store_word/load_word had a 1-bit addr
// bug), so LW/SW could never actually move data.  Word (LW/SW) only; byte/half
// access (LB/LH/SB/SH) is left as documented future work.
//
// A second, READ-ONLY debug port (dbg_addr/dbg_data) is brought out so the
// board top level can show banked results on the LEDs without the CPU having to
// cooperate.  Distributed RAM gives extra async read ports essentially free.
// -----------------------------------------------------------------------------
module dmem(
    input             clk,
    input             we,
    input      [31:0] addr,
    input      [31:0] wdata,
    output     [31:0] rdata,
    input      [9:0]  dbg_addr,     // word index
    output     [31:0] dbg_data
);
    reg [31:0] mem [0:1023];
    always @(posedge clk)
        if (we) mem[addr[11:2]] <= wdata;
    assign rdata    = mem[addr[11:2]];
    assign dbg_data = mem[dbg_addr];
endmodule
