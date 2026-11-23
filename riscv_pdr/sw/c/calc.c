/* The thesis in nine lines.  Operands come from IN[], written by the loader AFTER the program is loaded, so gcc cannot
   fold them: `*` is a real call to __mulsi3 and popcount a real call to __popcountsi2, both served by the slot.
   OUT[0] = a*b  OUT[1] = popcount(a)  OUT[2] = a & b (plain RV32I, slot-independent)  OUT[3] = a*b + 1 */
#include "prog.h"
int main(void) {
    uint32_t a = IN[0], b = IN[1];
    OUT[0] = a * b;
    OUT[1] = (uint32_t)__builtin_popcount(a);
    OUT[2] = a & b;
    OUT[3] = a * b + 1;
    return 0;
}
