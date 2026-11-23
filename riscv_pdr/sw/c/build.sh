#!/usr/bin/env bash
# build.sh prog.c [--no-cfu-libcalls]  ->  sw/c/out/prog.json  {imem, dmem}
# Cross compiler: riscv64-linux-gnu-gcc (Fedora gcc-riscv64-linux-gnu), or the no-root copy under ~/.local/riscv.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
if ! command -v riscv64-linux-gnu-gcc >/dev/null && [ -x "$HOME/.local/riscv/usr/bin/riscv64-linux-gnu-gcc" ]; then
    export PATH="$HOME/.local/riscv/usr/bin:$PATH" LD_LIBRARY_PATH="$HOME/.local/riscv/usr/lib64:${LD_LIBRARY_PATH:-}"
fi
src="${1:?usage: build.sh prog.c [--no-cfu-libcalls]}"; shift || true
name="$(basename "$src" .c)"; mkdir -p "$here/out"; elf="$here/out/$name.elf"
# -fno-pie/-no-pie/-static: Fedora defaults to PIE, whose GOT needs a relocator the core does not have.
# -mno-relax -msmall-data-limit=0: no gp-relative addressing (gp is never set up).  -O1 keeps the listing readable.
FLAGS="-march=rv32i -mabi=ilp32 -O1 -ffreestanding -nostdlib -nostartfiles -fno-pie -mno-relax -msmall-data-limit=0 -fno-asynchronous-unwind-tables -ffunction-sections -fdata-sections -Wall -Wextra -I$here"
# Compile with the driver, link with ld directly: nothing here needs libgcc or start files, and the relocated no-root gcc
# cannot find its own ld.  (-fno-pie: Fedora defaults to PIE, whose GOT needs a relocator the core does not have.)
objs=()
for f in "$here/crt0.S" "$here/cfu.c" "$src"; do
    o="$here/out/$name.$(basename "$f").o"; riscv64-linux-gnu-gcc $FLAGS -c "$f" -o "$o"; objs+=("$o")
done
riscv64-linux-gnu-ld -m elf32lriscv -static -nostdlib --gc-sections -T "$here/link.ld" -o "$elf" "${objs[@]}"
python3 "$here/mkimg.py" "$elf" "$here/out/$name.json" --objdump "$(command -v riscv64-linux-gnu-objdump)" "$@"
