/*
 * portkit on JOEBOX 1 (blackbox-mod): what bank 1 (pk_main.c: hooks, settings, the cheap parts) and bank 2 (pk_dsp.c:
 * the DSP) share. Bank 2 calls nothing in bank 1 (blackbox-mod's rule, so a stale bank 2 can never jump into a moved
 * cave): bank 1 hands it everything in these structures, readers included as function pointers. Bank 1 calls bank 2
 * only after b2_live() (blackbox-mod's cpu.c: the payload up there is the one this image was linked with).
 */
#ifndef PK_H
#define PK_H
#include <stdint.h>

#define FN(addr) ((addr) | 1u)

/* --- RAM (re/blackbox.md "RAM": SRAM4 and D2 SRAM are unused by the firmware and by blackbox-mod) --------------- */
#define PK_DIST_STATE  0x38000000u      /* .. 0x380002ff  distortion */
#define PK_GRAINS      0x38000400u      /* .. 0x38000dff  WSOLA grains, 64 slots x 40 bytes */
#define PK_FX3_STATE   0x38000e00u      /* .. 0x38000eff */
#define PK_RVB_STATE   0x38000f00u      /* .. 0x38000fff */
#define PK_PLATE       0x38001000u      /* .. 0x380010af  plate state (0xb0) */
#define PK_PLAYLEN_TXT 0x38001100u      /* .. 0x380017ff  Play Len names, built at boot */
#define PK_FXSUM_L     ((float *)0x38001800u)   /* .. 0x380019ff  FX returns summed (FX1 + FX2 + FX3), for "Rec Input: FX" */
#define PK_FXSUM_R     ((float *)0x38001a00u)   /* .. 0x38001bff */
#define PK_FXSUM_BUF   0x38001c00u      /* .. 0x38001c13  a buffer struct around them (cap, frames, L, R, silent, stereo) */
#define PK_SSL_STATE   0x38001c40u      /* .. 0x38001c4f  SSL compressor */
#define PK_SSL_DRY_L   ((float *)0x38002000u)   /* .. 0x380027ff  its dry copy for Mix (512 frames) */
#define PK_SSL_DRY_R   ((float *)0x38002800u)   /* .. 0x38002fff */
#define PK_D2_BUFS     0x30000000u      /* 212992 bytes: plate buffers */
#define PK_PRE         ((float *)0x30034000u)   /* pre-delay ring, 16384 floats */
#define PK_PRE_LEN     16384
#define PK_ACC_L       ((float *)0x30044000u)   /* FX3 send accumulator */
#define PK_ACC_R       ((float *)0x30044200u)
#define PK_D2_END      0x30044400u
#define PK_USBIN_RING  ((int32_t *)0x38004000u)  /* .. 0x38005fff  audio from the computer: 1024 frames x L, R (24 bit) */
#define PK_USBIN_L     ((float *)0x38006000u)    /* .. 0x380061ff  one block of it, rate-matched, for the recorder */
#define PK_USBIN_R     ((float *)0x38006200u)    /* .. 0x380063ff */
#define PK_USBIN_BUF   0x38006400u               /* .. 0x38006413  a buffer struct around them (as PK_FXSUM_BUF) */
#define PK_MIRROR_BUF  ((float *)0x38006600u)    /* .. 0x380067ff  the headphone mix at Mirror Vol, for Out 3 */
#define PK_USBIN_RD    0x38006500u               /* .. 0x3800653f  the reader's state (task only, struct usbin_rd) */

/* --- WSOLA ---------------------------------------------------------------------------------------------------------- */
typedef int (*pk_read1_fn)(void *stream, float *dst, int n, int pos, int ch, const uint8_t *pad);
typedef int (*pk_read2_fn)(void *stream, float *left, float *right, int n, int pos, const uint8_t *pad);

struct src {
    void *stream;
    const uint8_t *pad;
    int stereo;
    float *sl, *sr;             /* scratch planes (the slot's source buffer) */
    int cap;                    /* scratch capacity in frames */
    pk_read1_fn read1;          /* bank 1's readers (Shift, Loop Fade) */
    pk_read2_fn read2;
};

/* per slot: two grains (old = fading out, age HOP..2HOP; new = fading in, age 0..HOP), positions in file frames */
struct grains {
    uint32_t magic;
    int32_t age;                /* age of the new grain, 0..HOP */
    double s_old, s_new;        /* file position of each grain's first frame */
    double expect;              /* analysis position the next call should start at */
    uint32_t has_old;           /* bit 0: the old grain is running; bits 16-31: when the slot last ran (now16) */
};
#define PK_GMAGIC 0x57534f4cu   /* "WSOL" */
#define PK_HOP    512

/* DWT cycle counter / 65536 (136 us at 480 MHz) */
static inline __attribute__((always_inline)) uint32_t pk_now16(void)
{
    return (*(volatile const uint32_t *)0xe0001004u >> 16) & 0xffffu;
}
#define PK_GAP16 100            /* ~14 ms without a call: the slot had stopped (blocks every 2.7 ms) */

/* bank 2: the WSOLA render; out planes cleared and filled, *consumed / *frac advanced */
void pk_wsola(const struct src *s, volatile struct grains *g, int pos, float rate, double c, int n, float *ol,
              float *or, int *consumed, float *frac, uint32_t now);

/* what bank 1's pk_smooth_wants hands the smooth render (decided just before, same call) */
struct pk_wctx {
    pk_read1_fn read1;
    pk_read2_fn read2;
    float speed;                /* Stretch speed (1 = none) */
    volatile struct grains *g;  /* the slot's grain state */
};
#define PK_WCTX ((volatile struct pk_wctx *)0x38001c20u)  /* .. 0x38001c2f */
/* bank 2: replaces the clip reader at 0x08066622 in Smooth (through pk_clip_entry), same arguments */
int pk_clip_render(void *pad, int unused, int64_t pos64, float rate, int n, int *consumed, float *frac, void *srcbuf,
                   void *outbuf, void **result);

/* --- distortion ----------------------------------------------------------------------------------------------------- */
/* bank 2: bus 0 through the distortion; set = Dist Type, Drive, Tone, Mix, Level as stored */
void pk_dist_bus(uint8_t *bus0);

/* --- loop fade (clips) ---------------------------------------------------------------------------------------------- */
/* bank 2: a dip of f frames at the seams 0, end and (if > 0) seam; frames at logical positions pos .. pos + n */
void pk_loop_fade(float *l, float *r, int n, int pos, int f, int end, int seam);

/* --- FX3 ------------------------------------------------------------------------------------------------------------ */
/* bank 2: the first call sets up the plate in D2 SRAM (clocks, template, cleared memory) and returns 0; later calls run
   the accumulator (have frames) through the reverb onto bus 0 (and onto sum_l / sum_r when not 0: the FX sum for
   "Rec Input: FX"). set = Type, Decay, Damp, Pre-Delay, Size, Level */
struct fx3 {
    uint32_t magic;
    uint32_t pre_w;
    float ph, lp1, lp2, px;     /* decimator */
    float ol, or_, pl, pr;      /* interpolator */
    uint32_t idle, acc_n;       /* blocks since the last input; frames in the accumulator this block */
};
#define PK_F3 ((volatile struct fx3 *)PK_FX3_STATE)
/* bank 2: the block's FX work after the FX2 return is in bus 0: the FX sum (FX1 + FX2 returns, + FX3) for "Rec Input:
   FX", and FX3 itself (set up on the first call, then the reverb onto bus 0). set = FX3 Type, Decay, Damp, Pre-Delay,
   Size, Level */
void pk_fx_block(uint8_t *bus0, uint8_t *bus_fx2);
/* bank 2: the SSL model on Out 1 (in place); set = Thresh, Ratio, Attack, Release, Gain, Mix as stored */
void pk_ssl_run(float *l, float *r, int n);
/* bank 2: scratch x g into FX3's accumulator */
void pk_fx3_add(const uint8_t *scratch, float g);
#define PK_F3MAGIC 0x46583342u   /* "FX3B" at PK_FX3_STATE: set up, the accumulator may be filled */

/* --- USB audio from the computer (Rec Input: USB) --------------------------------------------------------------------
 * JOEBOX's usbdev.c (edited at build time, build.py USBIN_EDITS) gets a second audio streaming interface: endpoint 3,
 * isochronous OUT, adaptive, 2 x 24 bit at 48 kHz. Its receive FIFO handler hands endpoint 3's packets to bank 1's
 * usbin_rx, which passes them to bank 2 while the stream is open (opened only after b2_live(), from the task). */
struct usbin {                  /* SRAM4; the interrupt and the task. usbdev.c's core_setup clears it every boot */
    uint32_t on;                /* USBIN_ON while the computer streams to us and bank 2 takes it */
    uint32_t write;             /* frames written into PK_USBIN_RING (interrupt) */
    uint32_t packets, bad;      /* packets taken; packets of an odd size, dropped */
};
#define PK_UI ((volatile struct usbin *)0x38003f00u)  /* .. 0x38003f0f */
#define USBIN_ON 0x55534231u    /* "USB1": SRAM keeps old values over a reset, so not a plain flag */
#define USBIN_RING 1024u        /* frames */
#define USBIN_MAX 294u          /* bytes a packet: 49 frames x 2 x 3 */
struct usbin_rd {               /* the reader (task context, bank 2) */
    uint32_t magic;             /* PK_URMAGIC: set up */
    uint32_t pos;               /* integer frame position (counts like write) */
    float frac, ratio, fill;    /* fraction of a frame, read rate (1 = nominal), smoothed fill */
    uint32_t underruns, resyncs;
    float integ;                /* the integral part of the rate (the computer's clock offset; kept over a dropout) */
    uint32_t made, made_n;      /* cycle counter when PK_USBIN_L / R were last filled, and with how many frames: the
                                   recorder and a pad's live input share one block of it (filling twice would take
                                   every other block from the computer) */
};
_Static_assert(sizeof(struct usbin_rd) <= 0x40, "usbin_rd runs past PK_USBIN_RD's 64 bytes");
#define PK_URMAGIC 0x55524431u  /* "URD1" */
int pk_usbin_open(void);                 /* bank 2, task: endpoint 3 set up and armed; USBIN_ON */
void pk_usbin_close(void);               /* bank 2, task */
void pk_usbin_rx(unsigned bytes);        /* bank 2, interrupt: a packet in the receive FIFO, into the ring */
void pk_usbin_arm(void);                 /* bank 2, interrupt: endpoint 3 again, for the next frame */
void pk_usbin_fill(int n);               /* bank 2, task: n rate-matched frames into PK_USBIN_L / R + its struct
                                            (once per audio block; a second call in the same block reuses it) */
void pk_usbin_add(float *l, float *r, int n);   /* bank 2, task: the block added into a pad's mix (live input) */

/* --- performance macros MAC1..MAC4 (pk_macro): four toggle buttons on the Pads screen (JOEBOX solo.c's button panel,
   position 0 of the lower-right knob), modulation sources for the stock matrix: engine sources mod5..mod8 (codes
   0x13..0x16, saved as "mod5".."mod8"), value = engine object + 4 (FUN_080519e0's table, re/blackbox.md) ---------- */
struct pk_macro {               /* SRAM4 */
    uint32_t magic;
    uint8_t on[4];              /* the buttons */
    float value[4];             /* 0..1, glides to on[] in MACRO_MS */
};
#define PK_MACRO ((volatile struct pk_macro *)0x38003f40u)   /* .. 0x38003f57 */
#define PK_MMAGIC 0x4d414331u   /* "MAC1" */
#define ID_MAC1 0x1f4           /* the buttons' message ids 0x1f4..0x1f7 (JOEBOX: 0x1f1..0x1f3 MUTE / SOLO / blank) */
void pk_macro_tick(uint8_t *engine, float dt_ms);   /* bank 2, audio task: glide, values into the engine */
void pk_macro_click(uint8_t *view, unsigned k);    /* bank 2, screen: toggle macro k, button lights */
void pk_macro_lights(uint8_t *view);               /* bank 2, screen */
void pk_fx3_send(uint8_t *scratch, const uint8_t *pad);  /* bank 2: a pad's FX3 send into the accumulator */
const float *pk_mirror_scale(const float *a, int frames, int vol);   /* bank 2: Out 3's mirror at Mirror Vol */
void pk_rec_reinit(void *store, const uint8_t *type);   /* bank 2: the pad rebuilt mid-recording, sends kept */
int pk_smooth_decide(const uint8_t *pad, float *frac, const int32_t *srcbuf, float rate);  /* bank 2: Smooth
                              stretch for this slot? sets PK_WCTX->g (bank 1 adds readers and speed) */

#endif
