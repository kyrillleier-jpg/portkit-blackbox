/*
 * Clip functions for the Blackbox (portkit; src/clipshift.c of the Bitbox micro on the Blackbox's addresses, same clip
 * engine: pad struct, slots, reader / seek / segment logic match instruction for instruction, re/blackbox.md "Clip").
 *
 * - Shift (-100 .. +100 ms): rotates a clip's audio against its loop. The clip reader 0x080662e4 reads through
 *   0x08063634 (one plane, at 0x0806636e / 0x0806644e) and 0x08063608 (both, at 0x080663ba / 0x0806642c), the segment
 *   starts 0x08065290 / 0x08065550 seek with 0x0806375c (0x0806541a / 0x0806578c); every read and seek inside the
 *   file is mapped to (pos + shift) mod frames. Slicer pads are left alone.
 * - Play Len (Full, 1/4 .. 32 bars): caps the segment count of synced clips at the clip voice's two loop tests
 *   (0x08066c46, 0x08066e7a).
 * - Stretch (-100 .. +100 %) and Stretch Mode (Auto / Jump / Smooth): segment positions scaled by the speed
 *   (0x0806560c, the segment length's load), the last-segment test (0x080655fe) and the count by 1 / speed; Smooth =
 *   WSOLA in bb/src/stretch.c.
 * - Loop Fade for clips (0 .. 50 ms): a short dip at the loop's seams (the Blackbox's own Loop Fade 0xfa is for sample
 *   pads, it is not on the clip page).
 * - Sync 1/32: the Sync list (0x94) gets an eighth entry, its beats table (0x080ec82c, literal 0x08067bb4 in the clip
 *   parameter handler) an eighth value.
 * Settings are pad parameters 0x1ed-0x1f1 (free in stock and blackbox-mod), read from the pad's app record
 * (app +0x1840 + row x 0xf0 + col x 0x30, as blackbox-mod's filter.c), added to every pad record after FX2 Send
 * (0x08094112 / 0x08094346), shown on the clip Pos page (0x080ef288, 0x080ef990).
 */
#include <stdint.h>

#pragma GCC optimize("O2", "no-tree-loop-distribute-patterns")

#define FN(addr) ((addr) | 1u)

typedef int (*read1_fn)(void *stream, float *dst, int n, int pos, int ch);
typedef int (*read2_fn)(void *stream, float *left, float *right, int n, int pos);
typedef void (*seek_fn)(void *stream, int pos);
typedef int (*frames_fn)(void *stream);
typedef int (*setting_fn)(const void *store, unsigned param);
typedef void (*register_list_fn)(void *table, int param, const char *label, const char *const *names, int count,
                                 const char *xml);
typedef void (*register_num_fn)(void *table, int param, int type, const char *label, int min, int max, const char *xml);
typedef void (*store_add_fn)(void *store, int param, int value);
#define fw_read1  ((read1_fn)FN(0x08063634))
#define fw_read2  ((read2_fn)FN(0x08063608))
#define fw_seek   ((seek_fn)FN(0x0806375c))
#define fw_frames ((frames_fn)FN(0x080636f0))   /* frame count; 0x10000000 if the source does not know it */
#define fw_setting       ((setting_fn)FN(0x08093e9c))
#define fw_register_list ((register_list_fn)FN(0x0808c0d8))
#define fw_register_num  ((register_num_fn)FN(0x0808c12c))
#define fw_store_add     ((store_add_fn)FN(0x08093ef6))

#define P_SHIFT        0x1ed
#define P_PLAYLEN      0x1ee      /* list index: 0 = Full, q = q quarter bars (1 .. 128) */
#define P_STRETCH      0x1ef      /* -100 .. 100 % */
#define P_SMODE        0x1f0      /* Stretch Mode (stretch.c): Auto / Jump / Smooth */
#define P_LFADE        0x1f1      /* ms, 0 = off */
#define P_FX3SEND      0x1f2      /* fx3.c: 0 .. 1000 */
#define PAD_SEGMENTS   0x240      /* + 0x244: segment count */
#define PAD_SYNCED     0x1f5
#define PAD_SEGLEN     0x1fc      /* float: file frames per segment */
#define PAD_UNIT_TICKS 0x220      /* int64 */
#define TICKS_PER_BEAT 960
#define SLICE_TICKS    0xf0000
#define PAD_SLICED     0x254
#define FRAMES_PER_MS  48
#define UNKNOWN_FRAMES 0x10000000
#define TYPE_INT       1          /* integer (nicht verifiziert: Anzeige wie auf der Micro) */

#define APP_PADS (0x24020088u + 0x1840u)

/* the pad's value from its app record (what the screen shows and presets save); engine pad id +0x18 = bank << 16 |
   row << 8 | col */
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

static inline __attribute__((always_inline)) float qsin(float t)  /* sin(pi / 2 t), 0 <= t <= 1 */
{
    float t2 = t * t;
    return t * (1.5707963f + t2 * (-0.6459641f + t2 * 0.0751678f));   /* coefficients sum to 1: ends at exactly 1 */
}

static void fade_zone(float *l, float *r, int n, int pos, int a, int b, int out, float inv)
{
    /* frames with logical position in [a, b): out ? fading out towards b : fading in from a */
    int lo = a > pos ? a - pos : 0, hi = b < pos + n ? b - pos : n;
    for (int i = lo; i < hi; i++) {
        int d = out ? b - 1 - (pos + i) : pos + i - a;
        float g = qsin((float)d * inv);
        l[i] *= g;
        if (r && r != l)
            r[i] *= g;
    }
}

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
    if (f < 2)
        return;
    float inv = 1.0f / (float)f;
    if (pos < f)
        fade_zone(l, r, n, pos, 0, f, 0, inv);
    if (pos + n > end - f)
        fade_zone(l, r, n, pos, end - f, end, 1, inv);
    int sh = shift_of(pad, stream, &total);
    if (sh) {
        int seam = total - sh;                          /* logical position of the file's seam */
        if (seam > f && seam < end - f) {
            fade_zone(l, r, n, pos, seam - f, seam, 1, inv);
            fade_zone(l, r, n, pos, seam, seam + f, 0, inv);
        }
    }
}

/* thunks in clip_thunk.S pass the pad (r5 of the reader 0x080662e4, r4 of the segment starts 0x08065290 /
   0x08065550) as the last argument */
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

/* --- play length ------------------------------------------------------------------------------------------------- */
const char *const playlen_names[129] = {
    "Full", "1/4", "1/2", "3/4", "1", "1 1/4", "1 1/2", "1 3/4", "2", "2 1/4",
    "2 1/2", "2 3/4", "3", "3 1/4", "3 1/2", "3 3/4", "4", "4 1/4", "4 1/2", "4 3/4",
    "5", "5 1/4", "5 1/2", "5 3/4", "6", "6 1/4", "6 1/2", "6 3/4", "7", "7 1/4",
    "7 1/2", "7 3/4", "8", "8 1/4", "8 1/2", "8 3/4", "9", "9 1/4", "9 1/2", "9 3/4",
    "10", "10 1/4", "10 1/2", "10 3/4", "11", "11 1/4", "11 1/2", "11 3/4", "12", "12 1/4",
    "12 1/2", "12 3/4", "13", "13 1/4", "13 1/2", "13 3/4", "14", "14 1/4", "14 1/2", "14 3/4",
    "15", "15 1/4", "15 1/2", "15 3/4", "16", "16 1/4", "16 1/2", "16 3/4", "17", "17 1/4",
    "17 1/2", "17 3/4", "18", "18 1/4", "18 1/2", "18 3/4", "19", "19 1/4", "19 1/2", "19 3/4",
    "20", "20 1/4", "20 1/2", "20 3/4", "21", "21 1/4", "21 1/2", "21 3/4", "22", "22 1/4",
    "22 1/2", "22 3/4", "23", "23 1/4", "23 1/2", "23 3/4", "24", "24 1/4", "24 1/2", "24 3/4",
    "25", "25 1/4", "25 1/2", "25 3/4", "26", "26 1/4", "26 1/2", "26 3/4", "27", "27 1/4",
    "27 1/2", "27 3/4", "28", "28 1/4", "28 1/2", "28 3/4", "29", "29 1/4", "29 1/2", "29 3/4",
    "30", "30 1/4", "30 1/2", "30 3/4", "31", "31 1/4", "31 1/2", "31 3/4", "32"
};

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


/* --- Sync 1/32 ------------------------------------------------------------------------------------------------------ */
/* the stock 7 names (list 0x080ec848) + "1/32", appended so stored indexes keep their meaning (6 = None) */
const char *const sync_names[8] = {
    (const char *)0x080ce790u, (const char *)0x080ce700u, (const char *)0x080ce708u, (const char *)0x080ce70cu,
    (const char *)0x080ce710u, (const char *)0x080ce714u, (const char *)0x080cd528u, "1/32",
};
const float sync_beats[8] = {1024.0f, 4.0f, 2.0f, 1.0f, 0.5f, 0.25f, 0.0f, 0.125f};

/* replaces the Sync registration (bl register_list at 0x0808d104) */
void sync_register(void *table, int param, const char *label, const char *const *names, int count, const char *xml)
{
    (void)names;
    (void)count;
    fw_register_list(table, param, label, sync_names, 8, xml);
}

/* --- registration and pad defaults --------------------------------------------------------------------------------- */
static const char *const smode_names[3] = {"Auto", "Jump", "Smooth"};

/* from bb_register (master.c) */
void clip_register(void *table)
{
    fw_register_num(table, P_SHIFT, TYPE_INT, "Shift ms:", -100, 100, "pkshift");
    fw_register_list(table, P_PLAYLEN, "Play Len:", playlen_names, 129, "pkplaylen");
    fw_register_num(table, P_STRETCH, TYPE_INT, "Stretch %:", -100, 100, "pkstretch");
    fw_register_list(table, P_SMODE, "Str Mode:", smode_names, 3, "pkstretchmode");
    fw_register_num(table, P_LFADE, TYPE_INT, "Loop Fade:", 0, 50, "pkloopfade");
    fw_register_num(table, P_FX3SEND, 8, "FX3 Send:", 0, 1000, "pkfx3send");   /* fx3.c */
}

/* replaces the FX2 Send add (0xda) in both pad blocks of the record init 0x08093f20: it, then ours (the clip record:
   59 stock + 6 = 65; capacity raised to 72, bb/patches/clip.py) */
void pad_store_add(void *store, unsigned param, int value)
{
    fw_store_add(store, (int)param, value);
    fw_store_add(store, P_SHIFT, 0);
    fw_store_add(store, P_PLAYLEN, 0);
    fw_store_add(store, P_STRETCH, 0);
    fw_store_add(store, P_SMODE, 0);
    fw_store_add(store, P_LFADE, 0);
    fw_store_add(store, P_FX3SEND, 0);
}
