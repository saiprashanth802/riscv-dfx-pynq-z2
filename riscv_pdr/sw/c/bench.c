/* Software shift-add multiply vs the slot, same inputs.  IN[0]=n  IN[1]=x0  IN[2]=y0  IN[3]=mode (0 soft, 1 `*`).
   acc = sum over i=1..n of (x0+i)*(y0+i) mod 2^32.  The PL cycle counter gives the cost of each mode; with the multiplier in
   the slot both modes agree, with the bitwise unit `*` returns popcount(a) and the checksums differ. */
#include "prog.h"
static uint32_t soft_mul(uint32_t a, uint32_t b) {
    uint32_t r = 0;
    while (b) { if (b & 1) r += a; a <<= 1; b >>= 1; }
    return r;
}
int main(void) {
    uint32_t n = IN[0], x0 = IN[1], y0 = IN[2], mode = IN[3], acc = 0;
    for (uint32_t i = 1; i <= n; i++) {
        uint32_t x = x0 + i, y = y0 + i;
        acc += mode ? x * y : soft_mul(x, y);
    }
    OUT[0] = acc;
    return 0;
}
