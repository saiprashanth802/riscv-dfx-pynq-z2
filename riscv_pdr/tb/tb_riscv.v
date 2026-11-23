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
    reg         imem_we = 1'b0, dmem_we = 1'b0;
    reg  [31:0] ps_wdata = 32'b0;
    wire [31:0] dbg_stat;

    riscv_top dut (.clk(clk), .reset(reset), .dbg_pc(dbg_pc), .dbg_wb(dbg_wb),
                   .dbg_addr(dbg_addr), .dbg_data(dbg_data),
                   .imem_we(imem_we), .dmem_we(dmem_we), .ps_wdata(ps_wdata), .dbg_stat(dbg_stat));

    always #5 clk = ~clk;          // 100 MHz sim clock

    integer errors = 0;

    task check;
        input [255:0] name;
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

    // PS loader, as the board's Python does it: address and data settle first, then the strobe is raised for one clock.
    task ps_write;
        input        to_imem;
        input [9:0]  a;
        input [31:0] d;
        begin
            @(negedge clk); dbg_addr = a; ps_wdata = d;
            @(negedge clk); if (to_imem) imem_we = 1'b1; else dmem_we = 1'b1;
            @(negedge clk); imem_we = 1'b0; dmem_we = 1'b0;
        end
    endtask

    task run_to_halt;               // release reset and wait for stat[31]
        integer n;
        begin
            @(negedge clk); reset = 1'b0;
            n = 0;
            while (!dbg_stat[31] && n < 500) begin @(negedge clk); n = n + 1; end
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
        check("stat: halted + 41 cycles", dbg_stat, 32'h80000029);   // demo/sim.js counts the same 41

        // ================= PS loader: put a different program on the core without touching the bitstream =========
        // 1. a strobe while the core is RUNNING must be ignored (imem word 0 is addi x1,x0,6 = 0x00600093)
        @(negedge clk); dbg_addr = 10'd0; ps_wdata = 32'hDEADBEEF;
        @(negedge clk); imem_we = 1'b1; dmem_we = 1'b1;
        @(negedge clk); imem_we = 1'b0; dmem_we = 1'b0;
        check("write ignored while running (imem)", dut.u_imem.mem[0], 32'h00600093);
        check("write ignored while running (dmem)", dut.u_dmem.mem[0], 32'd13);

        // 2. in reset: a strobe held high for 4 clocks writes once (edge-detect), the later wdata does not land
        @(negedge clk); reset = 1'b1;
        @(negedge clk); dbg_addr = 10'd700; ps_wdata = 32'hA1A1A1A1;
        @(negedge clk); dmem_we = 1'b1;
        @(negedge clk); ps_wdata = 32'hB2B2B2B2;          // address unchanged, data changed, strobe still high
        @(negedge clk); @(negedge clk); dmem_we = 1'b0;
        check("held strobe writes once", dut.u_dmem.mem[700], 32'hA1A1A1A1);

        // 3. a program whose FIRST instruction is a store must not write dmem while held in reset:
        //    sw x0,12(x0) = 0x00002623 ; then halt.  dmem[3] is preloaded; the core sits in reset for ~10 clocks.
        ps_write(1'b0, 10'd3, 32'hAAAA5555);
        ps_write(1'b1, 10'd0, 32'h00002623);
        ps_write(1'b1, 10'd1, 32'h0000006f);
        repeat (10) @(negedge clk);
        check("no core write during reset", dut.u_dmem.mem[3], 32'hAAAA5555);
        run_to_halt;
        check("...and the store runs after release", dut.u_dmem.mem[3], 32'd0);
        check("stat: 2 cycles (sw, halt)", dbg_stat, 32'h80000002);

        // 4. sum 1..10 loop written through the port (assembled by sw/rvasm.py from sw/asm/sum10.s)
        @(negedge clk); reset = 1'b1;
        ps_write(1'b1, 10'd0, 32'h00000093); ps_write(1'b1, 10'd1, 32'h00100113);
        ps_write(1'b1, 10'd2, 32'h00b00193); ps_write(1'b1, 10'd3, 32'h002080b3);
        ps_write(1'b1, 10'd4, 32'h00110113); ps_write(1'b1, 10'd5, 32'hfe314ce3);
        ps_write(1'b1, 10'd6, 32'h00102023); ps_write(1'b1, 10'd7, 32'h0000006f);
        run_to_halt;
        check("loaded sum10: mem[0] = 55",    dut.u_dmem.mem[0], 32'd55);
        check("loaded sum10: 35 cycles",      dbg_stat,          32'h80000023);

        // 5. data in AND the CFU: lw a, lw b, CFU fn2 (bitwise: a^b, multiplier: a*b mod 2^32), sw result
        @(negedge clk); reset = 1'b1;
        ps_write(1'b0, 10'd100, 32'h12345678); ps_write(1'b0, 10'd101, 32'h0F0F0F0F);
        ps_write(1'b1, 10'd0, 32'h19002083); ps_write(1'b1, 10'd1, 32'h19402103);
        ps_write(1'b1, 10'd2, 32'hf00002b7); ps_write(1'b1, 10'd3, 32'h0012a023);
        ps_write(1'b1, 10'd4, 32'h0022a223); ps_write(1'b1, 10'd5, 32'h00200413);
        ps_write(1'b1, 10'd6, 32'h0082a423); ps_write(1'b1, 10'd7, 32'h00c2a483);
        ps_write(1'b1, 10'd8, 32'h18902c23); ps_write(1'b1, 10'd9, 32'h0000006f);
        run_to_halt;
`ifdef CFU_BITWISE
        check("loaded program, CFU fn2 = xor", dut.u_dmem.mem[102], 32'h1d3b5977);
`else
        check("loaded program, CFU fn2 = mul", dut.u_dmem.mem[102], 32'h3b2a1908);
`endif
        check("stat: 10 cycles",              dbg_stat,          32'h8000000a);

        // 6. dmem survives a core reset (the rick decoder keeps its framebuffer there)
        @(negedge clk); reset = 1'b1; repeat (3) @(negedge clk);
        check("dmem kept across reset", dut.u_dmem.mem[100], 32'h12345678);
        check("stat cleared by reset",   dbg_stat, 32'd0);

        if (errors == 0) $display("\n==== ALL TESTS PASSED ====");
        else             $display("\n==== %0d FAILURE(S) ====", errors);
        $finish;
    end

    // safety timeout
    initial begin
        #40000;
        $display("TIMEOUT");
        $finish;
    end
endmodule
