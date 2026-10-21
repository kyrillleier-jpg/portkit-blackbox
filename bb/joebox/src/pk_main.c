/*
 * portkit on JOEBOX 1 (blackbox-mod), bank 1: settings, hooks and the cheap parts (see pk.h for the split; the
 * DSP is pk_dsp.c in bank 2). The features and their reverse engineering are those of the 3.1.n build (bb/src,
 * re/blackbox.md); what changed for JOEBOX:
 * - parameter ids: JOEBOX uses nearly all of 0x19d .. 0x1f3, so the build grows the parameter table to 600 slots
 *   and portkit's ids live from 0x200 on (bb/joebox/ids.py -> pk_ids.h). Saved data is keyed by XML name.
 * - bank 1 is nearly full (the installer refuses an image past 0x08100000): the DSP is in bank 2 and runs only when
 *   b2_live() says the payload is this build's; without it the features pass the audio through untouched.
 * - shared hook sites, chained: comp_register / comp_defaults (comp.c), the clip reader call 0x08066622 (filter.c's
 *   clip_read_b, machine Fidelity modes on clip pads; our WSOLA takes the call only in Smooth).
 * - store capacities: JOEBOX already raised the pad stores and the global settings to 96 entries.
 * - Tools page 4 "Extra" (JOEBOX leaves it empty), at most 11 rows (re/blackbox.md: the list builder's structure).
 */
#include "pk.h"

#pragma GCC optimize("Os", "no-tree-loop-distribute-patterns")

typedef int (*read1_fn)(void *stream, float *dst, int n, int pos, int ch);
typedef int (*read2_fn)(void *stream, float *left, float *right, int n, int pos);
typedef void (*seek_fn)(void *stream, int pos);
typedef int (*frames_fn)(void *obj);
typedef int (*setting_fn)(const void *store, unsigned param);
typedef void (*register_list_fn)(void *table, int param, const char *label, const char *const *names, int count,
                                 const char *xml);
typedef void (*register_num_fn)(void *table, int param, int type, const char *label, int min, int max, const char *xml);
typedef void (*store_add_fn)(void *store, int param, int value);
typedef void (*chans_fn)(void *buf, float **l, float **r);
typedef void (*mix_fn)(void *dst, const void *src);
typedef float (*curve_fn)(float x);
typedef float *(*mono_fn)(void *buf);
typedef int (*planes_fn)(void *buf, float **l, float **r);
#define fw_read1         ((read1_fn)FN(0x08063634))
#define fw_read2         ((read2_fn)FN(0x08063608))
#define fw_seek          ((seek_fn)FN(0x0806375c))
#define fw_frames        ((frames_fn)FN(0x080636f0))   /* stream: frame count; 0x10000000 if the source does not know */
#define fw_stream_stereo ((frames_fn)FN(0x08063790))
#define fw_buf_frames    ((frames_fn)FN(0x0804d8e8))
#define fw_buf_mono      ((mono_fn)FN(0x0804d934))      /* buffer: frames = capacity, mono; returns plane L */
#define fw_buf_pair      ((planes_fn)FN(0x0804da0c))    /* buffer: frames = capacity, stereo; planes L, R */
#define fw_stereo        ((chans_fn)FN(0x0804d9c0))     /* zero-fills a silent buffer, makes it stereo; L, R */
#define fw_mix           ((mix_fn)FN(0x0804da6c))
#define fw_send_curve    ((curve_fn)FN(0x08060930))
#define fw_setting       ((setting_fn)FN(0x08093e9c))
#define fw_register_list ((register_list_fn)FN(0x0808c0d8))
#define fw_register_num  ((register_num_fn)FN(0x0808c12c))
#define fw_store_add     ((store_add_fn)FN(0x08093ef6))

int b2_live(void);                                     /* JOEBOX cpu.c */
void comp_register(void *table, int param, int type, const char *label, int min, int max, const char *xml);
void comp_defaults(void *store, int param, int value); /* JOEBOX comp.c */

#define SETTINGS ((const void *)(0x24020088u + 0x8c90u))
#define APP_PADS (0x24020088u + 0x1840u)
#define TYPE_INT 1
#define TYPE_DB  7
#define TYPE_PCT 8

#include "pk_ids.h"                                  /* bb/joebox/ids.py */
#include "pk_groups.h"                               /* build.py: the groups of this build */

#define PAD_SEGMENTS   0x240
#define PAD_SYNCED     0x1f5
#define PAD_SEGLEN     0x1fc
#define PAD_UNITOUT    0x204
#define PAD_UNIT_TICKS 0x220
#define PAD_SLICED     0x254
#define PAD_STREAM     0x24
#define TICKS_PER_BEAT 960
#define SLICE_TICKS    0xf0000
#define FRAMES_PER_MS  48
#define UNKNOWN_FRAMES 0x10000000

unsigned pad_setting(const uint8_t *pad, unsigned param)
{
    if (!pad)
        return 0;
    uint32_t id = *(const uint32_t *)(pad + 0x18);
    unsigned row = (id >> 8) & 0xff, col = id & 0xff;
    if (row >= 4 || col >= 5)
        return 0;
    return (unsigned)fw_setting((const void *)(APP_PADS + row * 0xf0u + col * 0x30u), param);
}

/* ============================================ settings ============================================ */
static const char *const dist_names[5] = {"Off", "Soft", "Hard", "Fold", "Tube"};
static const char *const rvb_names[4] = {"Plate", "Room", "Hall", "Chamber"};
static const char *const smode_names[3] = {"Auto", "Jump", "Smooth"};
static const char *const sratio_names[3] = {"2:1", "4:1", "10:1"};
static const char *const sattack_names[6] = {"0.1 ms", "0.3 ms", "1 ms", "3 ms", "10 ms", "30 ms"};
static const char *const srel_names[5] = {"0.1 s", "0.3 s", "0.6 s", "1.2 s", "Auto"};
/* Sync: the stock 7 names (list 0x080ec848) + "1/32" (stored indexes keep their meaning, 6 = None) */
static const char *const sync_names[8] = {
    (const char *)0x080ce790u, (const char *)0x080ce700u, (const char *)0x080ce708u, (const char *)0x080ce70cu,
    (const char *)0x080ce710u, (const char *)0x080ce714u, (const char *)0x080cd528u, "1/32",
};
const float sync_beats[8] = {1024.0f, 4.0f, 2.0f, 1.0f, 0.5f, 0.25f, 0.0f, 0.125f};

/* Play Len: Full, 1/4 .. 32 bars in quarter bars; the 129 names are made at boot in SRAM4 (bank 1 has no room) */
static const char *const *playlen_names(void)
{
    const char **ptr = (const char **)PK_PLAYLEN_TXT;
    char *t = (char *)(PK_PLAYLEN_TXT + 129 * 4);
    static const char *const frac[4] = {"", "1/4", "1/2", "3/4"};
    ptr[0] = "Full";
    for (int q = 1; q <= 128; q++) {
        ptr[q] = t;
        int bars = q / 4;
        if (bars >= 10)
            *t++ = (char)('0' + bars / 10);
        if (bars)
            *t++ = (char)('0' + bars % 10);
        if (bars && (q & 3))
            *t++ = ' ';
        for (const char *f = frac[q & 3]; *f; f++)
            *t++ = *f;
        *t++ = 0;
    }
    return (const char *const *)ptr;
}

void sync_register(void *table, int param, const char *label, const char *const *names, int count, const char *xml)
{
    (void)names;
    (void)count;
    fw_register_list(table, param, label, sync_names, 8, xml);
}

/* type 0 = list (names by index, max = count). Packed (bank 1 is nearly full): label and xml name in one string
   ("Label:\0xmlname"), dB ranges in whole dB (all are), names as an index into pnames */
enum { N_NONE, N_DIST, N_RVB, N_SMODE, N_SRATIO, N_SATTACK, N_SREL, N_ONOFF, N_PLAYLEN };
static const char *const onoff_names[2] = {"Off", "On"};
static const char *const *const pnames[N_PLAYLEN] = {0, dist_names, rvb_names, smode_names, sratio_names,
                                                     sattack_names, srel_names, onoff_names};
struct pdef { const char *lx; int16_t min, max; uint16_t id; uint8_t type, names; };
static const struct pdef pdefs[] = {
    {"Dist Type:\0pkdtype", 0, 5, P_D_TYPE, 0, N_DIST},
    {"Drive:\0pkddrive", 0, 36, P_D_DRIVE, TYPE_DB, 0},
    {"Tone:\0pkdtone", 0, 1000, P_D_TONE, TYPE_PCT, 0},
    {"Mix:\0pkdmix", 0, 1000, P_D_MIX, TYPE_PCT, 0},
    {"Level:\0pkdlevel", -24, 12, P_D_LEVEL, TYPE_DB, 0},
    {"FX3 Type:\0pkfx3type", 0, 4, P_R_TYPE, 0, N_RVB},
    {"FX3 Decay:\0pkfx3decay", 0, 1000, P_R_DECAY, TYPE_PCT, 0},
    {"FX3 Damp:\0pkfx3damp", 0, 1000, P_R_DAMP, TYPE_PCT, 0},
    {"FX3 PreDly:\0pkfx3predelay", 0, 1000, P_R_PREDLY, TYPE_PCT, 0},
    {"FX3 Size:\0pkfx3size", 0, 1000, P_R_SIZE, TYPE_PCT, 0},
    {"FX3 Level:\0pkfx3level", 0, 1000, P_R_LEVEL, TYPE_PCT, 0},
    {"Shift ms:\0pkshift", -100, 100, P_SHIFT, TYPE_INT, 0},
    {"Play Len:\0pkplaylen", 0, 129, P_PLAYLEN, 0, N_PLAYLEN},
    {"Stretch %:\0pkstretch", -100, 100, P_STRETCH, TYPE_INT, 0},
    {"Str Mode:\0pkstretchmode", 0, 3, P_SMODE, 0, N_SMODE},
    {"Loop Fade:\0pkloopfade", 0, 50, P_LFADE, TYPE_INT, 0},
    {"FX3 Send:\0pkfx3send", 0, 1000, P_FX3SEND, TYPE_PCT, 0},
    {"SSL Thresh:\0pksslthresh", -48, 0, P_S_THRESH, TYPE_DB, 0},
    {"SSL Ratio:\0pksslratio", 0, 3, P_S_RATIO, 0, N_SRATIO},
    {"SSL Attack:\0pksslattack", 0, 6, P_S_ATTACK, 0, N_SATTACK},
    {"SSL Release:\0pksslrelease", 0, 5, P_S_REL, 0, N_SREL},
    {"SSL Gain:\0pksslgain", -12, 24, P_S_GAIN, TYPE_DB, 0},
    {"SSL Mix:\0pksslmix", 0, 1000, P_S_MIX, TYPE_PCT, 0},
    {"Mirror:\0pkmirror", 0, 2, P_MIRROR, 0, N_ONOFF},
    {"Mirror Vol:\0pkmirrorvol", 0, 1000, P_MIRRORVOL, TYPE_PCT, 0},
};
#define NPDEFS (int)(sizeof pdefs / sizeof pdefs[0])

/* replaces JOEBOX's comp_register at 0x0808d350: it, then ours */
void bb_register(void *table, int param, int type, const char *label, int min, int max, const char *xml)
{
    comp_register(table, param, type, label, min, max, xml);
    for (int k = 0; k < NPDEFS; k++) {
        const struct pdef *p = &pdefs[k];
        const char *xn = p->lx;
        while (*xn++)
            ;
        if (p->type == 0)
            fw_register_list(table, p->id, p->lx, p->names == N_PLAYLEN ? playlen_names() : pnames[p->names], p->max,
                             xn);
        else {
            int k1 = p->type == TYPE_DB ? 1000 : 1;
            fw_register_num(table, p->id, p->type, p->lx, p->min * k1, p->max * k1, xn);
        }
    }
}

/* replaces JOEBOX's comp_defaults at 0x08094886: it, then ours */
void bb_defaults(void *store, int param, int value)
{
    comp_defaults(store, param, value);
    static const int16_t def[][2] = {
        {P_D_TYPE, 0}, {P_D_DRIVE, 12000}, {P_D_TONE, 1000}, {P_D_MIX, 1000}, {P_D_LEVEL, 0},
        {P_R_TYPE, 0}, {P_R_DECAY, 600}, {P_R_DAMP, 500}, {P_R_PREDLY, 0}, {P_R_SIZE, 500}, {P_R_LEVEL, 500},
        {P_S_THRESH, -16000}, {P_S_RATIO, 0}, {P_S_ATTACK, 5}, {P_S_REL, 4}, {P_S_GAIN, 0}, {P_S_MIX, 1000},
        {P_MIRROR, 0}, {P_MIRRORVOL, 1000},
    };
    for (unsigned k = 0; k < sizeof def / sizeof def[0]; k++)
        fw_store_add(store, def[k][0], def[k][1]);
}

/* replaces the FX2 Send add (0xda) in both pad blocks of the record init 0x08093f20: it, then ours */
void pad_store_add(void *store, unsigned param, int value)
{
    fw_store_add(store, (int)param, value);
    static const uint16_t ids[] = {P_SHIFT, P_PLAYLEN, P_STRETCH, P_SMODE, P_LFADE, P_FX3SEND};
    for (unsigned k = 0; k < sizeof ids / sizeof ids[0]; k++)
        fw_store_add(store, ids[k], 0);
}

/* ============================================ distortion ============================================ */
/* dist_thunk at 0x08053528 (bus 0 = r6) */
void master_dist(uint8_t *bus0)
{
    if (b2_live())
        pk_dist_bus(bus0);                              /* reads its settings itself */
}

/* ============================================ clip ============================================ */
/* the pad's shift in frames, 0 if none applies; *frames = the file's frame count */
static int shift_of(const uint8_t *pad, void *stream, int *frames)
{
    if (!pad || pad[PAD_SLICED])
        return 0;
    int ms = (int)pad_setting(pad, P_SHIFT);
    if (ms == 0 || ms < -100 || ms > 100)
        return 0;
    int total = fw_frames(stream);
    if (total <= 0 || total >= UNKNOWN_FRAMES)
        return 0;
    *frames = total;
    int s = (ms * FRAMES_PER_MS) % total;
    return s < 0 ? s + total : s;                       /* 0 <= s < total */
}

/* next run: from stock position pos, at most n frames; *at = where to read it. Returns the run length. */
static int run(int pos, int n, int s, int total, int *at)
{
    if (pos < 0 || pos >= total) {                      /* outside the file: as stock (zero-filled) */
        *at = pos;
        if (pos < 0)
            return -pos < n ? -pos : n;
        return n;
    }
    int p = pos + s;
    if (p >= total)
        p -= total;
    int m = total - pos;                                /* stay inside the file in stock terms */
    if (total - p < m)
        m = total - p;                                  /* and in shifted terms (wrap) */
    *at = p;
    return m < n ? m : n;
}

/* --- Loop Fade (0x183, ms) ------------------------------------------------------------------------------------- */
/* A recorded loop has no material beyond its ends, so a true crossfade is not possible; Loop Fade is a short dip
   instead: the last F frames before a seam fade out, the first F after it fade in (quarter sine, F = ms x 48). Seams:
   the loop start (logical 0), the loop end (synced: segments x segment length x Stretch speed, as the stock wraps,
   at most the file's end; else the file's end) and, with Shift, the file's own seam at logical total - shift. Applied
   to the frames as read (logical position pos + i), so the stock read, its resampling and the WSOLA grains all get it. */
int clip_segments(const uint8_t *pad);
static float clip_speed_of(const uint8_t *pad);

static void loop_fade(const uint8_t *pad, void *stream, float *l, float *r, int n, int pos)
{
    if (!pad || n <= 0)
        return;
    int ms = (int)pad_setting(pad, P_LFADE);
    if (ms <= 0 || ms > 50)
        return;
    int total = fw_frames(stream);
    if (total <= 0 || total >= UNKNOWN_FRAMES)
        return;
    int end = total;
    if (pad[PAD_SYNCED] && !pad[PAD_SLICED]) {
        float e = (float)clip_segments(pad) * *(const float *)(pad + PAD_SEGLEN) * clip_speed_of(pad);
        if (e > 1.0f && e < (float)total)
            end = (int)e;
    }
    int f = ms * FRAMES_PER_MS;
    if (f > end / 4)
        f = end / 4;
    if (f < 2 || !b2_live())
        return;
    int sh = shift_of(pad, stream, &total);
    pk_loop_fade(l, r, n, pos, f, end, sh ? total - sh : 0);
}

/* pk_thunk.S passes the pad (r5 of the reader 0x080662e4, r4 of the segment starts 0x08065290 / 0x08065550) last */
static int clip_read1_raw(void *stream, float *dst, int n, int pos, int ch, const uint8_t *pad)
{
    int total, s = shift_of(pad, stream, &total);
    if (!s)
        return fw_read1(stream, dst, n, pos, ch);
    int ok = 0;
    while (n > 0) {
        int at, m = run(pos, n, s, total, &at);
        ok |= fw_read1(stream, dst, m, at, ch);
        dst += m;
        pos += m;
        n -= m;
    }
    return ok;
}

static int clip_read2_raw(void *stream, float *left, float *right, int n, int pos, const uint8_t *pad)
{
    int total, s = shift_of(pad, stream, &total);
    if (!s)
        return fw_read2(stream, left, right, n, pos);
    int ok = 0;
    while (n > 0) {
        int at, m = run(pos, n, s, total, &at);
        ok |= fw_read2(stream, left, right, m, at);
        left += m;
        if (right)
            right += m;
        pos += m;
        n -= m;
    }
    return ok;
}

int clip_read1(void *stream, float *dst, int n, int pos, int ch, const uint8_t *pad)
{
    int ok = clip_read1_raw(stream, dst, n, pos, ch, pad);
    loop_fade(pad, stream, dst, 0, n, pos);
    return ok;
}

int clip_read2(void *stream, float *left, float *right, int n, int pos, const uint8_t *pad)
{
    int ok = clip_read2_raw(stream, left, right, n, pos, pad);
    loop_fade(pad, stream, left, right, n, pos);
    return ok;
}

void clip_seek(void *stream, int pos, const uint8_t *pad)
{
    int total, s = shift_of(pad, stream, &total);
    if (s && pos >= 0 && pos < total) {
        pos += s;
        if (pos >= total)
            pos -= total;
    }
    fw_seek(stream, pos);
}

static int stretched_count(const uint8_t *pad, int count);

/* thunks clip_segments12 / clip_segments23: `ldrd r1, r2, [r6, #0x240]` / `ldrd r2, r3, [r6, #0x240]` before the add;
   returns the segment count to use (pad = r6) */
int clip_segments(const uint8_t *pad)
{
    int count = *(const int32_t *)(pad + PAD_SEGMENTS) + *(const int32_t *)(pad + PAD_SEGMENTS + 4);
    if (pad[PAD_SLICED])
        return count;
    if (!pad[PAD_SYNCED] || count < 1)
        return count;
    count = stretched_count(pad, count);
    int q = (int)pad_setting(pad, P_PLAYLEN);
    int32_t unit = *(const int32_t *)(pad + PAD_UNIT_TICKS);
    if (q <= 0 || q > 128 || unit <= 0 || unit >= SLICE_TICKS || *(const int32_t *)(pad + PAD_UNIT_TICKS + 4))
        return count;
    int limit = (q * TICKS_PER_BEAT + unit / 2) / unit;
    if (limit < 1)
        limit = 1;
    return limit < count ? limit : count;
}

/* --- stretch -------------------------------------------------------------------------------------------------------- */
/* the pad's Stretch speed (1 = none) */
static float clip_speed_of(const uint8_t *pad)
{
    if (pad[PAD_SLICED])
        return 1.0f;
    int p = (int)pad_setting(pad, P_STRETCH);
    if (p == 0 || p < -100 || p > 100)
        return 1.0f;
    return p > 0 ? 1.0f + (float)p * 0.01f : 1.0f / (1.0f - (float)p * 0.01f);
}

/* segments at this speed, rounded, at least 1 */
static int stretched_count(const uint8_t *pad, int count)
{
    float n = (float)count / clip_speed_of(pad) + 0.5f;
    int c = (int)n;
    return c < 1 ? 1 : c;
}

/* stretch.c: the speed for the smooth (WSOLA) read */
float clip_stretch_speed(const uint8_t *pad)
{
    return clip_speed_of(pad);
}

/* thunk (clip_seglen_thunk): `vldr s15, [r4, #0x1fc]` at 0x0806560c (segment length, then index x length) */
float clip_speed(const uint8_t *pad)
{
    return clip_speed_of(pad);
}

/* thunk (clip_last_thunk): `ldr.w r2, [r4, #0x240]` at 0x080655fe (r2 - 1 == index: last segment) */
int clip_last_count(const uint8_t *pad)
{
    int count = *(const int32_t *)(pad + PAD_SEGMENTS);
    return count < 1 ? count : stretched_count(pad, count);
}



/* ============================================ WSOLA (decision and setup here, the render in bank 2) ============ */
_Static_assert(64 * sizeof(struct grains) <= 0xa00, "grain states: SRAM4 0x38000400-0x38000dff");

/* pk_clip_entry (pk_thunk.S, at the reader call 0x08066622): 1 = our smooth render, 0 = on to clip_read_b. Bank 2
   decides (pk_smooth_decide: the checks, the slot's grains, Str Mode / Auto); bank 1 adds its readers and the speed */
int pk_smooth_wants(const uint8_t *pad, float *frac, const int32_t *srcbuf, float rate)
{
    if (!b2_live() || !pk_smooth_decide(pad, frac, srcbuf, rate))
        return 0;
    volatile struct pk_wctx *w = PK_WCTX;
    w->read1 = clip_read1;
    w->read2 = clip_read2;
    w->speed = clip_stretch_speed(pad);
    return 1;
}

/* ============================================ FX3 ============================================ */
#define MAXN 128

/* thunks fx3_send_a / _b at the FX2 gain loads: scratch x FX3 gain into the accumulator (bank 2) */
void fx3_send(uint8_t *scratch, const uint8_t *pad)
{
    if (b2_live())
        pk_fx3_send(scratch, pad);                      /* bank 2 reads the send and applies the curve */
}

/* --- Out 3 can mirror the headphones (pk_hpout3): Mirror Off / On and Mirror Vol (global, on the page INFO opens on
   Tools > Headphone). JOEBOX usbdev.c's usbaud_tap asks for Out 3's source (build.py HPOUT3_EDITS): its own bus, or
   the headphone mix (bus a, ahead of the headphone volume: independent of it, checked on the unit) at Mirror Vol.
   USB 5-6 stay the real Out 3. */
const float *out3_source(const float *a, const float *b, int frames)
{
    if (fw_setting(SETTINGS, P_MIRROR) != 1)
        return b;
    return b2_live() ? pk_mirror_scale(a, frames, fw_setting(SETTINGS, P_MIRRORVOL)) : a;
}

/* performance macros (JOEBOX duck.c / solo.c call these, build.py MACRO_EDITS); the work is in bank 2 */
void macro_tick(uint8_t *engine, float dt)
{
    if (b2_live())
        pk_macro_tick(engine, dt);
}

void macro_click(uint8_t *view, unsigned k)
{
    if (b2_live())
        pk_macro_click(view, k);
}

void macro_lights(uint8_t *view)
{
    if (b2_live())
        pk_macro_lights(view);
}

/* replaces the block function's "bus 0 += bus 0xb" (bl 0x0804da6c at 0x08053516): that, then the FX sum and FX3 */
void fx3_master(uint8_t *bus0, uint8_t *bus_fx2)
{
    fw_mix(bus0, bus_fx2);
    if (b2_live())
        pk_fx_block(bus0, bus_fx2);
}

/* ============================================ SSL (JOEBOX comp.c calls this for its model "SSL") ============== */
void pk_ssl(float *l, float *r, int n)
{
    if (b2_live())
        pk_ssl_run(l, r, n);
}

/* ============================================ recording ============================================ */
typedef void (*store_init_fn)(void *store, const uint8_t *type);
typedef void (*store_set_fn)(void *store, unsigned param, int value);
typedef void (*copy_fn)(void *dst, const void *src);
#define fw_store_init ((store_init_fn)FN(0x08094a1c))
#define fw_store_set  ((store_set_fn)FN(0x08093ecc))
#define fw_buf_copy   ((copy_fn)FN(0x0804d880))

/* 1-2 s into a recording the firmware rebuilds the pad's record as a clip record (0x0809d5fa -> 0x08094a1c), every
   setting back to its default: bank 2 keeps the FX1 / FX2 / FX3 sends (pk_rec_reinit); without it stock's rebuild */
void rec_reinit(void *store, const uint8_t *type)
{
    if (b2_live())
        pk_rec_reinit(store, type);
    else
        fw_store_init(store, type);
}

/* Rec Input (0x9a): the stock four (list 0x080ec704: L+R, Left, Right, Resam) + FX (+ USB), appended (stored values
   keep their meaning) */
static const char *const rec_names[6] = {
    (const char *)0x080ce6bcu, (const char *)0x080ce6c0u, (const char *)0x080ce6c8u, (const char *)0x080ce6d0u, "FX",
    "USB",
};

void rec_input_register(void *table, int param, const char *label, const char *const *names, int count,
                        const char *xml)
{
    (void)names;
    (void)count;
    fw_register_list(table, param, label, rec_names, PK_HAS_USBIN ? 6 : 5, xml);
}

/* pk_thunk.S rec_src_thunk: the record node's source with Rec Input FX: the FX sum instead of the main mix */
void rec_fx_copy(void *dst)
{
    fw_buf_copy(dst, (const void *)PK_FXSUM_BUF);
}

/* ... and with Rec Input USB: the computer's stream (bank 2 rate-matches it); silence while there is none */
static const uint32_t usb_silent[5] = {128, 128, (uint32_t)PK_USBIN_L, (uint32_t)PK_USBIN_R, 0x101};

void rec_usb_copy(void *dst)
{
    const void *src = usb_silent;
    if (PK_UI->on == USBIN_ON) {
        pk_usbin_fill(fw_buf_frames(dst));
        src = (const void *)PK_USBIN_BUF;
    }
    fw_buf_copy(dst, src);
}

/* --- JOEBOX usbdev.c's hooks for endpoint 3 (build.py USBIN_EDITS); bank 2 only while the stream is open, which it
   is only after b2_live() (asked from the task, never from the interrupt: its first call may scan bank 2) -------- */
void usbin_reset(void)                                  /* core_setup, every boot: nothing open */
{
    PK_UI->on = 0;
}

void usbin_open(int on)                                 /* task: SET_INTERFACE 2, SET_CONFIGURATION, bus reset */
{
    int was = PK_UI->on == USBIN_ON;
    PK_UI->on = 0;
    if (was)
        pk_usbin_close();
    if (on && b2_live())
        PK_UI->on = pk_usbin_open() ? USBIN_ON : 0;
}

int usbin_alt(void)                                     /* GET_INTERFACE 2 */
{
    return PK_UI->on == USBIN_ON;
}

void usbin_rx(unsigned bytes)                           /* interrupt: endpoint 3's packet waits in the receive FIFO */
{
    if (PK_UI->on == USBIN_ON) {
        pk_usbin_rx(bytes);
        return;
    }
    for (unsigned i = 0; i < bytes; i += 4)             /* not ours to take: read it out all the same */
        (void)*(volatile uint32_t *)0x40041000u;
}

void usbin_add(float *l, float *r, int n)               /* JOEBOX insert.c: a pad's live input set to USB */
{
    if (PK_UI->on == USBIN_ON)
        pk_usbin_add(l, r, n);
}

void usbin_done(void)                                   /* interrupt: endpoint 3's transfer finished, or one missed */
{
    if (PK_UI->on == USBIN_ON)
        pk_usbin_arm();
}

/* version shown on the splash / Tools (patches/pk.py repoints JOEBOX's four users) */
const char pk_tab[] = "Extra";
