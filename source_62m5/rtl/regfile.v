`timescale 1ns / 1ps
// -----------------------------------------------------------------------------
// regfile.v  -- 32x32 RV32I register file, 2 read ports + 1 write port.
// Replaces register_array.v.  FIXES vs the original:
//   * x0 is hardwired to 0 (never written, always reads 0).  The original
//     instantiated x0 as a normal writable register -> illegal per RV32I.
//   * clean behavioural description (the original's 32 explicit `register`
//     instances + 32:1 muxes + 1:32 demux synthesise, but were verbose and
//     contained `output wire reg` which is not legal Verilog).
// -----------------------------------------------------------------------------
module regfile(
    input             clk,
    input             we,
    input      [4:0]  rs1,
    input      [4:0]  rs2,
    input      [4:0]  rd,
    input      [31:0] wd,
    output     [31:0] rd1,
    output     [31:0] rd2
);
    reg [31:0] regs [0:31];
    integer i;
    initial for (i = 0; i < 32; i = i + 1) regs[i] = 32'b0;   // sim determinism

    // x0 must never be written
    always @(posedge clk)
        if (we && rd != 5'd0)
            regs[rd] <= wd;

    // x0 must always read as zero
    assign rd1 = (rs1 == 5'd0) ? 32'b0 : regs[rs1];
    assign rd2 = (rs2 == 5'd0) ? 32'b0 : regs[rs2];
endmodule
