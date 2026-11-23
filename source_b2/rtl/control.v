`timescale 1ns / 1ps
// -----------------------------------------------------------------------------
// control.v -- single-cycle RV32I decoder / control unit.
// Replaces control_logic.v.  FIXES:
//   * fully COMBINATIONAL (`always @(*)`) with ALL outputs defaulted at the top
//     of the block -> no inferred latches / stale control (the original drove
//     control in a posedge block with no defaults).
//   * proper funct7[5] handling for SUB vs ADD and SRA vs SRL.
// alu_ctrl encoding matches alu.v.
// -----------------------------------------------------------------------------
module control(
    input      [31:0] ins,
    output reg        reg_write,
    output reg        alu_src,     // 1: operand B = imm, 0: = rs2
    output reg        alu_a_pc,    // 1: operand A = pc  (AUIPC)
    output reg        mem_read,
    output reg        mem_write,
    output reg [1:0]  wb_sel,      // 00 alu | 01 mem | 10 pc+4 | 11 imm(LUI)
    output reg        branch,
    output reg        jump,        // JAL
    output reg        jalr,
    output reg [3:0]  alu_ctrl
);
    wire [6:0] op     = ins[6:0];
    wire [2:0] funct3 = ins[14:12];
    wire       f7b5   = ins[30];   // funct7[5]

    reg [3:0] rtype_ctrl, itype_ctrl;
    always @(*) begin
        case (funct3)
            3'b000: rtype_ctrl = f7b5 ? 4'd1 : 4'd0;  // SUB / ADD
            3'b001: rtype_ctrl = 4'd2;                // SLL
            3'b010: rtype_ctrl = 4'd3;                // SLT
            3'b011: rtype_ctrl = 4'd4;                // SLTU
            3'b100: rtype_ctrl = 4'd5;                // XOR
            3'b101: rtype_ctrl = f7b5 ? 4'd7 : 4'd6;  // SRA / SRL
            3'b110: rtype_ctrl = 4'd8;                // OR
            3'b111: rtype_ctrl = 4'd9;                // AND
        endcase
        case (funct3)
            3'b000: itype_ctrl = 4'd0;                // ADDI
            3'b001: itype_ctrl = 4'd2;                // SLLI
            3'b010: itype_ctrl = 4'd3;                // SLTI
            3'b011: itype_ctrl = 4'd4;                // SLTIU
            3'b100: itype_ctrl = 4'd5;                // XORI
            3'b101: itype_ctrl = f7b5 ? 4'd7 : 4'd6;  // SRAI / SRLI
            3'b110: itype_ctrl = 4'd8;                // ORI
            3'b111: itype_ctrl = 4'd9;                // ANDI
        endcase
    end

    always @(*) begin
        // defaults -- prevents latches
        reg_write = 1'b0; alu_src = 1'b0; alu_a_pc = 1'b0;
        mem_read  = 1'b0; mem_write = 1'b0; wb_sel = 2'b00;
        branch    = 1'b0; jump = 1'b0; jalr = 1'b0; alu_ctrl = 4'd0;
        case (op)
            7'b0110011: begin                          // R-type
                reg_write = 1'b1; alu_ctrl = rtype_ctrl;
            end
            7'b0010011: begin                          // I-type ALU
                reg_write = 1'b1; alu_src = 1'b1; alu_ctrl = itype_ctrl;
            end
            7'b0000011: begin                          // load
                reg_write = 1'b1; alu_src = 1'b1; mem_read = 1'b1;
                wb_sel = 2'b01; alu_ctrl = 4'd0;
            end
            7'b0100011: begin                          // store
                alu_src = 1'b1; mem_write = 1'b1; alu_ctrl = 4'd0;
            end
            7'b1100011: begin                          // branch
                branch = 1'b1; alu_ctrl = 4'd1;
            end
            7'b0110111: begin                          // LUI
                reg_write = 1'b1; wb_sel = 2'b11;
            end
            7'b0010111: begin                          // AUIPC
                reg_write = 1'b1; alu_src = 1'b1; alu_a_pc = 1'b1; alu_ctrl = 4'd0;
            end
            7'b1101111: begin                          // JAL
                reg_write = 1'b1; jump = 1'b1; wb_sel = 2'b10;
            end
            7'b1100111: begin                          // JALR
                reg_write = 1'b1; jalr = 1'b1; alu_src = 1'b1;
                wb_sel = 2'b10; alu_ctrl = 4'd0;
            end
            default: ;
        endcase
    end
endmodule
