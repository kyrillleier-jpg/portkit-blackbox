/*
 * Blackbox master distortion hook (bb/src/master.c):
 * - 0x08053528 `ldrb.w r3, [r5, #0xd60]` (the block function's compressor flag, bus 0 built and the FX returns added;
 *   bus 0 = r6): master_dist(bus 0) first, then the load. Flags are set by the cmp after it; lr is not live (calls
 *   before the site in the same function).
 */
    .syntax unified
    .thumb
    .text

    .global dist_thunk
    .thumb_func
    .type dist_thunk, %function
dist_thunk:
    push    {r0, r1, r2, r3, ip, lr}
    vpush   {s0-s15}
    mov     r0, r6
    bl      master_dist
    vpop    {s0-s15}
    pop     {r0, r1, r2, r3, ip, lr}
    ldrb.w  r3, [r5, #0xd60]
    bx      lr
