`timescale 1ns / 1ps
// -----------------------------------------------------------------------------
// cfu_mmio.v -- STATIC-REGION wrapper for the reconfigurable custom function
// unit.  This module is NEVER reconfigured; only the `cfu` instance inside it
// is the reconfigurable partition (RP).
//
// Memory map (base 0xF000_0000, reached by the CPU with plain SW/LW):
//   +0x0  W  op_a
//   +0x4  W  op_b
//   +0x8  W  fn[3:0]  (also pulses `start` for multi-cycle variants)
//   +0xC  R  result
//
// In the DFX flow you would place a DFX Decoupler between this wrapper and the
// `cfu` instance so the CPU never sees garbage on `result` during a partial
// reconfiguration.  Kept out here for the week-1 static build.
// -----------------------------------------------------------------------------
module cfu_mmio(
    input             clk,
    input             rst,
    input             we,
    input      [3:0]  addr,     // low offset within the CFU window
    input      [31:0] wdata,
    output     [31:0] rdata
);
    reg [31:0] op_a, op_b;
    reg [3:0]  fn;
    reg        start;

    always @(posedge clk) begin
        start <= 1'b0;                    // start is a 1-cycle pulse
        if (rst) begin
            op_a <= 32'b0; op_b <= 32'b0; fn <= 4'b0;
        end else if (we) begin
            case (addr)
                4'h0: op_a <= wdata;
                4'h4: op_b <= wdata;
                4'h8: begin fn <= wdata[3:0]; start <= 1'b1; end
                default: ;
            endcase
        end
    end

    wire [31:0] result;
    wire        done;

    // ---- reconfigurable partition instance (frozen interface) ----
    cfu u_cfu (
        .clk    (clk),
        .rst    (rst),
        .start  (start),
        .op_a   (op_a),
        .op_b   (op_b),
        .fn     (fn),
        .result (result),
        .done   (done)
    );

    assign rdata = result;                // read at +0xC returns result
endmodule
