`timescale 1ns / 1ps
// -----------------------------------------------------------------------------
// alu.v -- RV32I integer ALU.
// Replaces ALU_32bit.v, whose case() body was EMPTY (`case(op) 7'd  default:;`)
// so it computed nothing.  ctrl encoding is produced by control.v.
//   0 ADD  1 SUB  2 SLL  3 SLT  4 SLTU  5 XOR  6 SRL  7 SRA  8 OR  9 AND
// Shift amount is b[4:0] (works for R-type rs2 and I-type shamt alike).
// -----------------------------------------------------------------------------
module alu(
    input      [31:0] a,
    input      [31:0] b,
    input      [3:0]  ctrl,
    output reg [31:0] y
);
    always @(*) begin
        case (ctrl)
            4'd0: y = a + b;
            4'd1: y = a - b;
            4'd2: y = a << b[4:0];
            4'd3: y = ($signed(a) < $signed(b)) ? 32'd1 : 32'd0;
            4'd4: y = (a < b) ? 32'd1 : 32'd0;
            4'd5: y = a ^ b;
            4'd6: y = a >> b[4:0];
            4'd7: y = $signed(a) >>> b[4:0];
            4'd8: y = a | b;
            4'd9: y = a & b;
            default: y = 32'b0;
        endcase
    end
endmodule
