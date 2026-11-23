/* libgcc replacements.  rv32i has no multiply and no popcount, so gcc turns `a * b` into a call to __mulsi3 and
   __builtin_popcount into __popcountsi2.  Both are sent to fn 0 of the reconfigurable slot:
     multiplier loaded : fn 0 = a * b (low word)  -> `*` is right, popcount is 0
     bitwise loaded    : fn 0 = popcount(a)       -> popcount is right, `*` returns popcount(a)
   so the same binary computes different things depending on which partial bitstream is in the slot. */
#include "prog.h"

uint32_t __mulsi3(uint32_t a, uint32_t b)  { return cfu_call(0, a, b); }
int      __popcountsi2(uint32_t a)         { return (int)cfu_call(0, a, 0); }

/* division is software (shift-subtract): the slot has no divider */
uint32_t __udivsi3(uint32_t n, uint32_t d) {
    uint32_t q = 0, r = 0;
    for (int i = 31; i >= 0; i--) {
        r = (r << 1) | ((n >> i) & 1);
        if (r >= d) { r -= d; q |= 1u << i; }
    }
    return q;
}
uint32_t __umodsi3(uint32_t n, uint32_t d) { return n - __udivsi3(n, d) * d; }   /* calls __mulsi3: needs the multiplier */
int32_t  __divsi3(int32_t n, int32_t d) {
    uint32_t un = n < 0 ? -(uint32_t)n : (uint32_t)n, ud = d < 0 ? -(uint32_t)d : (uint32_t)d, q = __udivsi3(un, ud);
    return (n < 0) != (d < 0) ? -(int32_t)q : (int32_t)q;
}
int32_t  __modsi3(int32_t n, int32_t d) { return n - __divsi3(n, d) * d; }
