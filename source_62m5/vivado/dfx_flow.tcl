# -----------------------------------------------------------------------------
# dfx_flow.tcl -- Dynamic Function eXchange flow for the CFU slot.
#   vivado -mode batch -source dfx_flow.tcl
#
# Reconfigurable partition : u_core/u_cfu/u_cfu   (module `cfu`)
# Static top              : rtl/pynq_axi_top.v (PS7 + AXI GPIO, remote board)
# Reconfigurable modules   : cfu_mul.v (A) , cfu_bitwise.v (B)
#
# Each stage prints "STAGE <name> OK" or "STAGE <name> FAILED: <msg>" and the
# script keeps going where it safely can, so one run tells us exactly how far
# the free licence gets.
# -----------------------------------------------------------------------------
set here [file normalize [file dirname [info script]]]
set rtl  $here/../rtl
set out  $here/dfx
file mkdir $out
file copy -force $here/program.hex $out/program.hex
cd $out

set RP    u_core/u_cfu/u_cfu
set PART  xc7z020clg400-1
set fails 0

proc stage {name body} {
    global fails
    if {[catch {uplevel 1 $body} msg]} {
        puts "STAGE $name FAILED: $msg"
        incr fails
        return 0
    }
    puts "STAGE $name OK"
    return 1
}

# --- 1. static design, RP left as a black box -------------------------------
# Top is pynq_axi_top (PS7 + AXI GPIO readout, no board pins) -- see rtl/ and
# ps_bd.tcl.  The block design needs a project, so this one stage runs inside a
# throwaway project and closes it again: open_checkpoint in the later stages
# refuses to run while a project is open.
stage synth_static {
  if {[file exists static_synth.dcp] && [file exists ps.hwh]} { puts "  (cached)" } else {
    create_project -force dfx_proj $out/proj -part $PART
    source $here/ps_bd.tcl
    foreach f {regfile.v imm_gen.v alu.v control.v branch_unit.v pc.v imem.v \
               dmem.v cfu_mmio.v riscv_top.v pynq_axi_top.v} {
        add_files -norecurse $rtl/$f
    }
    add_files -norecurse $here/cfu_stub.v
    set_property top pynq_axi_top [current_fileset]
    synth_design -top pynq_axi_top -part $PART
    write_checkpoint -force static_synth.dcp
    file copy -force $env(PS_HWH) ps.hwh
    puts "  RP cell present: [get_cells $RP]"
    close_project
  }
}

# --- 2. each reconfigurable module, out of context --------------------------
foreach {tag src} {mul cfu_mul.v bitwise cfu_bitwise.v} {
    stage synth_rm_$tag "
      if {\[file exists rm_${tag}_synth.dcp\]} { puts \"  (cached)\" } else {
        read_verilog $rtl/$src
        synth_design -top cfu -part $PART -mode out_of_context
        write_checkpoint -force rm_${tag}_synth.dcp
        close_design
      }
    "
}

# --- 3. configuration 1: static + variant A ---------------------------------
stage config1_assemble {
    open_checkpoint static_synth.dcp
    read_checkpoint -cell $RP rm_mul_synth.dcp
    set_property HD.RECONFIGURABLE true [get_cells $RP]

    create_pblock pblock_cfu
    add_cells_to_pblock pblock_cfu [get_cells $RP]

    # Clock region X1Y1, ONE DSP column (3) plus the 8 slice columns beside it
    # -- the "narrow" geometry from dfx_pblock_sweep.tcl: 111 KB partial instead
    # of 221 KB for the two-column version, and 20 DSPs is still 5x what the
    # multiplier needs.  Full clock-region height on purpose: on 7 series a
    # reconfigurable frame IS a clock-region-tall column, so a shorter pblock
    # buys nothing in partial-bitstream size (measured).
    #
    # TWO TRAPS, both of which cost a run:
    #  1. Range syntax needs FULL site names at both ends.  "SLICE_X50Y50:X67Y99"
    #     is rejected with "pblock resize has invalid range".
    #  2. SLICE site-X numbering does NOT track tile columns.  The DSP columns
    #     live in tiles X59 (DSP_R) and X64 (DSP_L); the CLB tiles flanking them
    #     are X58/X60 and X63/X65, which carry SLICE sites X92..X103.  A pblock
    #     of SLICE_X50..X67 is nowhere near the DSPs, and SNAPPING_MODE then
    #     silently DROPS the DSP range and fails with DRC HDPR-50 ("Programmable
    #     Unit missing range") -- a message that reads like the DSP range was
    #     wrong when in fact the SLICE range was.
    resize_pblock pblock_cfu -add {SLICE_X92Y50:SLICE_X99Y99}
    resize_pblock pblock_cfu -add {DSP48_X3Y20:DSP48_X3Y39}
    set_property SNAPPING_MODE ON [get_pblocks pblock_cfu]
    report_property [get_pblocks pblock_cfu] -file pblock_props.rpt
}

stage config1_implement {
    opt_design
    place_design
    route_design
    write_checkpoint -force config1_routed.dcp
    report_utilization -pblocks [get_pblocks pblock_cfu] -file util_pblock_c1.rpt
    report_timing_summary -file timing_c1.rpt
    puts "  C1 WNS = [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]"
    close_design
}

# --- 4. lock the static region ----------------------------------------------
stage lock_static {
    # Start from the ROUTED config1, not from whatever happens to be open --
    # otherwise a failed implement stage silently locks an unplaced design and
    # every later stage "succeeds" against garbage.
    open_checkpoint config1_routed.dcp
    update_design -cell $RP -black_box
    lock_design -level routing
    write_checkpoint -force static_locked.dcp
    close_design
}

# --- 5. configuration 2: locked static + variant B --------------------------
stage config2_implement {
    open_checkpoint static_locked.dcp
    read_checkpoint -cell $RP rm_bitwise_synth.dcp
    opt_design
    place_design
    route_design
    write_checkpoint -force config2_routed.dcp
    report_utilization -pblocks [get_pblocks pblock_cfu] -file util_pblock_c2.rpt
    puts "  C2 WNS = [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]"
    close_design
}

# --- 6. verify the two configurations agree on the static region ------------
stage pr_verify {
    pr_verify -full_check -file pr_verify.rpt config1_routed.dcp config2_routed.dcp
}

# --- 7. bitstreams: full + partial for each configuration -------------------
stage bitstream_c1 {
    open_checkpoint config1_routed.dcp
    write_bitstream -force config1
    file copy -force ps.hwh config1.hwh     ;# PYNQ Overlay() wants <name>.hwh beside <name>.bit
    close_design
}
stage bitstream_c2 {
    open_checkpoint config2_routed.dcp
    write_bitstream -force config2
    file copy -force ps.hwh config2.hwh
    close_design
}

foreach f [lsort [glob -nocomplain *.bit]] {
    puts "BITSTREAM [format %10d [file size $f]] B  $f"
}
puts "DFX_FLOW_DONE failures=$fails"
