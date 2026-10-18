/*
 * FX3 (fx3.c) sends: the FX2 gain loads `vldr s15, [r3]` in the pad voices, pad in r4 at both:
 * - 0x08059ace sample pads: scratch at the caller's [sp, #0x18]
 * - 0x080688d0 clip pads:   scratch at the caller's [sp, #0x14]
 * fx3_send(scratch, pad), then the load; the vcmp after sets the flags. lr is not live (calls before, same function).
 * Frame: 6 words + s0-s14 (15) + 4 = 88 bytes, so the caller's [sp, #x] is [sp, #88 + x].
 */
    .syntax unified
    .thumb
    .text

    .macro SEND name, off
    .global \name
    .thumb_func
    .type \name, %function
\name:
    push    {r0, r1, r2, r3, ip, lr}
    vpush   {s0-s14}
    sub     sp, sp, #4
    ldr     r0, [sp, #(88 + \off)]
    mov     r1, r4
    bl      fx3_send
    add     sp, sp, #4
    vpop    {s0-s14}
    pop     {r0, r1, r2, r3, ip, lr}
    vldr    s15, [r3]
    bx      lr
    .endm

    SEND fx3_send_a, 0x18
    SEND fx3_send_b, 0x14
