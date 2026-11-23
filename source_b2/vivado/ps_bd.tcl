# -----------------------------------------------------------------------------
# ps_bd.tcl -- block design "ps": Zynq PS7 + one dual-channel AXI GPIO.
# Sourced from dfx_flow.tcl with a project already open (BDs need a project).
#
# Why it exists: the board is remote, so the LED/button readout in pynq_top.v
# is useless.  This gives the core a software-visible debug port instead:
#   ctl[9:0]  = dbg_addr (word index into dmem)      GPIO ch1, output
#   ctl[10]   = software reset for the core           GPIO ch1, output
#   dbg_data  = dmem[dbg_addr]                        GPIO ch2, input
# and FCLK_CLK0 at 50 MHz is the core clock: the 31.25 MHz build showed an
# 18.1 ns worst path (WNS +13.9), so 20 ns closes; 62.5 MHz (16 ns) does not.
# No board preset: the FSBL configures the PS, the bitstream does not, so
# DDR/MIO settings here are irrelevant.
#
# Leaves: ps_wrapper (added to the project) and $env(PS_HWH) -> path of ps.hwh.
# -----------------------------------------------------------------------------
create_bd_design ps

create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 ps7
# TRAP: without a board preset the PS7 IP is free to "solve" the requested
# FCLK0 by changing the IO PLL multiplier (it picked x48 = 1600 MHz for 50 MHz
# and kept the /8/4 divisors).  But PLLs are programmed by the FSBL at boot, not
# by the bitstream, and PYNQ only writes the FCLK divisors from the .hwh -- so on
# the board that was 1000/32 = 31.25 MHz with a design timed at 50.  Override
# mode pins the PLLs to what the PYNQ-Z2 FSBL actually sets (33.333 MHz crystal:
# ARM x40 = 1333, DDR x32 = 1067, IO x30 = 1000) and the divisors to 5*4.
set_property -dict [list \
    CONFIG.PCW_USE_M_AXI_GP0 {1} \
    CONFIG.PCW_EN_CLK0_PORT {1} \
    CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {50} \
    CONFIG.PCW_OVERRIDE_BASIC_CLOCK {1} \
    CONFIG.PCW_ARMPLL_CTRL_FBDIV {40} \
    CONFIG.PCW_DDRPLL_CTRL_FBDIV {32} \
    CONFIG.PCW_IOPLL_CTRL_FBDIV {30} \
    CONFIG.PCW_FCLK0_PERIPHERAL_DIVISOR0 {5} \
    CONFIG.PCW_FCLK0_PERIPHERAL_DIVISOR1 {4} \
] [get_bd_cells ps7]
apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 \
    -config {make_external "FIXED_IO, DDR" apply_board_preset "0" Master "Disable" Slave "Disable"} \
    [get_bd_cells ps7]

create_bd_cell -type ip -vlnv xilinx.com:ip:axi_gpio:2.0 axi_gpio_0
set_property -dict [list \
    CONFIG.C_IS_DUAL {1} \
    CONFIG.C_GPIO_WIDTH {11}  CONFIG.C_ALL_OUTPUTS {1} \
    CONFIG.C_GPIO2_WIDTH {32} CONFIG.C_ALL_INPUTS_2 {1} \
] [get_bd_cells axi_gpio_0]
apply_bd_automation -rule xilinx.com:bd_rule:axi4 \
    -config {Clk_master {Auto} Clk_slave {Auto} Clk_xbar {Auto} \
             Master {/ps7/M_AXI_GP0} Slave {/axi_gpio_0/S_AXI} \
             ddr_seg {Auto} intc_ip {New AXI Interconnect} master_apm {0}} \
    [get_bd_intf_pins axi_gpio_0/S_AXI]

# plain ports the RTL top wires to the core
create_bd_port -dir O -type clk clk
connect_bd_net [get_bd_ports clk] [get_bd_pins ps7/FCLK_CLK0]
create_bd_port -dir O -from 0 -to 0 aresetn
connect_bd_net [get_bd_ports aresetn] \
    [get_bd_pins [get_bd_cells -filter {VLNV =~ *proc_sys_reset*}]/peripheral_aresetn]
create_bd_port -dir O -from 10 -to 0 ctl
connect_bd_net [get_bd_ports ctl] [get_bd_pins axi_gpio_0/gpio_io_o]
create_bd_port -dir I -from 31 -to 0 dbg_data
connect_bd_net [get_bd_ports dbg_data] [get_bd_pins axi_gpio_0/gpio2_io_i]

assign_bd_address
validate_bd_design
save_bd_design

# Global synthesis: synth_design pulls the IP RTL in directly instead of
# expecting per-IP out-of-context checkpoints that only launch_runs would make.
set_property synth_checkpoint_mode None [get_files ps.bd]
generate_target all [get_files ps.bd]
add_files -norecurse [make_wrapper -files [get_files ps.bd] -top]
update_compile_order -fileset sources_1

set env(PS_HWH) [lindex [glob [get_property DIRECTORY [current_project]]/*.gen/sources_1/bd/ps/hw_handoff/ps.hwh] 0]
puts "PS_HWH $env(PS_HWH)"
