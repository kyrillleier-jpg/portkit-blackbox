/*
 * Master distortion for the original Blackbox (portkit, on top of blackbox-mod 3.1.n; same DSP as src/master.c on the
 * Bitbox micro).
 *
 * - Engine (3.1.9, re/blackbox.md "Master"): the block function builds bus 0 (Out 1/2, buffer layout as on the micro:
 *   +4 frames, +8 L, +0xc R, +0x10 silent, +0x11 stereo) at 0x080534cc (r6), adds the FX returns 0xa / 0xb
 *   (0x0804da6c), runs the object at +0xd8c, then the master compressor when its flag (+0xd60) is set (0x08053c98 ->
 *   0x0804eddc, hooked by blackbox-mod's comp_process). dist_thunk replaces the flag's load at 0x08053528, so the
 *   distortion runs on bus 0 before the compressor, whether the compressor is on or not.
 * - Shapers Soft (tanh) / Hard (clip) / Fold (triangle) / Tube (asymmetric tanh, DC blocked), 2x oversampled (31-tap
 *   half-band up / down), Tone (one-pole low-pass, 0..100 % = 200 Hz .. 20 kHz, 100 % = off), Mix (dry delayed by the
 *   filters' 15 samples), Level. State in SRAM4 (0x38000000, unused by the firmware and by blackbox-mod: canary map,
 *   re/blackbox.md "RAM").
 * - Settings: new global ids 0x1e8-0x1ec (unregistered in stock and in blackbox-mod), registered after blackbox-mod's
 *   comp_register (hook 0x0808d350), defaults after its comp_defaults (hook 0x08094886). Shown on a fifth Tools tab
 *   "Dist" (Tools page table 0x080eed18, 5 pages of 36 ids, page 4 empty in stock; tab names 0x080eee80, the first
 *   empty name ends the tab bar).
 */
#include <stdint.h>

#pragma GCC optimize("O2", "no-tree-loop-distribute-patterns")

#define FN(addr) ((addr) | 1u)

typedef void (*register_list_fn)(void *table, int param, const char *label, const char *const *names, int count,
                                 const char *xml);
typedef void (*register_num_fn)(void *table, int param, int type, const char *label, int min, int max, const char *xml);
typedef void (*store_add_fn)(void *store, int param, int value);
typedef int (*setting_fn)(const void *store, unsigned param);
typedef int (*frames_fn)(void *buf);
typedef void (*chans_fn)(void *buf, float **l, float **r);
#define fw_register_list ((register_list_fn)FN(0x0808c0d8))
#define fw_register_num  ((register_num_fn)FN(0x0808c12c))
#define fw_store_add     ((store_add_fn)FN(0x08093ef6))
#define fw_setting       ((setting_fn)FN(0x08093e9c))
#define fw_frames        ((frames_fn)FN(0x0804d8e8))
#define fw_stereo        ((chans_fn)FN(0x0804d9c0))      /* zero-fills a silent buffer, makes it stereo; L, R */

/* blackbox-mod's functions at the shared hook sites (addresses from its cave.elf, bb/build.sh --defsym) */
void comp_register(void *table, int param, int type, const char *label, int min, int max, const char *xml);
void comp_defaults(void *store, int param, int value);
void clip_register(void *table);                          /* clip.c */
void reverb_register_fx3(void *table);                    /* reverb.c */
void reverb_defaults_fx3(void *store);
void fx3_init(void);                                      /* fx3.c */

#define SETTINGS ((const void *)(0x24020088u + 0x8c90u))  /* app: global settings store */
#define P_D_TYPE  0x1e8
#define P_D_DRIVE 0x1e9
#define P_D_TONE  0x1ea
#define P_D_MIX   0x1eb
#define P_D_LEVEL 0x1ec
#define TYPE_DB   7              /* milli-dB, shown as dB */
#define TYPE_PCT  8              /* 0..1000, shown as % */

#define FS 48000.0f

enum { D_OFF, D_SOFT, D_HARD, D_FOLD, D_TUBE, D_TYPES };
static const char *const dist_names[D_TYPES] = {"Off", "Soft", "Hard", "Fold", "Tube"};

/* replaces blackbox-mod's comp_register at 0x0808d350 (the Compressor registration): it, then ours (and clip.c's) */
void bb_register(void *table, int param, int type, const char *label, int min, int max, const char *xml)
{
    comp_register(table, param, type, label, min, max, xml);
    fw_register_list(table, P_D_TYPE, "Dist Type:", dist_names, D_TYPES, "pkdtype");
    fw_register_num(table, P_D_DRIVE, TYPE_DB, "Drive:", 0, 36000, "pkddrive");
    fw_register_num(table, P_D_TONE, TYPE_PCT, "Tone:", 0, 1000, "pkdtone");
    fw_register_num(table, P_D_MIX, TYPE_PCT, "Mix:", 0, 1000, "pkdmix");
    fw_register_num(table, P_D_LEVEL, TYPE_DB, "Level:", -24000, 12000, "pkdlevel");
    clip_register(table);
    fw_register_num(table, 0x1b9, TYPE_PCT, "FX3 Decay:", 0, 1000, "pkfx3decay");
    fw_register_num(table, 0x1ba, TYPE_PCT, "FX3 Damp:", 0, 1000, "pkfx3damp");
    fw_register_num(table, 0x1bb, TYPE_PCT, "FX3 PreDly:", 0, 1000, "pkfx3predelay");
    reverb_register_fx3(table);
}

/* replaces blackbox-mod's comp_defaults at 0x08094886 (global settings defaults): it, then ours */
void bb_defaults(void *store, int param, int value)
{
    comp_defaults(store, param, value);
    fw_store_add(store, P_D_TYPE, D_OFF);
    fw_store_add(store, P_D_DRIVE, 12000);
    fw_store_add(store, P_D_TONE, 1000);
    fw_store_add(store, P_D_MIX, 1000);
    fw_store_add(store, P_D_LEVEL, 0);
    fw_store_add(store, 0x1b9, 600);                     /* FX3 Decay, Damping, Pre-Delay: the stock reverb's defaults */
    fw_store_add(store, 0x1ba, 500);
    fw_store_add(store, 0x1bb, 0);
    reverb_defaults_fx3(store);
    fx3_init();
}

/* --- DSP (as src/master.c) ----------------------------------------------------------------------------------------- */
static float exp2_fast(float x)
{
    if (x < -60.0f)
        return 0.0f;
    if (x > 60.0f)
        x = 60.0f;
    int i = (int)x - (x < 0.0f && (float)(int)x != x);
    float f = x - (float)i, p = 1.0f + f * (0.6951f + f * (0.2262f + f * 0.0782f));
    union { float f; uint32_t u; } v = {p};
    v.u += (uint32_t)i << 23;
    return v.f;
}

static float db_gain(int mdb)
{
    return exp2_fast((float)mdb * (0.001f / 6.0206f));
}

static inline __attribute__((always_inline)) float tanh_r(float x)
{
    x = x > 3.0f ? 3.0f : x < -3.0f ? -3.0f : x;
    float x2 = x * x;
    return x * (27.0f + x2) / (27.0f + 9.0f * x2);
}

#define TUBE_BIAS 0.35f
static inline __attribute__((always_inline)) float shape(int type, float u)
{
    switch (type) {
    case D_SOFT:
        return tanh_r(u);
    case D_HARD:
        return u > 1.0f ? 1.0f : u < -1.0f ? -1.0f : u;
    case D_FOLD: {                                        /* triangle fold: identity up to +-1, then back and forth */
        float t = (u + 1.0f) * 0.25f;
        t -= (float)(int)t - (t < 0.0f && (float)(int)t != t);
        float a = t - 0.5f;
        return 1.0f - 4.0f * (a < 0.0f ? -a : a);
    }
    default:                                              /* Tube: asymmetric, even harmonics; DC removed after */
        return tanh_r(u + TUBE_BIAS) - tanh_r(TUBE_BIAS);
    }
}

/* 2x half-band (31 taps, Kaiser 7): odd taps 1, 3, .. 15; centre 0.5 */
static const float HB[8] = {0.314318663f, -0.094598776f, 0.046056884f, -0.023741433f,
                            0.011624296f, -0.005037228f, 0.001760217f, -0.000394379f};
#define HLEN 16

/* delay lines as rings stored twice (newest first): a window of the last 16 (8) values is always contiguous */
struct dch {
    float xr[2 * HLEN];          /* input; window x[0..15], x[15] = the dry signal, aligned with the output */
    float sbr[2 * HLEN];         /* shaped odd (in-between) samples */
    float sar[16];               /* shaped even samples (8) */
    uint32_t xp, sbp, sap;
    float lp, dcx, dcy;          /* tone low-pass, DC blocker */
};
struct dist {
    uint32_t magic;
    float drive, mix, level;     /* smoothed: the last block's values */
    struct dch ch[2];
};
#define DS ((struct dist *)0x38000000u)
_Static_assert(sizeof(struct dist) <= 0x300, "distortion state: SRAM4 0x38000000-0x380002ff (bb/README.md RAM)");
#define DMAGIC 0x44495355u       /* "DISU" */

static float run1(struct dch *c, int type, float in, float drive, float tone_a, int tone_on)
{
    unsigned p = c->xp = (c->xp - 1u) & (HLEN - 1);
    c->xr[p] = c->xr[p + HLEN] = in;
    const float *x = &c->xr[p];
    float b = HB[0] * (x[7] + x[8]) + HB[1] * (x[6] + x[9]) + HB[2] * (x[5] + x[10]) + HB[3] * (x[4] + x[11])
            + HB[4] * (x[3] + x[12]) + HB[5] * (x[2] + x[13]) + HB[6] * (x[1] + x[14]) + HB[7] * (x[0] + x[15]);
    float sa = shape(type, x[8] * drive);
    float sbv = shape(type, 2.0f * b * drive);
    unsigned q = c->sap = (c->sap - 1u) & 7u;
    c->sar[q] = c->sar[q + 8] = sa;
    unsigned r = c->sbp = (c->sbp - 1u) & (HLEN - 1);
    c->sbr[r] = c->sbr[r + HLEN] = sbv;
    const float *sb = &c->sbr[r];
    float y = 0.5f * c->sar[q + 7]
            + HB[0] * (sb[7] + sb[8]) + HB[1] * (sb[6] + sb[9]) + HB[2] * (sb[5] + sb[10]) + HB[3] * (sb[4] + sb[11])
            + HB[4] * (sb[3] + sb[12]) + HB[5] * (sb[2] + sb[13]) + HB[6] * (sb[1] + sb[14]) + HB[7] * (sb[0] + sb[15]);
    if (type == D_TUBE) {                                  /* DC blocker, ~8 Hz */
        float o = y - c->dcx + 0.999f * c->dcy;
        c->dcx = y;
        c->dcy = o;
        y = o;
    }
    if (tone_on) {
        c->lp += tone_a * (y - c->lp);
        y = c->lp;
    }
    return y;
}

/* dist_thunk at 0x08053528 (bus 0 = r6) */
void master_dist(uint8_t *bus0)
{
    struct dist *d = DS;
    int type = fw_setting(SETTINGS, P_D_TYPE);
    if (type <= D_OFF || type >= D_TYPES) {
        d->magic = 0;                                    /* fresh state when it is switched on again */
        return;
    }
    if (bus0[0x10])                                      /* silent: nothing to shape (the tails are 15 samples) */
        return;
    int n = fw_frames(bus0);
    if (n <= 0 || n > 512)
        return;
    float *l = 0, *r = 0;
    fw_stereo(bus0, &l, &r);
    if (!l || !r)
        return;

    float drive = db_gain(fw_setting(SETTINGS, P_D_DRIVE));
    float mix = (float)fw_setting(SETTINGS, P_D_MIX) * 0.001f;
    float level = db_gain(fw_setting(SETTINGS, P_D_LEVEL));
    mix = mix < 0.0f ? 0.0f : mix > 1.0f ? 1.0f : mix;
    if (d->magic != DMAGIC) {
        uint32_t *w = (uint32_t *)d;
        for (unsigned k = 0; k < sizeof *d / 4; k++)
            w[k] = 0;
        d->drive = drive;
        d->mix = mix;
        d->level = level;
        d->magic = DMAGIC;
    }
    int tone = fw_setting(SETTINGS, P_D_TONE), tone_on = tone < 990;
    float tone_a = 1.0f;
    if (tone_on) {
        float t = (float)(tone < 0 ? 0 : tone) * 0.001f;
        float hz = 200.0f * exp2_fast(t * 6.643856f);   /* 200 Hz .. 20 kHz, exponential */
        float w = 6.2831853f * hz / FS;                  /* one-pole: a = 1 - e^-w, ~ w / (1 + w) */
        tone_a = w / (1.0f + w);
    }

    float inv = 1.0f / (float)n;
    float dr = d->drive, dd = (drive - dr) * inv;
    float mx = d->mix, dm = (mix - mx) * inv;
    float lv = d->level, dl = (level - lv) * inv;
    for (int k = 0; k < n; k++) {
        dr += dd;
        mx += dm;
        lv += dl;
        float wl = run1(&d->ch[0], type, l[k], dr, tone_a, tone_on);
        float dryl = d->ch[0].xr[d->ch[0].xp + HLEN - 1];
        l[k] = (dryl + mx * (wl - dryl)) * lv;
        float wr = run1(&d->ch[1], type, r[k], dr, tone_a, tone_on);
        float dryr = d->ch[1].xr[d->ch[1].xp + HLEN - 1];
        r[k] = (dryr + mx * (wr - dryr)) * lv;
    }
    d->drive = drive;
    d->mix = mix;
    d->level = level;
}

/* Tools tab name and the version shown on the splash / Tools screen (bb/patches/cave.py) */
const char tab_dist[] = "Extra";
const char version_str[] = "3.1.n+pk3";
