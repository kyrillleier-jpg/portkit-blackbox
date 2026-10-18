/*
 * Smooth time stretch for clip pads on the Blackbox (portkit; src/stretch.c of the Bitbox micro with the Blackbox's
 * addresses: same clip engine, slot layout and reader arguments, re/blackbox.md "Clip"): WSOLA (waveform-similarity overlap-add) in place of the clip slot's
 * read + resample 0x080662e4 (its only caller 0x08066622, the slot reader 0x08066454).
 *
 * Stock: a clip slot reads its file at the pitch rate (s0: file rate x pitch) and keeps time only by starting every
 * Sync unit (segment k) at file position k x segment length; when the song tempo differs from the clip's, each unit
 * either stops short or runs into the next one (jumps). Stretch (bb/src/clip.c) scales those segment positions.
 * Smooth: the slot's file position (slot +8, frac at slot +0x1c) advances by c = segment length x speed / output
 * frames per segment (pad +0x1fc, +0x204) per output frame, so every segment ends exactly where the next one starts,
 * while the sound is built from grains read at the pitch rate: 2 x HOP frames, Hann window, 50 % overlap. Each new grain
 * starts near the analysis position, shifted by up to +-SEARCH frames to the place where its start best matches the
 * continuation of the previous grain (decimated cross-correlation, then refined to the frame). Pitch and tempo are
 * independent; the clip follows the song tempo without jumps, and Stretch changes the tempo without changing pitch.
 *
 * Stretch Mode (0x1f0): Auto = Smooth while Stretch is not 0, else stock; Jump = stock (Stretch by jumping, pkQ);
 * Smooth = always (also follows the song tempo smoothly at Stretch 0). Only for synced clips (pad +0x1f5), not slicer.
 * Reads go through clip_read1 / clip_read2 (bb/src/clip.c), so Shift applies. Grain state per slot in SRAM4.
 */
#include <stdint.h>

#define FN(addr) ((addr) | 1u)

/* 0x080662e4(pad, -, int64 pos, s0 rate, n, int *consumed, float *frac, srcbuf, outbuf, void **result) */
typedef int (*slot_read_fn)(void *pad, int unused, int64_t pos, float rate, int n, int *consumed, float *frac,
                            void *src, void *out, void **result);
#define fw_slot_read ((slot_read_fn)FN(0x080662e4))
typedef int (*u8_fn)(void *obj);
#define fw_stereo    ((u8_fn)FN(0x08063790))          /* stream: two channels (+0x1c) */
typedef int (*frames_fn)(void *stream);
#define fw_frames    ((frames_fn)FN(0x080636f0))
typedef float *(*mono_fn)(void *buf);
#define fw_buf_mono  ((mono_fn)FN(0x0804d934))       /* buffer: frames = capacity, mono; returns plane L */
typedef int (*planes_fn)(void *buf, float **l, float **r);
#define fw_buf_stereo ((planes_fn)FN(0x0804da0c))    /* buffer: frames = capacity, stereo; planes L, R */

int clip_read1(void *stream, float *dst, int n, int pos, int ch, const uint8_t *pad);       /* clip.c */
int clip_read2(void *stream, float *left, float *right, int n, int pos, const uint8_t *pad);
unsigned pad_setting(const uint8_t *pad, unsigned param);                                   /* clip.c */
float clip_stretch_speed(const uint8_t *pad);                                               /* clip.c */

#define P_STRETCH   0x1ef
#define P_SMODE     0x1f0       /* list: 0 Auto, 1 Jump, 2 Smooth */
#define PAD_ID      0x18
#define PAD_STREAM  0x24
#define PAD_SEGLEN  0x1fc       /* float: file frames per segment */
#define PAD_SYNCED  0x1f5
#define PAD_UNITOUT 0x204       /* float: output frames per segment */
#define PAD_SLICED  0x254
#define SLOT0       0x30
#define SLOT_SIZE   0x70
#define SLOT_FRAC   0x1c

#define HOP     512             /* output frames between grain starts; grain = 2 x HOP */
#define SEARCH  256             /* +- file frames the grain start may move */
#define DEC     8               /* decimation of the coarse search */
#define REFINE  4               /* +- frames around the coarse best */
#define TGT     (HOP / DEC)     /* coarse template length */
#define FINE    64              /* fine template length (frames); search buffers ~1.6 KB on the audio task's stack */

static const float win_rise[HOP] = {
    0.0000000f, 0.0000094f, 0.0000376f, 0.0000847f, 0.0001506f, 0.0002353f, 0.0003388f, 0.0004611f,
    0.0006023f, 0.0007622f, 0.0009409f, 0.0011385f, 0.0013548f, 0.0015899f, 0.0018437f, 0.0021163f,
    0.0024076f, 0.0027177f, 0.0030465f, 0.0033940f, 0.0037602f, 0.0041451f, 0.0045487f, 0.0049709f,
    0.0054117f, 0.0058712f, 0.0063493f, 0.0068460f, 0.0073612f, 0.0078950f, 0.0084473f, 0.0090181f,
    0.0096074f, 0.0102151f, 0.0108413f, 0.0114859f, 0.0121489f, 0.0128303f, 0.0135300f, 0.0142481f,
    0.0149844f, 0.0157390f, 0.0165118f, 0.0173028f, 0.0181120f, 0.0189393f, 0.0197847f, 0.0206483f,
    0.0215298f, 0.0224294f, 0.0233470f, 0.0242825f, 0.0252359f, 0.0262072f, 0.0271963f, 0.0282033f,
    0.0292280f, 0.0302704f, 0.0313305f, 0.0324082f, 0.0335036f, 0.0346165f, 0.0357470f, 0.0368949f,
    0.0380602f, 0.0392430f, 0.0404431f, 0.0416605f, 0.0428951f, 0.0441470f, 0.0454160f, 0.0467021f,
    0.0480054f, 0.0493256f, 0.0506628f, 0.0520169f, 0.0533878f, 0.0547756f, 0.0561802f, 0.0576015f,
    0.0590394f, 0.0604939f, 0.0619650f, 0.0634525f, 0.0649565f, 0.0664769f, 0.0680136f, 0.0695665f,
    0.0711357f, 0.0727210f, 0.0743224f, 0.0759398f, 0.0775732f, 0.0792225f, 0.0808876f, 0.0825686f,
    0.0842652f, 0.0859775f, 0.0877053f, 0.0894487f, 0.0912076f, 0.0929818f, 0.0947714f, 0.0965762f,
    0.0983962f, 0.1002314f, 0.1020815f, 0.1039467f, 0.1058268f, 0.1077217f, 0.1096314f, 0.1115558f,
    0.1134948f, 0.1154483f, 0.1174164f, 0.1193988f, 0.1213956f, 0.1234066f, 0.1254318f, 0.1274711f,
    0.1295244f, 0.1315917f, 0.1336729f, 0.1357678f, 0.1378765f, 0.1399987f, 0.1421346f, 0.1442839f,
    0.1464466f, 0.1486226f, 0.1508119f, 0.1530143f, 0.1552297f, 0.1574582f, 0.1596995f, 0.1619536f,
    0.1642205f, 0.1665000f, 0.1687921f, 0.1710967f, 0.1734136f, 0.1757428f, 0.1780842f, 0.1804378f,
    0.1828034f, 0.1851809f, 0.1875703f, 0.1899714f, 0.1923842f, 0.1948086f, 0.1972445f, 0.1996918f,
    0.2021503f, 0.2046201f, 0.2071011f, 0.2095930f, 0.2120959f, 0.2146096f, 0.2171341f, 0.2196692f,
    0.2222149f, 0.2247710f, 0.2273375f, 0.2299143f, 0.2325012f, 0.2350982f, 0.2377052f, 0.2403220f,
    0.2429486f, 0.2455849f, 0.2482308f, 0.2508862f, 0.2535509f, 0.2562249f, 0.2589081f, 0.2616004f,
    0.2643016f, 0.2670118f, 0.2697306f, 0.2724582f, 0.2751943f, 0.2779389f, 0.2806919f, 0.2834531f,
    0.2862225f, 0.2889999f, 0.2917852f, 0.2945784f, 0.2973793f, 0.3001879f, 0.3030040f, 0.3058275f,
    0.3086583f, 0.3114963f, 0.3143414f, 0.3171935f, 0.3200525f, 0.3229182f, 0.3257907f, 0.3286696f,
    0.3315551f, 0.3344468f, 0.3373449f, 0.3402490f, 0.3431591f, 0.3460752f, 0.3489970f, 0.3519246f,
    0.3548577f, 0.3577962f, 0.3607402f, 0.3636893f, 0.3666436f, 0.3696029f, 0.3725672f, 0.3755362f,
    0.3785099f, 0.3814882f, 0.3844709f, 0.3874580f, 0.3904494f, 0.3934448f, 0.3964443f, 0.3994477f,
    0.4024548f, 0.4054657f, 0.4084801f, 0.4114979f, 0.4145191f, 0.4175434f, 0.4205709f, 0.4236014f,
    0.4266348f, 0.4296709f, 0.4327096f, 0.4357509f, 0.4387947f, 0.4418407f, 0.4448889f, 0.4479392f,
    0.4509914f, 0.4540455f, 0.4571013f, 0.4601588f, 0.4632177f, 0.4662780f, 0.4693396f, 0.4724024f,
    0.4754662f, 0.4785309f, 0.4815964f, 0.4846626f, 0.4877294f, 0.4907966f, 0.4938642f, 0.4969321f,
    0.5000000f, 0.5030679f, 0.5061358f, 0.5092034f, 0.5122706f, 0.5153374f, 0.5184036f, 0.5214691f,
    0.5245338f, 0.5275976f, 0.5306604f, 0.5337220f, 0.5367823f, 0.5398412f, 0.5428987f, 0.5459545f,
    0.5490086f, 0.5520608f, 0.5551111f, 0.5581593f, 0.5612053f, 0.5642491f, 0.5672904f, 0.5703291f,
    0.5733652f, 0.5763986f, 0.5794291f, 0.5824566f, 0.5854809f, 0.5885021f, 0.5915199f, 0.5945343f,
    0.5975452f, 0.6005523f, 0.6035557f, 0.6065552f, 0.6095506f, 0.6125420f, 0.6155291f, 0.6185118f,
    0.6214901f, 0.6244638f, 0.6274328f, 0.6303971f, 0.6333564f, 0.6363107f, 0.6392598f, 0.6422038f,
    0.6451423f, 0.6480754f, 0.6510030f, 0.6539248f, 0.6568409f, 0.6597510f, 0.6626551f, 0.6655532f,
    0.6684449f, 0.6713304f, 0.6742093f, 0.6770818f, 0.6799475f, 0.6828065f, 0.6856586f, 0.6885037f,
    0.6913417f, 0.6941725f, 0.6969960f, 0.6998121f, 0.7026207f, 0.7054216f, 0.7082148f, 0.7110001f,
    0.7137775f, 0.7165469f, 0.7193081f, 0.7220611f, 0.7248057f, 0.7275418f, 0.7302694f, 0.7329882f,
    0.7356984f, 0.7383996f, 0.7410919f, 0.7437751f, 0.7464491f, 0.7491138f, 0.7517692f, 0.7544151f,
    0.7570514f, 0.7596780f, 0.7622948f, 0.7649018f, 0.7674988f, 0.7700857f, 0.7726625f, 0.7752290f,
    0.7777851f, 0.7803308f, 0.7828659f, 0.7853904f, 0.7879041f, 0.7904070f, 0.7928989f, 0.7953799f,
    0.7978497f, 0.8003082f, 0.8027555f, 0.8051914f, 0.8076158f, 0.8100286f, 0.8124297f, 0.8148191f,
    0.8171966f, 0.8195622f, 0.8219158f, 0.8242572f, 0.8265864f, 0.8289033f, 0.8312079f, 0.8335000f,
    0.8357795f, 0.8380464f, 0.8403005f, 0.8425418f, 0.8447703f, 0.8469857f, 0.8491881f, 0.8513774f,
    0.8535534f, 0.8557161f, 0.8578654f, 0.8600013f, 0.8621235f, 0.8642322f, 0.8663271f, 0.8684083f,
    0.8704756f, 0.8725289f, 0.8745682f, 0.8765934f, 0.8786044f, 0.8806012f, 0.8825836f, 0.8845517f,
    0.8865052f, 0.8884442f, 0.8903686f, 0.8922783f, 0.8941732f, 0.8960533f, 0.8979185f, 0.8997686f,
    0.9016038f, 0.9034238f, 0.9052286f, 0.9070182f, 0.9087924f, 0.9105513f, 0.9122947f, 0.9140225f,
    0.9157348f, 0.9174314f, 0.9191124f, 0.9207775f, 0.9224268f, 0.9240602f, 0.9256776f, 0.9272790f,
    0.9288643f, 0.9304335f, 0.9319864f, 0.9335231f, 0.9350435f, 0.9365475f, 0.9380350f, 0.9395061f,
    0.9409606f, 0.9423985f, 0.9438198f, 0.9452244f, 0.9466122f, 0.9479831f, 0.9493372f, 0.9506744f,
    0.9519946f, 0.9532979f, 0.9545840f, 0.9558530f, 0.9571049f, 0.9583395f, 0.9595569f, 0.9607570f,
    0.9619398f, 0.9631051f, 0.9642530f, 0.9653835f, 0.9664964f, 0.9675918f, 0.9686695f, 0.9697296f,
    0.9707720f, 0.9717967f, 0.9728037f, 0.9737928f, 0.9747641f, 0.9757175f, 0.9766530f, 0.9775706f,
    0.9784702f, 0.9793517f, 0.9802153f, 0.9810607f, 0.9818880f, 0.9826972f, 0.9834882f, 0.9842610f,
    0.9850156f, 0.9857519f, 0.9864700f, 0.9871697f, 0.9878511f, 0.9885141f, 0.9891587f, 0.9897849f,
    0.9903926f, 0.9909819f, 0.9915527f, 0.9921050f, 0.9926388f, 0.9931540f, 0.9936507f, 0.9941288f,
    0.9945883f, 0.9950291f, 0.9954513f, 0.9958549f, 0.9962398f, 0.9966060f, 0.9969535f, 0.9972823f,
    0.9975924f, 0.9978837f, 0.9981563f, 0.9984101f, 0.9986452f, 0.9988615f, 0.9990591f, 0.9992378f,
    0.9993977f, 0.9995389f, 0.9996612f, 0.9997647f, 0.9998494f, 0.9999153f, 0.9999624f, 0.9999906f
};

static float window(int age)    /* Hann over 2 x HOP: rising half from the table, falling half = 1 - rising */
{
    return age < HOP ? win_rise[age] : 1.0f - win_rise[age - HOP];
}

/* per slot: two grains (old = fading out, age HOP..2HOP; new = fading in, age 0..HOP), positions in file frames */
struct grains {
    uint32_t magic;
    int32_t age;                /* age of the new grain, 0..HOP */
    double s_old, s_new;        /* file position of each grain's first frame */
    double expect;              /* analysis position the next call should start at */
    uint32_t has_old;           /* bit 0: the old grain is running; bits 16-31: when the slot last ran (now16) */
};
#define GMAGIC 0x57534f4cu      /* "WSOL" */
#define SLOTS  64               /* 16 pads x 4 slots */
#define GRAINS ((volatile struct grains *)0x38000400u)   /* SRAM4 (bb/README.md RAM), 64 x 40 bytes */
_Static_assert(64 * sizeof(struct grains) <= 0xa00, "grain states: SRAM4 0x38000400-0x38000dff");
_Static_assert(sizeof(struct grains) == 40, "grain state size");

/* coarse time for "is this slot still playing": DWT cycle counter / 65536 (136 us at 480 MHz; enabled by blackbox-mod's cpu.c and by clip_render) */
static inline __attribute__((always_inline)) uint32_t now16(void)
{
    return (*(volatile const uint32_t *)0xe0001004u >> 16) & 0xffffu;
}
#define GAP16 100               /* ~14 ms without a call: the slot had stopped (blocks come every 2.7 ms) */

static int floor_i(double x)
{
    int i = (int)x;
    return (double)i > x ? i - 1 : i;
}

struct src {
    void *stream;
    const uint8_t *pad;
    int stereo;
    float *sl, *sr;             /* scratch planes (the slot's source buffer) */
    int cap;                    /* scratch capacity in frames */
};

/* read cnt frames from file position pos into the scratch planes (through Shift) */
static void fetch(const struct src *s, int pos, int cnt)
{
    if (s->stereo)
        clip_read2(s->stream, s->sl, s->sr, cnt, pos, s->pad);
    else
        clip_read1(s->stream, s->sl, cnt, pos, 0, s->pad);
}

/* add m frames of a grain (first frame at file s0g, age a0, pitch rate r) into out, windowed */
static void grain_run(const struct src *s, double s0g, int a0, float r, int m, float *ol, float *or)
{
    while (m > 0) {
        int chunk = (int)((float)(s->cap - 3) / (r > 0.01f ? r : 0.01f));
        if (chunk > m)
            chunk = m;
        if (chunk < 1)
            chunk = 1;
        double x0 = s0g + (double)a0 * r;
        int i0 = floor_i(x0);
        int cnt = floor_i(x0 + (double)(chunk - 1) * r) - i0 + 2;
        if (cnt > s->cap)
            cnt = s->cap;
        fetch(s, i0, cnt);
        float f = (float)(x0 - i0);
        for (int k = 0; k < chunk; k++) {
            int j = (int)f;
            float t = f - (float)j;
            if (j > cnt - 2)
                j = cnt - 2;
            float w = window(a0 + k);
            ol[k] += w * (s->sl[j] + t * (s->sl[j + 1] - s->sl[j]));
            if (or) {
                const float *src = s->stereo ? s->sr : s->sl;
                or[k] += w * (src[j] + t * (src[j + 1] - src[j]));
            }
            f += r;
        }
        a0 += chunk;
        ol += chunk;
        if (or)
            or += chunk;
        m -= chunk;
    }
}

/* mono (left) samples of the file at x0 + k * step, k = 0..cnt-1, into dst (through the scratch) */
static void sample(const struct src *s, double x0, float step, int cnt, float *dst)
{
    int k = 0;
    while (k < cnt) {
        int left = cnt - k;
        int span = (int)((float)(s->cap - 3) / step);
        if (span < 1)
            span = 1;
        if (span > left)
            span = left;
        double xa = x0 + (double)k * step;
        int i0 = floor_i(xa);
        int len = floor_i(xa + (double)(span - 1) * step) - i0 + 2;
        if (len > s->cap)
            len = s->cap;
        fetch(s, i0, len);
        float f = (float)(xa - i0);
        for (int q = 0; q < span; q++) {
            int j = (int)f;
            if (j > len - 2)
                j = len - 2;
            float t = f - (float)j;
            dst[k + q] = s->sl[j] + t * (s->sl[j + 1] - s->sl[j]);
            f += step;
        }
        k += span;
    }
}

/* best start for a new grain near p: matches the old grain's continuation (first frame at cont, pitch rate r) */
static double search(const struct src *s, double p, double cont, float r)
{
    float tgt[TGT], cand[TGT + 2 * SEARCH / DEC + 1];
    sample(s, cont, r * DEC, TGT, tgt);
    sample(s, p - SEARCH * r, r * DEC, TGT + 2 * SEARCH / DEC + 1, cand);
    int best = SEARCH / DEC;
    float best_score = -1e30f;
    for (int lag = 0; lag <= 2 * SEARCH / DEC; lag++) {
        float c = 0.0f, e = 1e-9f;
        for (int k = 0; k < TGT; k++) {
            float v = cand[lag + k];
            c += tgt[k] * v;
            e += v * v;
        }
        float score = c > 0.0f ? c * c / e : -c * c / e;
        if (score > best_score) {
            best_score = score;
            best = lag;
        }
    }
    double coarse = p + (double)(best * DEC - SEARCH) * r;
    /* refine to the frame: full-rate template (first FINE frames) against +-REFINE x DEC frames */
    float t2[FINE], c2[FINE + 2 * REFINE * DEC + 1];
    sample(s, cont, r, FINE, t2);
    sample(s, coarse - REFINE * DEC * r, r, FINE + 2 * REFINE * DEC + 1, c2);
    int bl = REFINE * DEC;
    best_score = -1e30f;
    for (int lag = 0; lag <= 2 * REFINE * DEC; lag++) {
        float c = 0.0f, e = 1e-9f;
        for (int k = 0; k < FINE; k++) {
            float v = c2[lag + k];
            c += t2[k] * v;
            e += v * v;
        }
        float score = c > 0.0f ? c * c / e : -c * c / e;
        if (score > best_score) {
            best_score = score;
            bl = lag;
        }
    }
    return coarse + (double)(bl - REFINE * DEC) * r;
}

/* the clip pad's mode decides; 1: smooth */
static int smooth(const uint8_t *pad)
{
    if (!pad || pad[PAD_SLICED] || !pad[PAD_SYNCED])
        return 0;
    unsigned mode = pad_setting(pad, P_SMODE);
    if (mode == 1)
        return 0;
    if (mode == 2)
        return 1;
    int st = (int)pad_setting(pad, P_STRETCH);
    return st != 0 && st >= -100 && st <= 100;
}

/* replaces the call of 0x080662e4 at 0x08066622 (same arguments) */
/* the slot's grain state; 0 if the slot is not one of the 16 grid pads' 4 */
static volatile struct grains *slot_grains(const uint8_t *pad, const float *frac)
{
    const uint8_t *slot = (const uint8_t *)frac - SLOT_FRAC;
    int si = (int)(slot - pad - SLOT0) / SLOT_SIZE;
    uint32_t id = *(const uint32_t *)(pad + PAD_ID);
    unsigned row = (id >> 8) & 0xff, col = id & 0xff;
    if (si < 0 || si > 3 || row > 3 || col > 3)
        return 0;
    return &GRAINS[(row * 4 + col) * 4 + si];
}

static int running(volatile const struct grains *g, uint32_t now)
{
    return g->magic == GMAGIC && ((now - (g->has_old >> 16)) & 0xffffu) < GAP16;
}

int clip_render(void *pad_, int unused, int64_t pos64, float rate, int n, int *consumed, float *frac, void *srcbuf,
                void *outbuf, void **result)
{
    const uint8_t *pad = pad_;
    if (!(*(volatile uint32_t *)0xe0001000u & 1u)) {     /* DWT cycle counter on (TRCENA, unlock, CYCCNTENA) */
        *(volatile uint32_t *)0xe000edfcu |= 1u << 24;
        *(volatile uint32_t *)0xe0001fb0u = 0xc5acce55u;
        *(volatile uint32_t *)0xe0001000u |= 1u;
    }
    volatile struct grains *g = pad ? slot_grains(pad, frac) : 0;
    uint32_t now = now16();
    /* Auto stays smooth while the slot keeps playing smoothly (no switch to the stock read when Stretch crosses 0) */
    int latched = g && running(g, now) && pad[PAD_SYNCED] && !pad[PAD_SLICED] && pad_setting(pad, P_SMODE) == 0;
    if (!smooth(pad) && !latched)
        return fw_slot_read(pad_, unused, pos64, rate, n, consumed, frac, srcbuf, outbuf, result);
    void *stream = *(void *const *)(pad + PAD_STREAM);
    int total = fw_frames(stream);
    int pos = (int)pos64;
    if (total + 0xff < pos)
        return 0;
    float seglen = *(const float *)(pad + PAD_SEGLEN), unit = *(const float *)(pad + PAD_UNITOUT);
    if (!(unit > 1.0f) || !(seglen > 1.0f) || !(rate > 0.0f) || n <= 0)
        return fw_slot_read(pad_, unused, pos64, rate, n, consumed, frac, srcbuf, outbuf, result);
    double c = (double)seglen * clip_stretch_speed(pad) / unit;     /* file frames per output frame */

    if (!g)
        return fw_slot_read(pad_, unused, pos64, rate, n, consumed, frac, srcbuf, outbuf, result);

    struct src s;
    s.stream = stream;
    s.pad = pad;
    s.stereo = fw_stereo(stream);
    s.cap = *(const int32_t *)srcbuf;                   /* buffer +0: capacity in frames */
    if (s.stereo)
        fw_buf_stereo(srcbuf, &s.sl, &s.sr);
    else
        s.sl = s.sr = fw_buf_mono(srcbuf);
    if (s.cap < 8)
        return fw_slot_read(pad_, unused, pos64, rate, n, consumed, frac, srcbuf, outbuf, result);

    float *ol, *or;
    if (s.stereo) {
        fw_buf_stereo(outbuf, &ol, &or);
    } else {
        ol = fw_buf_mono(outbuf);
        or = 0;
    }
    for (int k = 0; k < n; k++) {
        ol[k] = 0.0f;
        if (or)
            or[k] = 0.0f;
    }

    double p = (double)pos + *frac;                     /* analysis position */
    double ex = g->expect, dp = p - ex;
    /* A fresh start (the slot had stopped) or a jump to the clip's start (retrigger, loop end): one grain at full
       weight, so attacks stay sharp. Any other jump while playing (the next Sync segment's position after Stretch was
       turned, Shift, ...): the running grains play on and the next grain (<= HOP frames later) is searched near the new
       position - an ordinary WSOLA splice instead of a hard cut. */
    int jump = dp > 1.0 || dp < -1.0;
    if (!running(g, now) || (jump && p < (double)HOP * rate)) {
        g->magic = GMAGIC;
        g->age = HOP;
        g->s_new = p - (double)HOP * rate;              /* centred: its frame for "now" is p */
        g->has_old = 0;
    }
    int t = 0;
    while (t < n) {
        int age = g->age;
        if (age >= HOP) {                               /* start the next grain */
            double s_cur = g->s_new;
            double cont = s_cur + (double)age * rate;   /* the current grain's next frame */
            double ns = p > 2.0 * SEARCH ? search(&s, p, cont, rate) : p;
            g->s_old = s_cur;
            g->has_old |= 1u;
            g->s_new = ns;
            g->age = age = 0;
        }
        int m = HOP - age;
        if (m > n - t)
            m = n - t;
        if (g->has_old & 1u)
            grain_run(&s, g->s_old, age + HOP, rate, m, ol + t, or ? or + t : 0);
        grain_run(&s, g->s_new, age, rate, m, ol + t, or ? or + t : 0);
        g->age = age + m;
        p += (double)m * c;
        t += m;
    }
    int ip = floor_i(p);
    *consumed = ip - pos;
    *frac = (float)(p - ip);
    g->expect = p;
    g->has_old = (g->has_old & 1u) | (now << 16);
    *result = outbuf;
    return 1;
}
