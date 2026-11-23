`timescale 1ns / 1ps
// -----------------------------------------------------------------------------
// riscv_top.v -- single-cycle RV32I core + memory-mapped custom function unit.
// Complete rewrite of the original risc_v.v, which would not elaborate
// (unnamed instances, wrong module names, mismatched ports, undeclared nets,
// unconnected reset).  Every instance is named, every net declared.
//
// Data-memory address decode: any effective address with the top nibble = 0xF
// is routed to the CFU (cfu_mmio) instead of RAM.  So the CPU drives the
// reconfigurable accelerator with ordinary SW/LW -- no custom instructions.
// -----------------------------------------------------------------------------
module riscv_top(
    input             clk,
    input             reset,
    output     [31:0] dbg_pc,       // for LEDs / AXI-GPIO / ILA
    output     [31:0] dbg_wb,       // last write-back value
    input      [9:0]  dbg_addr,     // data-memory debug read: word index
    output     [31:0] dbg_data      // ... contents of that word
);
    // ---- fetch ----
    wire [31:0] pc_cur, next_pc, ins;
    wire [31:0] pc_plus4 = pc_cur + 32'd4;

    pc   u_pc   (.clk(clk), .reset(reset), .next_pc(next_pc), .pc(pc_cur));
    imem u_imem (.addr(pc_cur), .ins(ins));

    // ---- decode ----
    wire [4:0] rs1 = ins[19:15];
    wire [4:0] rs2 = ins[24:20];
    wire [4:0] rd  = ins[11:7];

    wire        reg_write, alu_src, alu_a_pc, mem_read, mem_write, branch, jump, jalr;
    wire [1:0]  wb_sel;
    wire [3:0]  alu_ctrl;

    control u_ctrl (
        .ins(ins), .reg_write(reg_write), .alu_src(alu_src), .alu_a_pc(alu_a_pc),
        .mem_read(mem_read), .mem_write(mem_write), .wb_sel(wb_sel),
        .branch(branch), .jump(jump), .jalr(jalr), .alu_ctrl(alu_ctrl)
    );

    wire [31:0] rd1, rd2, imm, wb_data;
    regfile u_rf (
        .clk(clk), .we(reg_write), .rs1(rs1), .rs2(rs2), .rd(rd),
        .wd(wb_data), .rd1(rd1), .rd2(rd2)
    );
    imm_gen u_imm (.ins(ins), .imm(imm));

    // ---- execute ----
    wire [31:0] alu_a = alu_a_pc ? pc_cur : rd1;
    wire [31:0] alu_b = alu_src  ? imm    : rd2;
    wire [31:0] alu_y;
    alu u_alu (.a(alu_a), .b(alu_b), .ctrl(alu_ctrl), .y(alu_y));

    // ---- memory / MMIO ----
    wire        is_cfu = (alu_y[31:28] == 4'hF);
    wire        ram_we = mem_write & ~is_cfu;
    wire        cfu_we = mem_write &  is_cfu;
    wire [31:0] ram_rdata, cfu_rdata;

    dmem u_dmem (
        .clk(clk), .we(ram_we), .addr(alu_y), .wdata(rd2), .rdata(ram_rdata),
        .dbg_addr(dbg_addr), .dbg_data(dbg_data)
    );
    cfu_mmio u_cfu (
        .clk(clk), .rst(reset), .we(cfu_we), .addr(alu_y[3:0]),
        .wdata(rd2), .rdata(cfu_rdata)
    );
    wire [31:0] mem_rdata = is_cfu ? cfu_rdata : ram_rdata;

    // ---- write-back mux ----
    assign wb_data = (wb_sel == 2'b00) ? alu_y     :
                     (wb_sel == 2'b01) ? mem_rdata :
                     (wb_sel == 2'b10) ? pc_plus4  :
                                         imm;       // 2'b11 = LUI

    // ---- next PC ----
    wire        taken;
    branch_unit u_bu (.funct3(ins[14:12]), .a(rd1), .b(rd2), .taken(taken));
    wire [31:0] branch_target = pc_cur + imm;
    wire [31:0] jal_target    = pc_cur + imm;
    wire [31:0] jalr_target   = (rd1 + imm) & ~32'b1;
    assign next_pc = jalr             ? jalr_target   :
                     jump             ? jal_target    :
                     (branch & taken) ? branch_target :
                                        pc_plus4;

    assign dbg_pc = pc_cur;
    assign dbg_wb = wb_data;
endmodule
