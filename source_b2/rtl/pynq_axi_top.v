`timescale 1ns / 1ps
// -----------------------------------------------------------------------------
// pynq_axi_top.v -- PYNQ-Z2 wrapper for a REMOTE board: PS7 + AXI GPIO readout.
//
// pynq_top.v shows results on the LEDs, which nobody can see over SSH.  This
// wrapper instead exposes the same dmem debug port to Python through one
// dual-channel AXI GPIO inside the `ps` block design (vivado/ps_bd.tcl):
//
//   ctl[9:0]   dbg_addr  -- word index into dmem            (GPIO ch1, PS -> PL)
//   ctl[10]    sw_reset  -- hold the core in reset          (GPIO ch1, PS -> PL)
//   dbg_data   dmem[dbg_addr]                               (GPIO ch2, PL -> PS)
//
// The core clock is FCLK_CLK0 straight from the PS (50 MHz; the frequency lives
// in vivado/ps_bd.tcl, nothing here depends on it).  No divider, no
// create_generated_clock, and no board pins at all: the DDR/FIXED_IO ports
// below are the PS's own and the tools place them automatically.
//
// Same demo as before, read instead of seen: write ctl=4, read dbg_data.
// Variant A (multiplier) returns 42; variant B (bitwise) returns 2.  Swap the
// partition with a partial bitstream and the number changes.
//
// Instance name u_core is load-bearing: the DFX flow addresses the
// reconfigurable partition as u_core/u_cfu/u_cfu.
// -----------------------------------------------------------------------------
module pynq_axi_top(
    inout [14:0] DDR_addr,
    inout [2:0]  DDR_ba,
    inout        DDR_cas_n,
    inout        DDR_ck_n,
    inout        DDR_ck_p,
    inout        DDR_cke,
    inout        DDR_cs_n,
    inout [3:0]  DDR_dm,
    inout [31:0] DDR_dq,
    inout [3:0]  DDR_dqs_n,
    inout [3:0]  DDR_dqs_p,
    inout        DDR_odt,
    inout        DDR_ras_n,
    inout        DDR_reset_n,
    inout        DDR_we_n,
    inout        FIXED_IO_ddr_vrn,
    inout        FIXED_IO_ddr_vrp,
    inout [53:0] FIXED_IO_mio,
    inout        FIXED_IO_ps_clk,
    inout        FIXED_IO_ps_porb,
    inout        FIXED_IO_ps_srstb
);
    wire        clk;
    wire        aresetn;
    wire [10:0] ctl;
    wire [31:0] dbg_data;

    ps_wrapper u_ps (
        .DDR_addr(DDR_addr), .DDR_ba(DDR_ba), .DDR_cas_n(DDR_cas_n),
        .DDR_ck_n(DDR_ck_n), .DDR_ck_p(DDR_ck_p), .DDR_cke(DDR_cke),
        .DDR_cs_n(DDR_cs_n), .DDR_dm(DDR_dm), .DDR_dq(DDR_dq),
        .DDR_dqs_n(DDR_dqs_n), .DDR_dqs_p(DDR_dqs_p), .DDR_odt(DDR_odt),
        .DDR_ras_n(DDR_ras_n), .DDR_reset_n(DDR_reset_n), .DDR_we_n(DDR_we_n),
        .FIXED_IO_ddr_vrn(FIXED_IO_ddr_vrn), .FIXED_IO_ddr_vrp(FIXED_IO_ddr_vrp),
        .FIXED_IO_mio(FIXED_IO_mio), .FIXED_IO_ps_clk(FIXED_IO_ps_clk),
        .FIXED_IO_ps_porb(FIXED_IO_ps_porb), .FIXED_IO_ps_srstb(FIXED_IO_ps_srstb),
        .clk(clk), .aresetn(aresetn), .ctl(ctl), .dbg_data(dbg_data)
    );

    // ---- reset: power-on pulse | software bit | AXI side not yet out of reset ----
    reg [3:0] por = 4'hF;           // FPGA config leaves this at F, then it drains
    always @(posedge clk) if (por != 4'h0) por <= por - 1'b1;

    wire reset = (por != 4'h0) | ctl[10] | ~aresetn;

    // ---- the core ----
    wire [31:0] dbg_pc, dbg_wb;     // unused here; ILA hooks if ever needed
    riscv_top u_core (
        .clk(clk), .reset(reset),
        .dbg_pc(dbg_pc), .dbg_wb(dbg_wb),
        .dbg_addr(ctl[9:0]), .dbg_data(dbg_data)
    );
endmodule
