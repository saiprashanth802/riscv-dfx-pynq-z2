# start-up: stack at the top of the 4 KB dmem alias, run main, then halt in a self-jump
# (the PL cycle counter freezes at that jump -- it is what tells the PS the program is done).
    .section .text.start
    .globl _start
_start:
    lui  sp, 0x10001          # 0x1000_1000; the first push lands at 0x1000_0FFC = dmem word 1023
    jal  ra, main
1:  j    1b
