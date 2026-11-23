`timescale 1ns / 1ps
// -----------------------------------------------------------------------------
// cfu_stub.v -- BLACK-BOX stub of the frozen `cfu` interface, for the DFX flow
// only.  Never compiled into simulation and never into the flat build.
//
// The static design has to be synthesised with the reconfigurable partition
// EMPTY.  Vivado does not black-box a missing module on its own -- omitting
// cfu_mul.v/cfu_bitwise.v just produces "ERROR: [Synth 8-439] module 'cfu' not
// found".  This stub, with an empty body and the (* black_box *) attribute, is
// what makes synth_design leave the RP hollow for read_checkpoint -cell to fill.
//
// Port list MUST stay identical to cfu_mul.v / cfu_bitwise.v.
// -----------------------------------------------------------------------------
(* black_box *)
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
endmodule
