`timescale 1ns / 1ps
// -----------------------------------------------------------------------------
// imm_gen.v -- RV32I immediate generator (I/S/B/U/J).
// FIX vs original immediate_generator.v: every immediate is now SIGN-EXTENDED
// to 32 bits.  The original assigned only the raw 12/20-bit field into a 32-bit
// reg (zero-padded), so negative immediates, branches and jumps were all wrong.
// -----------------------------------------------------------------------------
module imm_gen(
    input      [31:0] ins,
    output reg [31:0] imm
);
    wire [6:0] op = ins[6:0];
    always @(*) begin
        case (op)
            7'b0010011,                       // I-type ALU (ADDI, ...)
            7'b0000011,                       // I-type load
            7'b1100111:                       // JALR
                imm = {{20{ins[31]}}, ins[31:20]};
            7'b0100011:                       // S-type (store)
                imm = {{20{ins[31]}}, ins[31:25], ins[11:7]};
            7'b1100011:                       // B-type (branch)
                imm = {{19{ins[31]}}, ins[31], ins[7], ins[30:25], ins[11:8], 1'b0};
            7'b0110111,                       // U-type LUI
            7'b0010111:                       // U-type AUIPC
                imm = {ins[31:12], 12'b0};
            7'b1101111:                       // J-type JAL
                imm = {{11{ins[31]}}, ins[31], ins[19:12], ins[20], ins[30:21], 1'b0};
            default:
                imm = 32'b0;
        endcase
    end
endmodule
