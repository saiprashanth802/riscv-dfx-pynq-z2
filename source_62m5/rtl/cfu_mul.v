`timescale 1ns / 1ps
// -----------------------------------------------------------------------------
// cfu_mul.v -- RECONFIGURABLE VARIANT A: 32x32 multiplier.
//
// This is one of the modules that gets loaded into the reconfigurable partition
// at runtime.  It MUST match the frozen `cfu` interface exactly (same module
// name, same port list) as cfu_bitwise.v -- do not change the ports.
//
// Gives the RV32I core a multiply it otherwise lacks:
//   fn = 0 -> low  32 bits of op_a*op_b (MUL)
//   fn = 1 -> high 32 bits            (MULH-ish, unsigned)
// Combinational, so `done` is tied high.  On the FPGA this maps to DSP48 slices
// (include DSP columns in the Pblock for the reconfigurable partition).
// -----------------------------------------------------------------------------
module cfu(
    input             clk,
    input             rst,
    input             start,
    input      [31:0] op_a,
    input      [31:0] op_b,
    input      [3:0]  fn,
    output     [31:0] result,
    output            done
);
    wire [63:0] prod = op_a * op_b;
    assign result = (fn == 4'd1) ? prod[63:32] : prod[31:0];
    assign done   = 1'b1;
endmodule
