/*
 * portkit on JOEBOX 1: the thunks (bank 1). Sites and register use as in the 3.1.n build (bb/src/*_thunk.S,
 * re/blackbox.md), plus pk_clip_entry for the clip reader call that JOEBOX also hooks.
 */
    .syntax unified
    .thumb
    .text

/* 0x08053528 `ldrb.w r3, [r5, #0xd60]` (compressor flag, dead in JOEBOX: its b.w at 0x0805352e always runs the
   compressor stage); bus 0 = r6: master_dist first, then the load */
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

/* 0x08066622, the slot reader's call of the clip reader (stock 0x080662e4, JOEBOX clip_read_b for its machine
   Fidelity modes): pk_smooth_wants(pad r0, frac [sp+8], srcbuf [sp+0xc], rate s0) decides; 1 -> pk_clip_render, 0 ->
   clip_read_b, both entered with every register and the stack as at the call. 6 words + 16 singles = 88 bytes. */
    .global pk_clip_entry
    .thumb_func
    .type pk_clip_entry, %function
pk_clip_entry:
    push    {r0, r1, r2, r3, ip, lr}
    vpush   {s0-s15}
    ldr     r1, [sp, #(88 + 8)]
    ldr     r2, [sp, #(88 + 0xc)]
    bl      pk_smooth_wants
    cmp     r0, #0
    vpop    {s0-s15}
    pop     {r0, r1, r2, r3, ip, lr}
    bne     1f
    b.w     clip_read_b
1:  b.w     pk_clip_render
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

/* the same without JOEBOX's filter patchset: the call there is stock's reader 0x080662e4 */
    .global pk_clip_entry_stock
    .thumb_func
    .type pk_clip_entry_stock, %function
pk_clip_entry_stock:
    push    {r0, r1, r2, r3, ip, lr}
    vpush   {s0-s15}
    ldr     r1, [sp, #(88 + 8)]
    ldr     r2, [sp, #(88 + 0xc)]
    bl      pk_smooth_wants
    cmp     r0, #0
    vpop    {s0-s15}
    pop     {r0, r1, r2, r3, ip, lr}
    bne     2f
    ldr     ip, =0x080662e5
    bx      ip
2:  b.w     pk_clip_render
    .ltorg

/* Rec Input FX (pk_main.c, the record node 0x08061xxx..0x08062xxx, Rec Input in [r4 + 0x58], its source buffer r8):
 * 0x08062120 `cmp r3, #3; beq.w 0x0806277e` (6 bytes) -> bl rec_src_thunk; nop
 *   3 (Resam): on to the stock tap 0x0806277e (copies the main mix in, then continues at 0x08062126 itself)
 *   4 (FX):    rec_fx_copy(r8), back to 0x08062126 (through the nop)
 *   5 (USB):   rec_usb_copy(r8), the same way
 * 0x08062660 `cmp r3, #3; beq 0x0806266c` -> bl rec_mon_thunk: Resam or FX skip the monitor (already in the main
 *   mix: it would double / feed back); USB is monitored like an input (the monitor copies the record buffer r8, which
 *   rec_usb_copy filled, 0x080627d6: stereo unless Rec Input is Left / Right)
 * 0x0809b26a `cmp r0, #3; it ne; cmpne r0, #0` (record start: stereo for L+R / Resam) -> bl rec_stereo_thunk; nop,
 *   FX and USB too; the `ite eq` after reads the flags */
    .global rec_src_thunk
    .thumb_func
    .type rec_src_thunk, %function
rec_src_thunk:
    cmp     r3, #3
    bne     1f
    ldr     ip, =0x0806277f
    bx      ip
1:  cmp     r3, #4
    beq     2f
    cmp     r3, #5
    it      ne
    bxne    lr
2:  push    {r0, r1, r2, r3, ip, lr}
    vpush   {s0-s15}
    mov     r0, r8
    cmp     r3, #4
    bne     3f
    bl      rec_fx_copy
    b       4f
3:  bl      rec_usb_copy
4:  vpop    {s0-s15}
    pop     {r0, r1, r2, r3, ip, lr}
    bx      lr

    .global rec_mon_thunk
    .thumb_func
    .type rec_mon_thunk, %function
rec_mon_thunk:
    cmp     r3, #3
    it      ne
    cmpne   r3, #4
    it      eq
    addeq   lr, lr, #8            /* was beq 0x0806266c: lr = 0x08062665 -> 0x0806266d */
    bx      lr

    .global rec_stereo_thunk
    .thumb_func
    .type rec_stereo_thunk, %function
rec_stereo_thunk:
    cmp     r0, #3
    it      ne
    cmpne   r0, #0
    it      ne
    cmpne   r0, #4
    it      ne
    cmpne   r0, #5
    bx      lr
    .ltorg
