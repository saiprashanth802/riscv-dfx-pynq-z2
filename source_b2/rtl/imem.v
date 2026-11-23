`timescale 1ns / 1ps
// -----------------------------------------------------------------------------
// imem.v -- instruction memory (word-addressed, async read).
// Based on the original instructions_set.v.  Loads program.hex via $readmemh.
// 1024 words = 4 KB of instruction space.  On Xilinx this infers LUTRAM/BRAM.
// -----------------------------------------------------------------------------
module imem(
    input      [31:0] addr,
    output     [31:0] ins
);
    reg [31:0] mem [0:1023];
    initial $readmemh("program.hex", mem);
    assign ins = mem[addr[11:2]];   // byte->word address
endmodule
