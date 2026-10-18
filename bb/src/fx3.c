/*
 * FX3 for the Blackbox (portkit; src/fx3.c of the Bitbox micro): a third send effect, a reverb of its own (Plate /
 * Room / Hall / Chamber, reverb.c), next to the stock FX1 (delay / Munchi) and FX2 (reverb / Room).
 *
 * - Send: every pad renders into a scratch buffer, then adds it x FX1 / FX2 gain to buses 0xa / 0xb (0x0804db4c), each
 *   send checked on its own (`vldr s15, [gain]`; sample pads 0x08059acc ff., clip pads 0x080688bc ff.). The FX2 gain
 *   load (0x08059ace sample, scratch [sp +0x18], bus array r5; 0x080688d0 clip, scratch [sp +0x14], bus array r7; pad
 *   r4 at both) first adds scratch x FX3 gain to FX3's own accumulator. FX3 Send (0x1f2) is a pad setting from the
 *   app record, gain through the stock send curve 0x08060930. No engine bus: buses 0xc / 0xd are used on the
 *   Blackbox and 0x10 / 0x11 not proven free.
 * - Effect: the block function adds bus 0xb (FX2 return) to bus 0 at 0x08053516; fx3_master does that, then runs the
 *   accumulator through the reverb at 29.8 kHz (decimated with a two-pole low-pass, interpolated back, pre-delay of its
 *   own, as the stock reverb does) and adds it to bus 0 (before the distortion and the compressor). Run-on ~30 s.
 * - Settings: global (Tools tab "Extra"): FX3 Decay 0x1b9, Damping 0x1ba, Pre-Delay 0x1bb, plus reverb.c's (0x1b8,
 *   0x1bc ..).
 * - Memory: D2 SRAM (unused by firmware and mod, canary map; clocks switched on here): the plate buffers (the stock
 *   init's 12 buffers, 212992 bytes), the pre-delay ring and the accumulator. Plate state words as the stock init
 *   0x08074d1c leaves them (template below, extracted in Unicorn: tests/test_bb_fx3.py compares). Set up once from the
 *   settings defaults (UI thread, boot).
 */
#include <stdint.h>

#pragma GCC optimize("O2", "no-tree-loop-distribute-patterns")

#define FN(addr) ((addr) | 1u)

typedef void (*mix_fn)(void *dst, const void *src);
typedef void (*chans_fn)(void *buf, float **l, float **r);
typedef int (*frames_fn)(void *buf);
typedef float (*curve_fn)(float x);
typedef int (*setting_fn)(const void *store, unsigned param);
#define fw_mix        ((mix_fn)FN(0x0804da6c))
#define fw_stereo     ((chans_fn)FN(0x0804d9c0))      /* zero-fills a silent buffer, makes it stereo; L, R */
#define fw_frames     ((frames_fn)FN(0x0804d8e8))
#define fw_send_curve ((curve_fn)FN(0x08060930))      /* send value / 1000 -> gain (the stock send setters) */
#define fw_setting    ((setting_fn)FN(0x08093e9c))

unsigned pad_setting(const uint8_t *pad, unsigned param);                                       /* clip.c */
void reverb_run_record(float *state, const void *rec, const float *in, float *outl, float *outr, int n);  /* reverb.c */

#define SETTINGS  ((const void *)(0x24020088u + 0x8c90u))
#define P_FX3SEND 0x1f2
#define P_DECAY   0x1b9
#define P_DAMP    0x1ba
#define P_PREDLY  0x1bb
#define FS_IN     48000.0f
#define FS_RVB    29800.0f
#define MAXN      128                                   /* engine block */
#define MAXM      (MAXN * 2 / 3 + 4)                    /* 29.8 kHz frames per block */
#define RUN_ON    (30u * 48000u / MAXN)                 /* blocks the tail runs on after the last input (~30 s) */

/* D2 SRAM layout */
#define D2_BUFS   0x30000000u                           /* 212992 bytes: plate buffers */
#define PRE       ((float *)0x30034000u)                /* pre-delay ring */
#define PRE_LEN   16384
#define ACC_L     ((float *)0x30044000u)                /* send accumulator, 2 x 128 floats */
#define ACC_R     ((float *)0x30044200u)
#define D2_END    0x30044400u
_Static_assert(D2_END <= 0x30048000u, "FX3 memory must end inside D2 SRAM");

struct fx3 {
    uint32_t magic;
    uint32_t pre_w;
    float ph, lp1, lp2, px;      /* decimator: phase (29.8 kHz periods), two-pole low-pass, last filtered input */
    float ol, or_, pl, pr;       /* interpolator: current and previous reverb outputs */
    uint32_t idle;               /* blocks since the accumulator last had signal */
    uint32_t acc_n;              /* frames in the accumulator this block (0 = nothing sent) */
};
#define F3    ((volatile struct fx3 *)0x38000e00u)      /* SRAM4 */
#define PLATE ((float *)0x38001000u)                    /* plate state, 0xb0 bytes (SRAM4) */
_Static_assert(sizeof(struct fx3) <= 0x100, "FX3 state: SRAM4 0x38000e00-0x38000eff");
#define F3MAGIC 0x46583342u      /* "FX3B" */

/* plate state as the stock init leaves it; 0 at the buffer words (filled in below) */
static const uint32_t plate_tmpl[44] = {
    0x3f000000, 0x3a03126f, 0, 0, 0, 0, 0x3f7fdf3b, 0,
    0, 0x008e0000, 0x3f400000, 0, 0x006b0000, 0x3f400000, 0, 0x017b0000,
    0x3f200000, 0, 0x01150000, 0x3f200000, 0, 0x02a00000, 0x3f333333, 0,
    0x000232fe, 0, 0x038c0000, 0x3f333333, 0, 0x000232ef, 0, 0x07080000,
    0x3f000000, 0, 0x0a600000, 0x3f000000, 0x11650000, 0, 0x10790000, 0,
    0x0e880000, 0, 0x0c5b0000, 0,
};
static const struct { uint8_t word; uint16_t bytes; } plate_bufs[12] = {
    {8, 2048}, {11, 2048}, {14, 2048}, {17, 2048}, {20, 4096}, {25, 4096},
    {30, 32768}, {33, 32768}, {37, 32768}, {39, 32768}, {41, 32768}, {43, 32768},
};

/* from bb_defaults (settings init, UI thread at boot): D2 SRAM clocks on, plate state and memory */
void fx3_init(void)
{
    if (F3->magic == F3MAGIC)
        return;
    volatile uint32_t *ahb2enr = (volatile uint32_t *)0x580244dcu;   /* RCC_AHB2ENR: SRAM1/2/3EN = bits 29..31 */
    *ahb2enr |= 7u << 29;
    (void)*ahb2enr;
    uint32_t *st = (uint32_t *)PLATE;
    for (int k = 0; k < 44; k++)
        st[k] = plate_tmpl[k];
    uint32_t a = D2_BUFS;
    for (int i = 0; i < 12; i++) {
        st[plate_bufs[i].word] = a;
        a += plate_bufs[i].bytes;
    }
    for (uint32_t *p = (uint32_t *)D2_BUFS; p < (uint32_t *)D2_END; p++)
        *p = 0;
    volatile struct fx3 *f = F3;
    f->pre_w = 0;
    f->ph = f->lp1 = f->lp2 = f->px = 0.0f;
    f->ol = f->or_ = f->pl = f->pr = 0.0f;
    f->idle = RUN_ON;
    f->acc_n = 0;
    f->magic = F3MAGIC;
}

/* --- pad sends ------------------------------------------------------------------------------------------------------ */
/* thunks fx3_send_a / _b at the FX2 gain loads: scratch x FX3 gain into the accumulator */
void fx3_send(uint8_t *scratch, const uint8_t *pad)
{
    volatile struct fx3 *f = F3;
    if (f->magic != F3MAGIC || !scratch || scratch[0x10])
        return;
    int v = (int)pad_setting(pad, P_FX3SEND);
    if (v <= 0)
        return;
    float g = fw_send_curve((float)(v > 1000 ? 1000 : v) * 0.001f);
    if (!(g > 0.0f))
        return;
    int n = fw_frames(scratch);
    if (n <= 0 || n > MAXN)
        return;
    const float *l = *(float *const *)(scratch + 8);
    const float *r = scratch[0x11] ? *(float *const *)(scratch + 0xc) : l;
    if (!l)
        return;
    if (!r)
        r = l;
    uint32_t have = f->acc_n;
    for (int k = 0; k < n; k++) {
        float a = g * l[k], b = g * r[k];
        if ((uint32_t)k < have) {
            ACC_L[k] += a;
            ACC_R[k] += b;
        } else {
            ACC_L[k] = a;
            ACC_R[k] = b;
        }
    }
    if ((uint32_t)n > have)
        f->acc_n = (uint32_t)n;
}

/* --- the effect ----------------------------------------------------------------------------------------------------- */
/* replaces the block function's "bus 0 += bus 0xb" (bl 0x0804da6c at 0x08053516): that, then bus 0 += FX3 */
void fx3_master(uint8_t *bus0, void *bus_fx2)
{
    fw_mix(bus0, bus_fx2);
    volatile struct fx3 *f = F3;
    if (f->magic != F3MAGIC)
        return;
    int n = fw_frames(bus0);
    if (n <= 0 || n > MAXN)
        n = MAXN;
    uint32_t have = f->acc_n;
    f->acc_n = 0;
    if (have == 0) {
        if (f->idle >= RUN_ON)
            return;                                     /* no input and the tail has run out */
        f->idle++;
    } else {
        f->idle = 0;
    }
    for (uint32_t k = have; k < (uint32_t)n; k++)
        ACC_L[k] = ACC_R[k] = 0.0f;
    float *ol = 0, *or_ = 0;
    fw_stereo(bus0, &ol, &or_);
    if (!ol)
        return;
    if (!or_)
        or_ = ol;

    float *st = PLATE;
    st[0] = (float)fw_setting(SETTINGS, P_DECAY) * (0.001f * 0.93f);
    st[1] = (float)fw_setting(SETTINGS, P_DAMP) * 0.001f;
    int pre_d = (int)((float)fw_setting(SETTINGS, P_PREDLY) * 0.001f * 12000.0f) + 256;
    if (pre_d > PRE_LEN - 2)
        pre_d = PRE_LEN - 2;
    if (pre_d < 1)
        pre_d = 1;

    /* decimate 48 -> 29.8 kHz: two one-pole low-passes, linear interpolation at the 29.8 kHz instants */
    const float r = FS_RVB / FS_IN, a = 0.6f;
    float tin[MAXM], tl[MAXM], tr[MAXM];
    float ph0 = f->ph, ph = ph0, l1 = f->lp1, l2 = f->lp2, px = f->px;
    uint32_t w = f->pre_w;
    int m = 0;
    for (int k = 0; k < n; k++) {
        float x = 0.5f * (ACC_L[k] + ACC_R[k]);
        l1 += a * (x - l1);
        l2 += a * (l1 - l2);
        float cur = l2;
        ph += r;
        if (ph >= 1.0f && m < MAXM) {
            ph -= 1.0f;
            float back = ph / r;
            float v = cur + (px - cur) * back;
            PRE[w & (PRE_LEN - 1)] = v;
            tin[m++] = PRE[(w - (uint32_t)pre_d) & (PRE_LEN - 1)];
            w++;
        }
        px = cur;
    }
    f->lp1 = l1;
    f->lp2 = l2;
    f->px = px;
    f->pre_w = w;
    if (m > 0)
        reverb_run_record(st, SETTINGS, tin, tl, tr, m);

    float cl = f->ol, cr = f->or_, pl = f->pl, pr = f->pr;
    int j = 0;
    ph = ph0;
    for (int k = 0; k < n; k++) {
        ph += r;
        if (ph >= 1.0f && j < m) {
            ph -= 1.0f;
            pl = cl;
            pr = cr;
            cl = tl[j];
            cr = tr[j];
            j++;
        }
        ol[k] += pl + (cl - pl) * ph;
        if (or_ != ol)
            or_[k] += pr + (cr - pr) * ph;
    }
    f->ph = ph;
    f->ol = cl;
    f->or_ = cr;
    f->pl = pl;
    f->pr = pr;
}
