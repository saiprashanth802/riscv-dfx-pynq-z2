`timescale 1ns / 1ps
// -----------------------------------------------------------------------------
// tb_riscv.v -- self-checking testbench for the single-cycle core + CFU.
//
// The SAME program.hex runs against either module in the reconfigurable slot;
// only the expected values differ.  Select the variant at compile time:
//
//   variant A (default)  xvlog ... cfu_mul.v ...
//   variant B            xvlog -d CFU_BITWISE ... cfu_bitwise.v ...
//
// Compiling cfu_bitwise.v without -d CFU_BITWISE (or vice versa) is a real
// failure, not a false alarm: it means the slot contents and the golden model
// disagree.
// -----------------------------------------------------------------------------
module tb_riscv;
    reg clk = 1'b0;
    reg reset = 1'b1;
    wire [31:0] dbg_pc, dbg_wb, dbg_data;
    reg  [9:0]  dbg_addr = 10'd4;

    riscv_top dut (.clk(clk), .reset(reset), .dbg_pc(dbg_pc), .dbg_wb(dbg_wb),
                   .dbg_addr(dbg_addr), .dbg_data(dbg_data));

    always #5 clk = ~clk;          // 100 MHz sim clock

    integer errors = 0;

    task check;
        input [127:0] name;
        input [31:0]  got;
        input [31:0]  exp;
        begin
            if (got !== exp) begin
                $display("FAIL  %0s = %0d (0x%08x), expected %0d (0x%08x)",
                         name, got, got, exp, exp);
                errors = errors + 1;
            end else begin
                $display("ok    %0s = %0d (0x%08x)", name, got, got);
            end
        end
    endtask

    initial begin
`ifdef CFU_BITWISE
        $display("CFU variant B -- cfu_bitwise (popcount / AND / XOR)\n");
`else
        $display("CFU variant A -- cfu_mul (32x32 multiplier)\n");
`endif
        #12 reset = 1'b0;          // release reset after 1 full cycle
        #600;                      // ample time for 41 single-cycle instructions

        // ---- core datapath: identical for both variants ----
        check("mem[0]  x1+x2",   dut.u_dmem.mem[0], 32'd13);
        check("mem[1]  x2-x1",   dut.u_dmem.mem[1], 32'd1);
        check("x3",              dut.u_rf.regs[3],  32'd13);
        check("x4",              dut.u_rf.regs[4],  32'd1);

        // ---- CFU slot: phase 1, op_a=6 op_b=7 ----
`ifdef CFU_BITWISE
        check("p1 fn0 popcnt",   dut.u_dmem.mem[4],  32'd2);          // popcount(6)
        check("p1 fn1 and",      dut.u_dmem.mem[5],  32'd6);          // 6 & 7
        check("p1 fn2 xor",      dut.u_dmem.mem[6],  32'd1);          // 6 ^ 7
        check("p1 fn3 passthru", dut.u_dmem.mem[7],  32'd6);          // op_a
`else
        check("p1 fn0 mul lo",   dut.u_dmem.mem[4],  32'd42);         // 6*7
        check("p1 fn1 mul hi",   dut.u_dmem.mem[5],  32'd0);
        check("p1 fn2 dflt lo",  dut.u_dmem.mem[6],  32'd42);
        check("p1 fn3 dflt lo",  dut.u_dmem.mem[7],  32'd42);
`endif

        // ---- CFU slot: phase 2, op_a=op_b=0x00010000 ----
`ifdef CFU_BITWISE
        check("p2 fn0 popcnt",   dut.u_dmem.mem[8],  32'd1);          // popcount(1<<16)
        check("p2 fn1 and",      dut.u_dmem.mem[9],  32'h00010000);
        check("p2 fn2 xor",      dut.u_dmem.mem[10], 32'd0);          // x ^ x
`else
        check("p2 fn0 mul lo",   dut.u_dmem.mem[8],  32'h00000000);   // 1<<32, low word
        check("p2 fn1 mul hi",   dut.u_dmem.mem[9],  32'h00000001);   // 1<<32, high word
        check("p2 fn2 dflt lo",  dut.u_dmem.mem[10], 32'h00000000);
`endif

        // ---- board debug read port must mirror the CPU's own view ----
        dbg_addr = 10'd4; #1;
        check("dbgport mem[4]", dbg_data, dut.u_dmem.mem[4]);
        dbg_addr = 10'd8; #1;
        check("dbgport mem[8]", dbg_data, dut.u_dmem.mem[8]);

        // ---- program must have reached the halt loop (jal x0,0 at word 40) ----
        check("halted at pc",   dbg_pc, 32'd160);

        if (errors == 0) $display("\n==== ALL TESTS PASSED ====");
        else             $display("\n==== %0d FAILURE(S) ====", errors);
        $finish;
    end

    // safety timeout
    initial begin
        #10000;
        $display("TIMEOUT");
        $finish;
    end
endmodule
