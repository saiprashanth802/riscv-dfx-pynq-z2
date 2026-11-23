/* Conventions shared by every program in sw/c.  All memory is WORD-ONLY: no char/short, no byte arrays. */
#ifndef PROG_H
#define PROG_H
typedef unsigned int uint32_t;
typedef int          int32_t;

#define DMEM   ((volatile uint32_t *)0x10000000u)
#define OUT    (DMEM)              /* words 0..63    results; the PS reads these back                      */
#define IN     (DMEM + 64)         /* words 64..127  inputs; the PS writes them after loading the program  */
#define CFU    ((volatile uint32_t *)0xF0000000u)

/* Drive the reconfigurable slot: op_a, op_b, fn (+0x0, +0x4, +0x8), result at +0xC.  Combinational on this build
   (B2/b3); the 62.5 MHz build needs a nop between the fn write and the result read. */
static inline uint32_t cfu_call(uint32_t fn, uint32_t a, uint32_t b) {
    CFU[0] = a; CFU[1] = b; CFU[2] = fn;
    return CFU[3];
}
#endif
