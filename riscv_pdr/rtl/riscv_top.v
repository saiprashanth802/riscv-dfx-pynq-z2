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
    input      [9:0]  dbg_addr,     // data-memory debug read: word index (also the word address of a PS write)
    output     [31:0] dbg_data,     // ... contents of that word
    // ---- PS-side loader + run status (board only).  Tie imem_we/dmem_we low and ignore dbg_stat elsewhere. ----
    input             imem_we,      // level from the GPIO; one write per rising edge, and only while `reset` is high
    input             dmem_we,
    input      [31:0] ps_wdata,     // data for either write
    output     [31:0] dbg_stat      // {halted, cycles[30:0]}: clocks since reset release, frozen at the halt loop
);
    // ---- fetch ----
    wire [31:0] pc_cur, next_pc, ins;
    wire [31:0] pc_plus4 = pc_cur + 32'd4;

    // PS loader: the core sits in reset (pc = 0) while a program and its data are written, then runs from pc 0.
    reg [1:0] we_q;
    always @(posedge clk) we_q <= {imem_we, dmem_we};
    wire imem_wr = reset & imem_we & ~we_q[1];
    wire dmem_wr = reset & dmem_we & ~we_q[0];

    pc   u_pc   (.clk(clk), .reset(reset), .next_pc(next_pc), .pc(pc_cur));
    imem u_imem (.clk(clk), .we(imem_wr), .waddr(dbg_addr), .wdata(ps_wdata), .addr(pc_cur), .ins(ins));

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
    // ~reset: pc is held at 0 during reset, so instruction 0 would otherwise re-execute every cycle -- a `sw` there
    // would write dmem while the PS is loading it.
    wire        ram_we = mem_write & ~is_cfu & ~reset;
    wire        cfu_we = mem_write &  is_cfu;
    wire [31:0] ram_rdata, cfu_rdata;

    dmem u_dmem (
        .clk(clk), .we(ram_we), .addr(alu_y), .wdata(rd2), .rdata(ram_rdata),
        .ps_we(dmem_wr), .ps_addr(dbg_addr), .ps_wdata(ps_wdata),
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

    // ---- run status: cycles counts every clock from reset release up to and including the first execution of the
    // halt instruction (a jump/branch to itself); the same convention as `cycles` in demo/sim.js.
    reg        halted;
    reg [30:0] cycles;
    always @(posedge clk)
        if (reset) begin halted <= 1'b0; cycles <= 31'd0; end
        else if (!halted) begin
            cycles <= cycles + 31'd1;
            if (next_pc == pc_cur) halted <= 1'b1;
        end
    assign dbg_stat = {halted, cycles};

    assign dbg_pc = pc_cur;
    assign dbg_wb = wb_data;
endmodule
