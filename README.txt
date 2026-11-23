RISC-V core with a partially reconfigurable accelerator slot (PYNQ-Z2)
Gadila Sai Prashanth Reddy

CONTENTS

report/          project report (PDF)
presentation/    slides (PPTX)
riscv_pdr/       the final build (b3, 40 MHz). It holds the sources and everything the board needs, so this one folder is copied to the board.
                 rtl/ core, two CFU variants, and the board wrapper. tb/ testbench. vivado/ build scripts.
                 sw/ assembler, C programs, and the video encoder. demo/ web page, board server, and self-checks.
                 b3/ b3 bitstreams. b62m5/ 62.5 MHz bitstreams. The config*.bit files at the top are build B2 (50 MHz).
                 run_demo.ipynb starts the demo. demo.ipynb and pr_demo.ipynb are the build B2 notebooks.
source_b2/       sources of build B2 (50 MHz)
source_62m5/     sources of the 62.5 MHz build

REQUIREMENTS

Board: PYNQ-Z2 with a PYNQ 3.x image (tested on PYNQ 3.1.1).
Rebuilding the bitstreams or simulating: Vivado 2022.2. The free edition is enough. Linux is assumed.
Self-checks on a PC: Python 3 and Node.js. C programs: riscv64-linux-gnu-gcc (prebuilt images are already in the page).

RUNNING ON THE BOARD

1. Boot the board and connect it by Ethernet. With no DHCP server a PYNQ image uses the address 192.168.2.99,
   so give the PC an address such as 192.168.2.1/24. With a router, use the address the router gave the board.
2. Copy the folder to the board. The default PYNQ user and password are both xilinx.
       scp -r riscv_pdr xilinx@192.168.2.99:/home/xilinx/jupyter_notebooks/
   The folder must keep the name riscv_pdr.
3. Browse to http://192.168.2.99:9090 and open riscv_pdr/run_demo.ipynb. Select Cell > Run All.
   The first cell replaces whatever design is in the PL. It prints FCLK0 40.0 MHz and stops if the clock is different.
4. The page appears under the second cell. Use it to run programs, swap the accelerator, and play the video.
   Select the driver path for swaps.
5. Shut the kernel down when finished.

The 50 MHz measurements are in pr_demo.ipynb. Restart the kernel before switching between the notebooks.

A swap is sometimes ignored by the configuration engine (1.33% of swaps in the soak test on build B2). The server detects this by
reading the result back, reloads the full bitstream, and continues.

RUNNING WITHOUT A BOARD

    cd riscv_pdr
    python3 demo/board_server.py      then browse to http://localhost:8000 (a software model replaces the board)
    tb/run_sim.sh                     RTL simulation of both variants (source Vivado settings64.sh first)
    python3 sw/rvasm.py --selfcheck
    node demo/sim_check.js
    python3 demo/loader_check.py
    python3 demo/server_check.py

REBUILDING THE BITSTREAMS

    cd riscv_pdr/vivado
    vivado -mode batch -source dfx_flow.tcl
The outputs go to riscv_pdr/vivado/dfx/. A complete run ends with DFX_FLOW_DONE failures=0. Timing must be checked in timing_c1.rpt.
source_b2/vivado and source_62m5/vivado are built the same way.
