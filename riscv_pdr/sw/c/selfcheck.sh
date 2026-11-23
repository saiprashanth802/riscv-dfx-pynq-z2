#!/usr/bin/env bash
# The build guard must refuse what the core cannot run, and the three programs must show the libcalls the demo depends on.
set -u
cd "$(dirname "$0")"
export PATH="$HOME/.local/riscv/usr/bin:$PATH" LD_LIBRARY_PATH="$HOME/.local/riscv/usr/lib64:${LD_LIBRARY_PATH:-}"
fail() { echo "SELFCHECK FAIL: $*"; exit 1; }
for p in calc bench; do ./build.sh $p.c >/dev/null || fail "$p does not build"; done
./build.sh rick.c --no-cfu-libcalls >/dev/null || fail "rick must build with no CFU libcalls"
D="riscv64-linux-gnu-objdump -d -M no-aliases,numeric --no-show-raw-insn"
$D out/calc.elf | grep -qE "jalr?\b.*<__mulsi3>"      || fail "calc: gcc folded the multiply (no call to __mulsi3)"
$D out/calc.elf | grep -qE "jalr?\b.*<__popcountsi2>" || fail "calc: popcount was expanded inline (no call to __popcountsi2)"
./build.sh calc.c --no-cfu-libcalls >/dev/null 2>&1   && fail "--no-cfu-libcalls accepted a program that calls __mulsi3"
# byte access, M-extension and volatile-free folding must be refused / visible
t=$(mktemp -d); trap 'rm -rf "$t"' EXIT
cat > "$t/bytes.c" <<'C'
#include "prog.h"
int main(void) { volatile unsigned char *p = (volatile unsigned char *)(DMEM + 200); p[1] = (unsigned char)IN[0]; OUT[0] = p[1]; return 0; }
C
./build.sh "$t/bytes.c" >"$t/log" 2>&1 && fail "a program using bytes was accepted"
grep -q "lbu\|sb\|lb" "$t/log" || fail "byte rejection did not name the instruction: $(cat "$t/log")"
echo "sw/c selfcheck: OK (calc has real __mulsi3/__popcountsi2 calls; bytes and CFU-libcall misuse are refused)"
