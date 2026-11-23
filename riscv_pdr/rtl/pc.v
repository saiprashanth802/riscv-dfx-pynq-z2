`timescale 1ns / 1ps
// -----------------------------------------------------------------------------
// pc.v -- program counter register with synchronous reset.
// Based on the original pc_riscv.v (which was already correct) but simplified to
// take a fully-computed next_pc from the top level.
// -----------------------------------------------------------------------------
module pc(
    input             clk,
    input             reset,
    input      [31:0] next_pc,
    output reg [31:0] pc
);
    always @(posedge clk)
        if (reset) pc <= 32'b0;
        else       pc <= next_pc;
endmodule
