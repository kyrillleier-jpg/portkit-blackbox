/*
 * Clip functions (clip.c) on the Blackbox: the call sites' registers differ from the Bitbox micro's in places.
 * 0x08063634 (stream, dst, n, pos, [sp] ch)  at 0x0806636e, 0x0806644e -> clip_read1(..., ch, pad = r5)
 * 0x08063608 (stream, l, r, n, [sp] pos)     at 0x080663ba, 0x0806642c -> clip_read2(..., pos, pad = r5)
 * 0x0806375c (stream, pos)                   at 0x0806541a, 0x0806578c -> clip_seek(stream, pos, pad = r4)
 * Play length (clip voice 0x080667b8, pad in r6; the add and cmp after set the flags):
 *   0x08066e7a `ldrd r1, r2, [r6, #0x240]` -> r1 = pad[0x240], r2 = clip_segments(pad) - r1   (clip_segments12)
 *   0x08066c46 `ldrd r2, r3, [r6, #0x240]` -> r2 = pad[0x240], r3 = clip_segments(pad) - r2   (clip_segments23)
 * Stretch (segment start 0x08065550, pad in r4):
 *   0x0806560c `vldr s15, [r4, #0x1fc]` -> s15 = segment length x clip_speed(pad) (copied to s16, then x index at
 *              0x080656bc; s16 has no other use on that path). lr is not live there (it is at 0x080656bc).
 *   0x080655fe `ldr.w r2, [r4, #0x240]` -> r2 = clip_last_count(pad) (subs / cmp follow)
 */
    .syntax unified
    .thumb
    .text

    .macro STACK5 name, target
    .global \name
    .thumb_func
    .type \name, %function
\name:
    push    {r4, lr}
    ldr     ip, [sp, #8]          /* the caller's fifth argument */
    sub     sp, sp, #8
    str     ip, [sp]
    str     r5, [sp, #4]          /* sixth: the pad (r5 in the reader) */
    bl      \target
    add     sp, sp, #8
    pop     {r4, pc}
    .endm

    STACK5 clip_read1_thunk, clip_read1
    STACK5 clip_read2_thunk, clip_read2

    .global clip_seek_thunk
    .thumb_func
    .type clip_seek_thunk, %function
clip_seek_thunk:
    mov     r2, r4
    b.w     clip_seek

    .global clip_segments12
    .thumb_func
    .type clip_segments12, %function
clip_segments12:
    push    {r0, r3, ip, lr}
    mov     r0, r6
    bl      clip_segments
    ldr     r1, [r6, #0x240]
    sub     r2, r0, r1
    pop     {r0, r3, ip, lr}
    bx      lr

    .global clip_segments23
    .thumb_func
    .type clip_segments23, %function
clip_segments23:
    push    {r0, r1, ip, lr}
    mov     r0, r6
    bl      clip_segments
    ldr     r2, [r6, #0x240]
    sub     r3, r0, r2
    pop     {r0, r1, ip, lr}
    bx      lr

    .global clip_seglen_thunk
    .thumb_func
    .type clip_seglen_thunk, %function
clip_seglen_thunk:
    push    {r0, r1, r2, r3, ip, lr}
    vpush   {s0-s14}
    sub     sp, sp, #4
    mov     r0, r4
    bl      clip_speed
    vmov    r0, s0
    add     sp, sp, #4
    vpop    {s0-s14}
    vldr    s15, [r4, #0x1fc]
    vpush   {s14}
    vmov    s14, r0
    vmul.f32 s15, s15, s14
    vpop    {s14}
    pop     {r0, r1, r2, r3, ip, lr}
    bx      lr

    .global clip_last_thunk
    .thumb_func
    .type clip_last_thunk, %function
clip_last_thunk:
    push    {r0, r1, r3, ip, lr}
    sub     sp, sp, #4
    vpush   {s0-s15}
    mov     r0, r4
    bl      clip_last_count
    mov     r2, r0
    vpop    {s0-s15}
    add     sp, sp, #4
    pop     {r0, r1, r3, ip, lr}
    bx      lr
