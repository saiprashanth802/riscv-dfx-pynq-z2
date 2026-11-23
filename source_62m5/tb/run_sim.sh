#!/usr/bin/env bash
# Simulate the core with BOTH reconfigurable-slot variants using Vivado xsim.
# Usage: ./run_sim.sh          (runs variant A then variant B)
#        ./run_sim.sh mul      (variant A only)
#        ./run_sim.sh bitwise  (variant B only)
#
# Needs Vivado on PATH (source /tools/Xilinx/Vivado/2022.2/settings64.sh).
# Icarus is NOT required -- xsim ships with Vivado, which is needed anyway.
set -u
cd "$(dirname "$0")"
RTL=../rtl
COMMON="$RTL/regfile.v $RTL/imm_gen.v $RTL/alu.v $RTL/control.v $RTL/branch_unit.v \
        $RTL/pc.v $RTL/imem.v $RTL/dmem.v $RTL/cfu_mmio.v $RTL/riscv_top.v"

run_variant() {
    local name=$1 src=$2 def=$3
    local wd=xsim_$name
    rm -rf "$wd"; mkdir -p "$wd"
    cp program.hex "$wd"/            # $readmemh resolves relative to the run dir
    ( cd "$wd" \
      && xvlog $def -i "$RTL/../rtl" $(for f in $COMMON; do echo "../$f"; done) \
               "../$RTL/$src" ../tb_riscv.v > xvlog.log 2>&1 \
      && xelab tb_riscv -s tb_sim > xelab.log 2>&1 \
      && xsim tb_sim -runall > xsim.log 2>&1 )
    local rc=$?
    echo "================ variant $name ($src) ================"
    if [ $rc -ne 0 ]; then
        echo "BUILD/RUN ERROR -- last log:"; tail -20 "$wd"/*.log; return 1
    fi
    sed -n '/run -all/,/^exit/p' "$wd"/xsim.log | sed '1d;$d'
    grep -q "ALL TESTS PASSED" "$wd"/xsim.log
}

rc=0
case "${1:-both}" in
    mul)     run_variant mul     cfu_mul.v     ""              || rc=1 ;;
    bitwise) run_variant bitwise cfu_bitwise.v "-d CFU_BITWISE" || rc=1 ;;
    both)    run_variant mul     cfu_mul.v     ""              || rc=1
             run_variant bitwise cfu_bitwise.v "-d CFU_BITWISE" || rc=1 ;;
    *) echo "usage: $0 [mul|bitwise|both]"; exit 2 ;;
esac

echo
if [ $rc -eq 0 ]; then echo ">>> ALL VARIANTS PASSED"; else echo ">>> FAILURES -- see logs"; fi
exit $rc
