/* One video frame, or one chunk of a frame, per run.  dmem: fb[0..575] (96x64, three 1 bpp planes R G B of 192 words,
   kept between runs)  W[576] = clear flag  W[577] = n  W[578..] = idx, val, idx, val ...   fb[idx] ^= val, with the XOR
   done by fn 2 of the slot.  A key frame is larger than dmem has room for, so the PS feeds it in chunks of at most
   200 pairs: 578 + 400 words stops below the stack, which starts at word 1023.
   No `*` anywhere on purpose: with the wrong unit loaded a `*` would corrupt the loop's own addressing instead of
   the picture (build.sh --no-cfu-libcalls enforces this). */
#include "prog.h"
#define FB 576
int main(void) {
    volatile uint32_t *fb = DMEM, *p = DMEM + FB + 2;
    uint32_t n = DMEM[FB + 1];
    if (DMEM[FB]) for (int i = 0; i < FB; i++) fb[i] = 0;
    for (uint32_t k = 0; k < n; k++, p += 2) {
        uint32_t idx = p[0];
        fb[idx] = cfu_call(2, fb[idx], p[1]);
    }
    return 0;
}
