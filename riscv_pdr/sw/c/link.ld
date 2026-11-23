/* Harvard layout for the riscv_pdr core: code in imem at 0, data in dmem.
   dmem is 4 KB and decodes addr[11:2]; the CFU window is addr[31:28]==0xF, so the dmem alias 0x1000_0000 is safe.
   Words 0..383 of dmem are left for the program's I/O area (see prog.h); .data/.bss start at word 384.
   Nothing copies .data at start-up: the loader writes the dmem image straight into dmem. */
OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY {
  IMEM (rx)  : ORIGIN = 0x00000000, LENGTH = 1K      /* 256 words, rtl/imem.v */
  DMEM (rw)  : ORIGIN = 0x10000600, LENGTH = 2560     /* up to the stack, which grows down from 0x1000_1000 */
}
SECTIONS {
  .text   : { *(.text.start) *(.text .text.*) }                                   > IMEM
  .rodata : { *(.rodata .rodata.* .srodata .srodata.*) }                          > DMEM
  .data   : { *(.data .data.* .sdata .sdata.*) }                                  > DMEM
  .bss    : { *(.sbss .sbss.* .bss .bss.* COMMON) }                               > DMEM
  /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) *(.riscv.attributes) }
}
