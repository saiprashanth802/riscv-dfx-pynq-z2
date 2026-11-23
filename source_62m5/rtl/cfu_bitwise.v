`timescale 1ns / 1ps
// -----------------------------------------------------------------------------
// cfu_bitwise.v -- RECONFIGURABLE VARIANT B: bitwise/logic accelerator.
//
// Second module for the reconfigurable partition.  IDENTICAL port list to
// cfu_mul.v (the frozen `cfu` interface) so the same partial-reconfiguration
// slot accepts either one.  Compile EXACTLY ONE of cfu_mul.v / cfu_bitwise.v
// into the static build; in the DFX flow they become the two reconfigurable
// modules for the partition.
//
//   fn = 0 -> popcount(op_a)
//   fn = 1 -> op_a & op_b
//   fn = 2 -> op_a ^ op_b
//   else   -> op_a  (pass-through)
// -----------------------------------------------------------------------------
module cfu(
    input             clk,
    input             rst,
    input             start,
    input      [31:0] op_a,
    input      [31:0] op_b,
    input      [3:0]  fn,
    output reg [31:0] result,
    output            done
);
    integer i;
    reg [31:0] cnt;
    always @(*) begin
        case (fn)
            4'd0: begin
                cnt = 32'd0;
                for (i = 0; i < 32; i = i + 1) cnt = cnt + op_a[i];
                result = cnt;
            end
            4'd1:    result = op_a & op_b;
            4'd2:    result = op_a ^ op_b;
            default: result = op_a;
        endcase
    end
    assign done = 1'b1;
endmodule
