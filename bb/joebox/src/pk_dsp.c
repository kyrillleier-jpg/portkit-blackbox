/*
 * portkit DSP in flash bank 2 (JOEBOX 1 build, see pk.h): the master distortion, the WSOLA time stretch and the FX3
 * reverb. From bb/src (the 3.1.n build) unchanged in substance; only the interfaces are bank-2 shaped: no calls into
 * bank 1, settings and readers come in through pk.h's structures. Stock firmware calls (fixed addresses) are fine.
 */
#include "pk.h"
#include "pk_ids.h"                                  /* bb/joebox/ids.py */

#pragma GCC optimize("O2", "no-tree-loop-distribute-patterns")

typedef void (*core_fn)(float *state, const float *in, float *l, float *r, int n);
typedef float *(*mono_fn)(void *buf);
#define fw_plate_core ((core_fn)FN(0x08074f50))
typedef int (*frames_fn)(void *buf);
typedef void (*chans_fn)(void *buf, float **l, float **r);
#define fw_buf_frames ((frames_fn)FN(0x0804d8e8))
#define fw_stereo     ((chans_fn)FN(0x0804d9c0))     /* zero-fills a silent buffer, makes it stereo; L, R */

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

/* ============================================ loop fade (clips) ============================================ */
static inline __attribute__((always_inline)) float qsin(float t)  /* sin(pi / 2 t), 0 <= t <= 1 */
{
    float t2 = t * t;
    return t * (1.5707963f + t2 * (-0.6459641f + t2 * 0.0751678f));
}

static void fade_zone(float *l, float *r, int n, int pos, int a, int b, int out, float inv)
{
    int lo = a > pos ? a - pos : 0, hi = b < pos + n ? b - pos : n;
    for (int i = lo; i < hi; i++) {
        int d = out ? b - 1 - (pos + i) : pos + i - a;
        float g = qsin((float)d * inv);
        l[i] *= g;
        if (r && r != l)
            r[i] *= g;
    }
}

void pk_loop_fade(float *l, float *r, int n, int pos, int f, int end, int seam)
{
    float inv = 1.0f / (float)f;
    if (pos < f)
        fade_zone(l, r, n, pos, 0, f, 0, inv);
    if (pos + n > end - f)
        fade_zone(l, r, n, pos, end - f, end, 1, inv);
    if (seam > f && seam < end - f) {
        fade_zone(l, r, n, pos, seam - f, seam, 1, inv);
        fade_zone(l, r, n, pos, seam, seam + f, 0, inv);
    }
}

/* ============================================ distortion ============================================ */
enum { D_OFF, D_SOFT, D_HARD, D_FOLD, D_TUBE, D_TYPES };

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
#define DS ((struct dist *)PK_DIST_STATE)
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


static void dist_bus(uint8_t *bus0, const int *set)
{
    struct dist *d = DS;
    int type = set[0], n = fw_buf_frames(bus0);
    if (n <= 0 || n > 512)
        return;
    float *l = 0, *r = 0;
    fw_stereo(bus0, &l, &r);
    if (!l || !r)
        return;
    float drive = exp2_fast((float)set[1] * (0.001f / 6.0206f));
    float mix = (float)set[3] * 0.001f;
    mix = mix < 0.0f ? 0.0f : mix > 1.0f ? 1.0f : mix;
    float level = exp2_fast((float)set[4] * (0.001f / 6.0206f));
    int tone = set[2], tone_on = tone < 990;
    float tone_a = 1.0f;
    if (tone_on) {
        float hz = 200.0f * exp2_fast((float)(tone < 0 ? 0 : tone) * 0.001f * 6.643856f);   /* 200 Hz .. 20 kHz */
        float w = 6.2831853f * hz / 48000.0f;
        tone_a = w / (1.0f + w);
    }
    if (d->magic != DMAGIC) {
        uint32_t *w = (uint32_t *)d;
        for (unsigned k = 0; k < sizeof *d / 4; k++)
            w[k] = 0;
        d->drive = drive;
        d->mix = mix;
        d->level = level;
        d->magic = DMAGIC;
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

/* ============================================ WSOLA ============================================ */
#define HOP     PK_HOP          /* output frames between grain starts; grain = 2 x HOP */
#define SEARCH  256             /* +- file frames the grain start may move */
#define DEC     8               /* decimation of the coarse search */
#define REFINE  4               /* +- frames around the coarse best */
#define TGT     (HOP / DEC)     /* coarse template length */
#define FINE    64              /* fine template length (frames) */

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

static int floor_i(double x)
{
    int i = (int)x;
    return (double)i > x ? i - 1 : i;
}

/* read cnt frames from file position pos into the scratch planes (through Shift: bank 1's readers) */
static void fetch(const struct src *s, int pos, int cnt)
{
    if (s->stereo)
        s->read2(s->stream, s->sl, s->sr, cnt, pos, s->pad);
    else
        s->read1(s->stream, s->sl, cnt, pos, 0, s->pad);
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


static int running(volatile const struct grains *g, uint32_t now)
{
    return g->magic == PK_GMAGIC && ((now - (g->has_old >> 16)) & 0xffffu) < PK_GAP16;
}

void pk_wsola(const struct src *s_, volatile struct grains *g, int pos, float rate, double c, int n, float *ol,
              float *or, int *consumed, float *frac, uint32_t now)
{
    const struct src s = *s_;
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
        g->magic = PK_GMAGIC;
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
}

/* ============================================ FX3 reverb ============================================ */
struct pk_rvb {                 /* the reverb's settings, all 0..1 (type as index) */
    unsigned type;
    float size, diff, bass, xover, rate, depth, early, width, hicut, locut, level;
};

#define FS 29800.0f
enum { ALG_PLATE, ALG_ROOM, ALG_HALL, ALG_CHAMBER, ALGS };


/* sine of a 32-bit phase (one cycle = 2^32), parabolic, error < 0.1 % after the correction */
static inline __attribute__((always_inline)) float sin32(uint32_t ph)
{
    float x = (float)(int32_t)ph * (1.0f / 2147483648.0f);           /* -1 .. 1 = -pi .. pi */
    float y = 4.0f * x * (1.0f - (x < 0.0f ? -x : x));
    return y * (0.775f + 0.225f * (y < 0.0f ? -y : y));
}

/* one-pole coefficient for a corner frequency at FS */
static float onepole(float hz)
{
    float w = 6.2831853f * hz / FS;
    return w / (1.0f + w);
}

static float clamp01(float x)
{
    return x < 0.0f ? 0.0f : x > 1.0f ? 1.0f : x;
}

/* the plate's buffers: state word index, floats */
static const struct { uint8_t word; uint16_t len; } bufs[12] = {
    {0x08, 512}, {0x0b, 512}, {0x0e, 512}, {0x11, 512}, {0x14, 1024}, {0x19, 1024},
    {0x1e, 8192}, {0x21, 8192}, {0x25, 8192}, {0x27, 8192}, {0x29, 8192}, {0x2b, 8192},
};
#define BUF(state, i) (*(float **)((uint32_t *)(state) + bufs[i].word))

/* settings of the cell, all 0..1 (Type as index) */

/* --- state (SRAM4: copied in / out once per block) ------------------------------------------------------------------ */
struct rstate {
    uint32_t magic, alg;
    /* hall / chamber */
    uint32_t w8k, w4k, w1k, w512;      /* write positions of the 8192 / 4096 / 1024 / 512 rings */
    float lp_a[2], lp_b[2];            /* crossover low parts / treble low-pass per branch: [0] crossover, [1] treble */
    float fb_a, fb_b;                  /* branch ends (feed the other branch) */
    float hc, lc;                      /* input hi-cut / lo-cut states */
    float size;                        /* slewed size factor */
    uint32_t lfo, wander;              /* modulation phases */
    /* room */
    uint32_t er_pos;
    uint16_t in_ap_pos[4], line_pos[8];
    uint8_t line_ap_pos[8];
    float rlp[8];
    uint32_t rlfo[4];
};
#define RS2 ((volatile struct rstate *)PK_RVB_STATE)
_Static_assert(sizeof(struct rstate) <= 0x100, "reverb state: SRAM4 0x38000f00-0x38000fff");
#define RMAGIC 0x52564231u             /* "RVB1" */
_Static_assert(sizeof(struct rstate) <= 0x100, "reverb state fits its patch RAM slot");

static void clear(float *state, volatile struct rstate *RS)
{
    for (int i = 0; i < 12; i++) {
        float *b = BUF(state, i);
        if (b)
            for (int k = 0; k < bufs[i].len; k++)
                b[k] = 0.0f;
    }
    volatile uint32_t *w = (volatile uint32_t *)RS;
    for (unsigned k = 0; k < sizeof(struct rstate) / 4; k++)
        w[k] = 0;
    RS->size = 1.0f;
    for (int k = 0; k < 4; k++)
        RS->rlfo[k] = (uint32_t)k * 0x40000000u;
}

/* Make-up gains: noise in, Decay 40 / 70 %, steady-state RMS against the stock plate (tests/test_reverb.py): Hall /
   Chamber were ~3.2 dB, Room ~9 dB quieter. */
#define TANK_GAIN 1.45f
#define ROOM_GAIN 2.8f

/* --- Hall / Chamber -------------------------------------------------------------------------------------------------- */
/* Lengths at 29.8 kHz (Dattorro's figures at 29.761 kHz). Rings: input diffusers in buffers 0-3 (512), modulated
   allpasses in 4-5 (1024), the four delays in 7-10 (8192), the second allpasses in 11 (two halves of 4096), early
   reflections in 6 (8192). */
struct tank {
    float in_ap[4];                    /* input diffuser lengths */
    float map_a, map_b;                /* modulated allpasses */
    float d1, ap2, d2;                 /* branch A after its modulated allpass */
    float d3, ap4, d4;                 /* branch B */
    float rt_min, rt_log2_range;       /* RT60 = rt_min x 2 ^ (rt_log2_range x decay) */
    float er_scale;
};
/* Hall: Dattorro's tank, RT60 0.3 .. 12 s; Chamber: shorter, denser lines, RT60 0.2 .. 5 s */
static const struct tank hall = {{142, 107, 379, 277}, 672, 908, 4453, 1800, 3720, 4217, 2656, 3163, 0.3f, 5.3219f, 1.0f};
static const struct tank chamber = {{142, 107, 379, 277}, 520, 700, 2300, 1100, 1900, 2150, 1500, 1650, 0.2f, 4.6439f,
                                    0.6f};

/* output taps (Dattorro's, on the Hall's lines; other tanks scale them by their line lengths): line, distance, sign */
enum { T_D1, T_AP2, T_D2, T_D3, T_AP4, T_D4 };
struct tap { uint8_t line; uint16_t dist; int8_t sign; };
static const struct tap taps_l[7] = {{T_D3, 266, 1}, {T_D3, 2974, 1}, {T_AP4, 1913, -1}, {T_D4, 1996, 1},
                                     {T_D1, 1990, -1}, {T_AP2, 187, -1}, {T_D2, 1066, -1}};
static const struct tap taps_r[7] = {{T_D1, 353, 1}, {T_D1, 3627, 1}, {T_AP2, 1228, -1}, {T_D2, 2673, 1},
                                     {T_D3, 2111, -1}, {T_AP4, 335, -1}, {T_D4, 121, -1}};
/* early reflections: 8 taps per side (at size 1), alternating signs, falling */
static const uint16_t er_l[8] = {211, 389, 557, 761, 997, 1231, 1499, 1811};
static const uint16_t er_r[8] = {263, 431, 619, 829, 1061, 1319, 1597, 1907};
static const float er_g[8] = {0.62f, -0.53f, 0.46f, -0.4f, 0.34f, -0.29f, 0.24f, -0.2f};

static inline __attribute__((always_inline)) float ring(const float *b, unsigned mask, uint32_t w, float dist)
{
    int id = (int)dist;
    float f = dist - (float)id;
    float a = b[(w - (uint32_t)id) & mask], c = b[(w - (uint32_t)id - 1u) & mask];
    return a + f * (c - a);
}

static void tank_run(volatile struct rstate *RS, float *state, const struct tank *tk, const struct pk_rvb *st,
                     const float *in, float *outl, float *outr, int n)
{
    float *ap_in[4] = {BUF(state, 0), BUF(state, 1), BUF(state, 2), BUF(state, 3)};
    float *map_a = BUF(state, 4), *map_b = BUF(state, 5), *er = BUF(state, 6);
    float *d1 = BUF(state, 7), *d2 = BUF(state, 8), *d3 = BUF(state, 9), *d4 = BUF(state, 10);
    float *ap2 = BUF(state, 11), *ap4 = BUF(state, 11) + 4096;

    float decay = clamp01(state[0] * (1.0f / 0.93f)), damp = clamp01(state[1]);
    /* size x 0.5 .. x 1.5, slewed towards the setting */
    float target = 0.5f + st->size, sz = RS->size;
    sz += 0.05f * (target - sz);
    if (!(sz > 0.4f) || sz > 1.6f)
        sz = target;
    float rt = tk->rt_min * exp2_fast(tk->rt_log2_range * decay);
    float bass_mult = exp2_fast((st->bass - 0.5f) * 2.0f);                    /* x 0.5 .. x 2 */
    float xo = onepole(100.0f * exp2_fast(st->xover * 4.3219f));              /* 100 .. 2000 Hz */
    float treble = 1.0f - 0.92f * damp;                                         /* treble low-pass coefficient */
    float hc = onepole(1000.0f * exp2_fast(st->hicut * 3.8074f));              /* 1 .. 14 kHz */
    float lc = onepole(20.0f * exp2_fast(st->locut * 4.6439f));                /* 20 .. 500 Hz */
    float g_in1 = 0.75f * st->diff, g_in2 = 0.625f * st->diff;                  /* input diffusion */
    float g_dec1 = -0.7f * (0.4f + 0.6f * st->diff), g_dec2 = 0.5f;             /* tank diffusion */
    float depth = 24.0f * st->depth;                                            /* samples */
    uint32_t lfo_inc = (uint32_t)(4294967296.0f / FS * (0.1f * exp2_fast(st->rate * 5.6439f)));  /* 0.1 .. 5 Hz */
    float er_lvl = 0.6f * st->early, side = st->width;

    float la = (tk->map_a + tk->d1 + tk->ap2 + tk->d2) * sz, lb = (tk->map_b + tk->d3 + tk->ap4 + tk->d4) * sz;
    float k_rt = -3.0f * 3.3219281f / (rt * FS);
    float gm_a = exp2_fast(k_rt * la), gm_b = exp2_fast(k_rt * lb);
    float gb_a = exp2_fast(k_rt * la / bass_mult), gb_b = exp2_fast(k_rt * lb / bass_mult);

    /* modulated allpasses live in 1024-float rings: length x size + 2 x depth must stay below 1023 */
    float l_map_a = tk->map_a * (sz < 1.4f ? sz : 1.4f), l_map_b = tk->map_b * (sz < 1.0f ? sz : 1.0f);
    float l_d1 = tk->d1 * sz, l_ap2 = tk->ap2 * sz, l_d2 = tk->d2 * sz;
    float l_d3 = tk->d3 * sz, l_ap4 = tk->ap4 * sz, l_d4 = tk->d4 * sz;
    float l_er = tk->er_scale * sz;
    const float tap_scale[6] = {tk->d1 / hall.d1 * sz, tk->ap2 / hall.ap2 * sz, tk->d2 / hall.d2 * sz,
                                tk->d3 / hall.d3 * sz, tk->ap4 / hall.ap4 * sz, tk->d4 / hall.d4 * sz};

    /* tap distances in samples, once per block */
    uint32_t erl[8], err[8], tl[7], tr[7];
    for (int t = 0; t < 8; t++) {
        erl[t] = (uint32_t)(er_l[t] * l_er);
        err[t] = (uint32_t)(er_r[t] * l_er);
    }
    for (int t = 0; t < 7; t++) {
        tl[t] = (uint32_t)(taps_l[t].dist * tap_scale[taps_l[t].line]);
        tr[t] = (uint32_t)(taps_r[t].dist * tap_scale[taps_r[t].line]);
    }
    uint32_t w8 = RS->w8k, w4 = RS->w4k, w1 = RS->w1k, w5 = RS->w512;
    float xa = RS->lp_a[0], ta = RS->lp_a[1], xb = RS->lp_b[0], tb = RS->lp_b[1];
    float fa = RS->fb_a, fb = RS->fb_b, hcs = RS->hc, lcs = RS->lc;
    uint32_t lfo = RS->lfo, wan = RS->wander;
    /* the LFO (<= 5 Hz) moves ~1 % of a cycle per block: its values at the block's ends, linear in between (no sines
       per sample); the phases advance exactly as per sample */
    uint32_t wan_inc = lfo_inc / 7u + 1u;
    uint32_t lfo_e = lfo + (uint32_t)n * lfo_inc, wan_e = wan + (uint32_t)n * wan_inc;
    float m1 = 0.75f * sin32(lfo) + 0.25f * sin32(wan);
    float m2 = 0.75f * sin32(lfo + 0x40000000u) + 0.25f * sin32(wan + 0x9e3779b9u);
    float inv_n = n > 0 ? 1.0f / (float)n : 0.0f;
    float dm1 = (0.75f * sin32(lfo_e) + 0.25f * sin32(wan_e) - m1) * inv_n;
    float dm2 = (0.75f * sin32(lfo_e + 0x40000000u) + 0.25f * sin32(wan_e + 0x9e3779b9u) - m2) * inv_n;
    lfo = lfo_e;
    wan = wan_e;

    for (int i = 0; i < n; i++) {
        /* input: band limits */
        float x = in[i];
        hcs += hc * (x - hcs);
        lcs += lc * (hcs - lcs);
        x = hcs - lcs;
        /* early reflections */
        er[w8 & 8191] = x;
        float el = 0.0f, erv = 0.0f;
        for (int t = 0; t < 8; t++) {
            el += er_g[t] * er[(w8 - erl[t]) & 8191];
            erv += er_g[t] * er[(w8 - err[t]) & 8191];
        }
        /* input diffusers */
        float d = x;
        for (int k = 0; k < 4; k++) {
            float *b = ap_in[k];
            float y = b[(w5 - (uint32_t)tk->in_ap[k]) & 511];
            float g = k < 2 ? g_in1 : g_in2;
            float v = d - g * y;
            b[w5 & 511] = v;
            d = y + g * v;
        }
        /* modulation: two quadrature sines + a slow wander, linear across the block (set up before the loop) */
        m1 += dm1;
        m2 += dm2;

        /* branch A */
        float a = d + fb;
        {
            float y = ring(map_a, 1023, w1, l_map_a + depth * (1.0f + m1));
            float v = a - g_dec1 * y;
            map_a[w1 & 1023] = v;
            a = y + g_dec1 * v;
        }
        d1[w8 & 8191] = a;
        a = ring(d1, 8191, w8, l_d1);
        xa += xo * (a - xa);
        a = xa * gb_a + (a - xa) * gm_a;            /* bass and mid decay */
        ta += treble * (a - ta);
        a = ta;
        {
            float y = ring(ap2, 4095, w4, l_ap2);
            float v = a + g_dec2 * y;
            ap2[w4 & 4095] = v;
            a = y - g_dec2 * v;
        }
        d2[w8 & 8191] = a;
        float end_a = ring(d2, 8191, w8, l_d2);

        /* branch B */
        float b = d + fa;
        {
            float y = ring(map_b, 1023, w1, l_map_b + depth * (1.0f + m2));
            float v = b - g_dec1 * y;
            map_b[w1 & 1023] = v;
            b = y + g_dec1 * v;
        }
        d3[w8 & 8191] = b;
        b = ring(d3, 8191, w8, l_d3);
        xb += xo * (b - xb);
        b = xb * gb_b + (b - xb) * gm_b;
        tb += treble * (b - tb);
        b = tb;
        {
            float y = ring(ap4, 4095, w4, l_ap4);
            float v = b + g_dec2 * y;
            ap4[w4 & 4095] = v;
            b = y - g_dec2 * v;
        }
        d4[w8 & 8191] = b;
        float end_b = ring(d4, 8191, w8, l_d4);

        fa = end_a;                                  /* A's end feeds B, B's end feeds A */
        fb = end_b;

        /* output taps */
        /* output taps (Dattorro's signs: + + - + - - -) */
        float sl = d3[(w8 - tl[0]) & 8191] + d3[(w8 - tl[1]) & 8191] - ap4[(w4 - tl[2]) & 4095]
                   + d4[(w8 - tl[3]) & 8191] - d1[(w8 - tl[4]) & 8191] - ap2[(w4 - tl[5]) & 4095]
                   - d2[(w8 - tl[6]) & 8191];
        float sr = d1[(w8 - tr[0]) & 8191] + d1[(w8 - tr[1]) & 8191] - ap2[(w4 - tr[2]) & 4095]
                   + d2[(w8 - tr[3]) & 8191] - d3[(w8 - tr[4]) & 8191] - ap4[(w4 - tr[5]) & 4095]
                   - d4[(w8 - tr[6]) & 8191];
        float mid = 0.5f * (sl + sr), sd = 0.5f * (sl - sr) * side;
        outl[i] = TANK_GAIN * (er_lvl * el + 0.6f * (mid + sd));
        outr[i] = TANK_GAIN * (er_lvl * erv + 0.6f * (mid - sd));

        w8++;
        w4++;
        w1++;
        w5++;
    }
    RS->w8k = w8;
    RS->w4k = w4;
    RS->w1k = w1;
    RS->w512 = w5;
    RS->lp_a[0] = xa;
    RS->lp_a[1] = ta;
    RS->lp_b[0] = xb;
    RS->lp_b[1] = tb;
    RS->fb_a = fa;
    RS->fb_b = fb;
    RS->hc = hcs;
    RS->lc = lcs;
    RS->size = sz;
    RS->lfo = lfo;
    RS->wander = wan;
}

/* --- Room (blackbox-mod's FDN, with the new controls) ----------------------------------------------------------------- */
#define ER_LEN 8192
static const uint16_t room_in_ap[4] = {142, 107, 379, 277};
static const uint16_t room_line[8] = {887, 1031, 1153, 1279, 1409, 1543, 1693, 1867};
static const uint8_t room_line_ap[8] = {37, 53, 67, 83, 97, 109, 113, 127};
static const uint16_t room_er_l[8] = {131, 197, 283, 359, 467, 571, 709, 853};
static const uint16_t room_er_r[8] = {157, 233, 311, 421, 523, 647, 779, 929};
static const float room_er_g[8] = {0.55f, -0.47f, 0.41f, -0.35f, 0.3f, -0.25f, 0.21f, -0.17f};
static const float out_sign_l[8] = {1, -1, 1, -1, 1, 1, -1, -1}, out_sign_r[8] = {1, 1, -1, -1, -1, 1, 1, -1};
static const uint8_t mod_line[4] = {0, 2, 5, 7};

static inline __attribute__((always_inline)) float allpass(float *buf, unsigned *pos, unsigned len, float g, float x)
{
    float y = buf[*pos], w = x + g * y;
    buf[*pos] = w;
    *pos = *pos + 1 >= len ? 0 : *pos + 1;
    return y - g * w;
}

static void room(volatile struct rstate *RS, float *state, const struct pk_rvb *st, const float *in, float *outl,
                 float *outr, int n)
{
    float *er = BUF(state, 6);
    float *in_ap[4] = {BUF(state, 0), BUF(state, 1), BUF(state, 2), BUF(state, 3)};
    float *line[8], *lap[8];
    for (int k = 0; k < 8; k++) {
        line[k] = BUF(state, 7 + k / 2) + (k & 1) * 4096;
        lap[k] = BUF(state, 4 + k / 4) + (k & 3) * 128;
    }
    float decay = clamp01(state[0] * (1.0f / 0.93f)), damp = clamp01(state[1]);
    float rt60 = 0.25f + 2.25f * decay, lpc = 0.9f - 0.7f * damp;
    float size = exp2_fast((st->size - 0.5f) * 2.0f);                         /* x 0.5 .. x 2 */
    float bass_mult = exp2_fast((st->bass - 0.5f) * 2.0f);
    float xo = onepole(100.0f * exp2_fast(st->xover * 4.3219f));
    float hc = onepole(1000.0f * exp2_fast(st->hicut * 3.8074f));
    float lc = onepole(20.0f * exp2_fast(st->locut * 4.6439f));
    float gd = 0.5f + 0.25f * st->diff;                                         /* input diffusion 0.5 .. 0.75 */
    float g[8], gb[8];
    unsigned len[8];
    for (int k = 0; k < 8; k++) {
        float l = (float)room_line[k] * size;
        len[k] = l < 64.0f ? 64u : l > 4000.0f ? 4000u : (unsigned)l;
        float kr = -3.0f * 3.321928f * (float)(len[k] + room_line_ap[k]) / (rt60 * FS);
        g[k] = exp2_fast(kr);
        gb[k] = exp2_fast(kr / bass_mult);
    }
    float depth = 20.0f * st->depth, er_lvl = 0.5f * st->early, side = st->width;
    uint32_t inc = (uint32_t)(4294967296.0f / FS * (0.1f * exp2_fast(st->rate * 5.6439f)));
    static const uint32_t spread[4] = {0u, 0x51eb851fu, 0x9e3779b9u, 0xc6a7ef9eu};

    unsigned erl[8], err[8];
    for (int t = 0; t < 8; t++) {
        erl[t] = (unsigned)(room_er_l[t] * size);
        err[t] = (unsigned)(room_er_r[t] * size);
    }
    unsigned ep = RS->er_pos, ip[4], lpos[8], apos[8];
    float lp[8], xl[8];
    uint32_t lfo0 = RS->rlfo[0];
    /* modulation offsets at the block's ends, linear in between (see tank_run) */
    float moff[4], dmoff[4];
    {
        uint32_t lfo_e = lfo0 + (uint32_t)n * inc;
        float inv_n = n > 0 ? 1.0f / (float)n : 0.0f;
        for (int m = 0; m < 4; m++) {
            moff[m] = depth * (1.0f + sin32(lfo0 + inc + spread[m]));
            dmoff[m] = (depth * (1.0f + sin32(lfo_e + inc + spread[m])) - moff[m]) * inv_n;
        }
        lfo0 = lfo_e;
    }
    float hcs = RS->hc, lcs = RS->lc;
    for (int k = 0; k < 4; k++)
        ip[k] = RS->in_ap_pos[k];
    for (int k = 0; k < 8; k++) {
        lpos[k] = RS->line_pos[k];
        if (lpos[k] >= len[k])
            lpos[k] = 0;
        apos[k] = RS->line_ap_pos[k];
        lp[k] = RS->rlp[k];
        xl[k] = 0.0f;
    }
    for (int i = 0; i < n; i++) {
        float x = in[i];
        hcs += hc * (x - hcs);
        lcs += lc * (hcs - lcs);
        x = hcs - lcs;
        er[ep] = x;
        float el = 0.0f, erv = 0.0f;
        for (int t = 0; t < 8; t++) {
            el += room_er_g[t] * er[(ep - erl[t]) & (ER_LEN - 1)];
            erv += room_er_g[t] * er[(ep - err[t]) & (ER_LEN - 1)];
        }
        ep = (ep + 1) & (ER_LEN - 1);
        float d = 0.5f * (el + erv);
        for (int k = 0; k < 4; k++)
            d = allpass(in_ap[k], &ip[k], room_in_ap[k], k < 2 ? gd : gd * 0.833f, d);

        float o[8], rd[8];
        for (int k = 0; k < 8; k++)
            rd[k] = line[k][lpos[k]];
        for (int m = 0; m < 4; m++) {
            int k = mod_line[m];
            float off = moff[m];
            moff[m] += dmoff[m];
            int io = (int)off;
            float fr = off - (float)io;
            unsigned a = lpos[k] + (unsigned)io, ln = len[k];
            a = a >= ln ? a - ln : a;
            unsigned b = a + 1 >= ln ? 0 : a + 1;
            rd[k] = line[k][a] + fr * (line[k][b] - line[k][a]);
        }
        for (int k = 0; k < 8; k++) {
            float v = allpass(lap[k], &apos[k], room_line_ap[k], 0.5f, rd[k]);
            lp[k] += lpc * (v - lp[k]);
            xl[k] += xo * (lp[k] - xl[k]);
            o[k] = xl[k] * gb[k] + (lp[k] - xl[k]) * g[k];
        }
        float a0 = o[0] + o[1], a1 = o[0] - o[1], a2 = o[2] + o[3], a3 = o[2] - o[3];
        float a4 = o[4] + o[5], a5 = o[4] - o[5], a6 = o[6] + o[7], a7 = o[6] - o[7];
        float b0 = a0 + a2, b1 = a1 + a3, b2 = a0 - a2, b3 = a1 - a3;
        float b4 = a4 + a6, b5 = a5 + a7, b6 = a4 - a6, b7 = a5 - a7;
        const float sc = 0.35355339f;
        float h[8] = {(b0 + b4) * sc, (b1 + b5) * sc, (b2 + b6) * sc, (b3 + b7) * sc,
                      (b0 - b4) * sc, (b1 - b5) * sc, (b2 - b6) * sc, (b3 - b7) * sc};
        float sl = 0.0f, sr = 0.0f;
        for (int k = 0; k < 8; k++) {
            line[k][lpos[k]] = d + h[k];
            lpos[k] = lpos[k] + 1 >= len[k] ? 0 : lpos[k] + 1;
            sl += out_sign_l[k] * o[k];
            sr += out_sign_r[k] * o[k];
        }
        float mid = 0.5f * (sl + sr), sd = 0.5f * (sl - sr) * side;
        outl[i] = ROOM_GAIN * (er_lvl * el + 0.3f * (mid + sd));
        outr[i] = ROOM_GAIN * (er_lvl * erv + 0.3f * (mid - sd));
    }
    RS->er_pos = ep;
    RS->hc = hcs;
    RS->lc = lcs;
    RS->rlfo[0] = lfo0;
    for (int k = 0; k < 4; k++)
        RS->in_ap_pos[k] = (uint16_t)ip[k];
    for (int k = 0; k < 8; k++) {
        RS->line_pos[k] = (uint16_t)lpos[k];
        RS->line_ap_pos[k] = (uint8_t)apos[k];
        RS->rlp[k] = lp[k];
    }
}

/* --- dispatch ------------------------------------------------------------------------------------------------------ */
/* Type switch clears the buffers, then the algorithm */
static void run(volatile struct rstate *RS, float *state, const struct pk_rvb *st, const float *in, float *outl,
                float *outr, int n)
{
    if (RS->magic != RMAGIC || RS->alg != st->type) {
        clear(state, RS);
        RS->alg = st->type;
        RS->magic = RMAGIC;
    }
    switch (st->type) {
    case ALG_ROOM:
        room(RS, state, st, in, outl, outr, n);
        break;
    case ALG_HALL:
        tank_run(RS, state, &hall, st, in, outl, outr, n);
        break;
    case ALG_CHAMBER:
        tank_run(RS, state, &chamber, st, in, outl, outr, n);
        break;
    default:
        fw_plate_core(state, in, outl, outr, n);
    }
    /* Level: -12 .. +12 dB (2 ^ (x x 4 - 2)), 0 dB at 500 */
    if (st->level != 0.5f) {
        float g = exp2_fast(st->level * 3.9863f - 1.9932f);
        for (int i = 0; i < n; i++) {
            outl[i] *= g;
            outr[i] *= g;
        }
    }
}


/* FX3: the accumulator (48 kHz) decimated to 29.8 kHz, pre-delay, the reverb, interpolated back onto bus 0 */
#define FS_IN  48000.0f
#define FS_RVB 29800.0f
#define MAXN   128
#define MAXM   (MAXN * 2 / 3 + 4)

static const uint32_t plate_tmpl[44] = {     /* the stock init 0x08074d1c's result, 0 at the buffer words */
    0x3f000000, 0x3a03126f, 0, 0, 0, 0, 0x3f7fdf3b, 0,
    0, 0x008e0000, 0x3f400000, 0, 0x006b0000, 0x3f400000, 0, 0x017b0000,
    0x3f200000, 0, 0x01150000, 0x3f200000, 0, 0x02a00000, 0x3f333333, 0,
    0x000232fe, 0, 0x038c0000, 0x3f333333, 0, 0x000232ef, 0, 0x07080000,
    0x3f000000, 0, 0x0a600000, 0x3f000000, 0x11650000, 0, 0x10790000, 0,
    0x0e880000, 0, 0x0c5b0000, 0,
};
static const uint8_t plate_word[12] = {8, 11, 14, 17, 20, 25, 30, 33, 37, 39, 41, 43};
static const uint8_t plate_kb[12] = {2, 2, 2, 2, 4, 4, 32, 32, 32, 32, 32, 32};

/* The D2 SRAM clocks (RCC_AHB2ENR SRAM1/2/3EN, bits 29..31) before ANY access to PK_D2_BUFS .. PK_D2_END, every time:
   a reset clears the RCC but not SRAM4, so FX3's magic outlives it - when only the first call switched them on, the
   first block after a warm reset (the bank 2 loader's restart, a watchdog reset) touched D2 SRAM unclocked and
   faulted, every boot: the JB1+pk boot loop of 2026-10-21. */
static void pk_d2_clocks(void)
{
    volatile uint32_t *ahb2enr = (volatile uint32_t *)0x580244dcu;
    if ((*ahb2enr & (7u << 29)) != (7u << 29)) {
        *ahb2enr |= 7u << 29;
        (void)*ahb2enr;
    }
}

static int fx3_run(uint8_t *bus0, int have, const int *set, float *sum_l, float *sum_r)
{
    volatile struct fx3 *f = (volatile struct fx3 *)PK_FX3_STATE;
    pk_d2_clocks();
    if (f->magic != PK_F3MAGIC) {                     /* first call: plate, cleared memory */
        uint32_t *stw = (uint32_t *)PK_PLATE;
        for (int k = 0; k < 44; k++)
            stw[k] = plate_tmpl[k];
        uint32_t at = PK_D2_BUFS;
        for (int i = 0; i < 12; i++) {
            stw[plate_word[i]] = at;
            at += plate_kb[i] * 1024u;
        }
        for (uint32_t *p = (uint32_t *)PK_D2_BUFS; p < (uint32_t *)PK_D2_END; p++)
            *p = 0;
        volatile uint32_t *fw = (volatile uint32_t *)f;
        for (unsigned k = 0; k < sizeof(struct fx3) / 4; k++)
            fw[k] = 0;
        ((volatile uint32_t *)PK_RVB_STATE)[0] = 0;   /* the reverb clears its own state on first use */
        f->magic = PK_F3MAGIC;
        return 0;
    }
    int n = fw_buf_frames(bus0);
    if (n <= 0 || n > MAXN)
        n = MAXN;
    for (int k = have; k < n; k++)
        PK_ACC_L[k] = PK_ACC_R[k] = 0.0f;
    float *ol = 0, *or_ = 0;
    fw_stereo(bus0, &ol, &or_);
    if (!ol)
        return 1;
    if (!or_)
        or_ = ol;
    struct pk_rvb rvb;
    unsigned t = (unsigned)set[0];
    rvb.type = t < ALGS ? t : ALG_PLATE;
    float sz = (float)set[4] * 0.001f, lv = (float)set[5] * 0.001f;
    rvb.size = sz < 0.0f ? 0.0f : sz > 1.0f ? 1.0f : sz;
    rvb.level = lv < 0.0f ? 0.0f : lv > 1.0f ? 1.0f : lv;
    rvb.diff = 0.7f;             /* not on the page (Tools pages hold 11 rows): the 3.1.n build's defaults */
    rvb.bass = 0.5f;
    rvb.xover = 0.4f;
    rvb.rate = 0.3f;
    rvb.depth = 0.4f;
    rvb.early = 0.3f;
    rvb.width = 1.0f;
    rvb.hicut = 0.8f;
    rvb.locut = 0.1f;
    float *st = (float *)PK_PLATE;
    st[0] = (float)set[1] * (0.001f * 0.93f);
    st[1] = (float)set[2] * 0.001f;
    int pre_d = (int)((float)set[3] * 0.001f * 12000.0f) + 256;
    pre_d = pre_d > PK_PRE_LEN - 2 ? PK_PRE_LEN - 2 : pre_d < 1 ? 1 : pre_d;

    const float r = FS_RVB / FS_IN, a = 0.6f;
    float tin[MAXM], tl[MAXM], tr[MAXM];
    float ph0 = f->ph, ph = ph0, l1 = f->lp1, l2 = f->lp2, px = f->px;
    uint32_t w = f->pre_w;
    int m = 0;
    for (int k = 0; k < n; k++) {
        float x = 0.5f * (PK_ACC_L[k] + PK_ACC_R[k]);
        l1 += a * (x - l1);
        l2 += a * (l1 - l2);
        float cur = l2;
        ph += r;
        if (ph >= 1.0f && m < MAXM) {
            ph -= 1.0f;
            float back = ph / r;
            float v = cur + (px - cur) * back;
            PK_PRE[w & (PK_PRE_LEN - 1)] = v;
            tin[m++] = PK_PRE[(w - (uint32_t)pre_d) & (PK_PRE_LEN - 1)];
            w++;
        }
        px = cur;
    }
    f->lp1 = l1;
    f->lp2 = l2;
    f->px = px;
    f->pre_w = w;
    if (m > 0)
        run(RS2, (float *)PK_PLATE, &rvb, tin, tl, tr, m);

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
        float yl = pl + (cl - pl) * ph, yr = pr + (cr - pr) * ph;
        ol[k] += yl;
        if (or_ != ol)
            or_[k] += yr;
        if (sum_l) {
            sum_l[k] += yl;
            sum_r[k] += yr;
        }
    }
    f->ph = ph;
    f->ol = cl;
    f->or_ = cr;
    f->pl = pl;
    f->pr = pr;
    return 1;
}

/* ============================================ FX sum, FX3 per block, FX3 sends ============================================ */
#define RUN_ON (30u * 48000u / MAXN)    /* blocks the tail runs on after the last input (~30 s) */

static void fx_sum_add(const uint8_t *bus, int n, int first)
{
    const float *l = 0, *r = 0;
    if (!bus[0x10]) {
        l = *(float *const *)(bus + 8);
        r = bus[0x11] ? *(float *const *)(bus + 0xc) : l;
    }
    for (int k = 0; k < n; k++) {
        float a = l ? l[k] : 0.0f, b = r ? r[k] : 0.0f;
        PK_FXSUM_L[k] = first ? a : PK_FXSUM_L[k] + a;
        PK_FXSUM_R[k] = first ? b : PK_FXSUM_R[k] + b;
    }
}

static void fx_block(uint8_t *bus0, uint8_t *bus_fx2, const int *set)
{
    int n = fw_buf_frames(bus0);
    n = n > 0 && n <= MAXN ? n : MAXN;
    fx_sum_add(bus_fx2 - 20, n, 1);                     /* bus 0xa: the bus array's entries are 20 bytes */
    fx_sum_add(bus_fx2, n, 0);
    uint32_t *sb = (uint32_t *)PK_FXSUM_BUF;
    sb[0] = MAXN;
    sb[1] = (uint32_t)n;
    sb[2] = (uint32_t)PK_FXSUM_L;
    sb[3] = (uint32_t)PK_FXSUM_R;
    sb[4] = 0x100;                                      /* silent 0, stereo 1 */
    volatile struct fx3 *f = PK_F3;
    if (f->magic != PK_F3MAGIC) {
        fx3_run(bus0, 0, set, 0, 0);                    /* sets up the memory (once) */
        f->idle = RUN_ON;
        return;
    }
    uint32_t have = f->acc_n;
    f->acc_n = 0;
    if (have == 0) {
        if (f->idle >= RUN_ON)
            return;                                     /* no input and the tail has run out */
        f->idle++;
    } else {
        f->idle = 0;
    }
    fx3_run(bus0, (int)have, set, PK_FXSUM_L, PK_FXSUM_R);
}

void pk_fx3_add(const uint8_t *scratch, float g)
{
    volatile struct fx3 *f = PK_F3;
    if (f->magic != PK_F3MAGIC || !scratch || scratch[0x10])
        return;
    pk_d2_clocks();                                     /* the accumulator is in D2 SRAM */
    int n = fw_buf_frames((void *)scratch);
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
            PK_ACC_L[k] += a;
            PK_ACC_R[k] += b;
        } else {
            PK_ACC_L[k] = a;
            PK_ACC_R[k] = b;
        }
    }
    if ((uint32_t)n > have)
        f->acc_n = (uint32_t)n;
}

/* ============================================ smooth clip render (WSOLA setup) ============================================ */
typedef int (*frames_s_fn)(void *stream);
typedef float *(*mono_fn2)(void *buf);
typedef int (*pair_fn)(void *buf, float **l, float **r);
#define fw_frames_s ((frames_s_fn)FN(0x080636f0))
#define fw_stream_stereo ((frames_s_fn)FN(0x08063790))
#define fw_buf_mono ((mono_fn2)FN(0x0804d934))
#define fw_buf_pair ((pair_fn)FN(0x0804da0c))

int pk_clip_render(void *pad_, int unused, int64_t pos64, float rate, int n, int *consumed, float *frac, void *srcbuf,
                   void *outbuf, void **result)
{
    (void)unused;
    const uint8_t *pad = pad_;
    if (!(*(volatile uint32_t *)0xe0001000u & 1u)) {     /* DWT cycle counter on */
        *(volatile uint32_t *)0xe000edfcu |= 1u << 24;
        *(volatile uint32_t *)0xe0001fb0u = 0xc5acce55u;
        *(volatile uint32_t *)0xe0001000u |= 1u;
    }
    void *stream = *(void *const *)(pad + 0x24);
    int pos = (int)pos64;
    if (fw_frames_s(stream) + 0xff < pos)
        return 0;
    volatile struct pk_wctx *w = PK_WCTX;
    struct src s;
    s.stream = stream;
    s.pad = pad;
    s.read1 = w->read1;
    s.read2 = w->read2;
    s.stereo = fw_stream_stereo(stream);
    s.cap = *(const int32_t *)srcbuf;
    if (s.stereo)
        fw_buf_pair(srcbuf, &s.sl, &s.sr);
    else
        s.sl = s.sr = fw_buf_mono(srcbuf);
    float *ol, *or = 0;
    if (s.stereo)
        fw_buf_pair(outbuf, &ol, &or);
    else
        ol = fw_buf_mono(outbuf);
    double c = (double)*(const float *)(pad + 0x1fc) * w->speed / *(const float *)(pad + 0x204);
    pk_wsola(&s, w->g, pos, rate, c, n, ol, or, consumed, frac, pk_now16());
    *result = outbuf;
    return 1;
}

/* ============================================ SSL-style bus compressor (model "SSL" in JOEBOX's list) ============== */
/* From the Bitbox micro (src/master.c ssl_run): feed-forward VCA design, stereo-linked peak detector in dB, 2 dB soft
   knee, gain reduction smoothed with the attack / release switch; Auto release = a fast (0.1 s) and a slow path
   (300 ms / 1.2 s), the deeper wins. Mix: parallel compression against the dry signal. Runs where JOEBOX runs its
   models (after Master FX, before the clipper). set = Thresh (mdB), Ratio, Attack, Release (list indexes), Gain (mdB),
   Mix (0..1000). */
static const float ssl_ratio[] = {2.0f, 4.0f, 10.0f};
static const float ssl_attack_s[] = {0.0001f, 0.0003f, 0.001f, 0.003f, 0.01f, 0.03f};
static const float ssl_release_s[] = {0.1f, 0.3f, 0.6f, 1.2f};
#define SSL_AUTO   4
#define SSL_KNEE   2.0f
struct sslst { uint32_t magic; float gf, gs; };
#define SST ((volatile struct sslst *)PK_SSL_STATE)
#define SMAGIC 0x53534c21u       /* "SSL!" */

static inline __attribute__((always_inline)) float log2_fast(float x)
{
    union { float f; uint32_t u; } v = {x};
    float e = (float)((int)(v.u >> 23) - 128);
    v.u = (v.u & 0x7fffffu) | 0x3f800000u;
    float m = v.f;
    return e + (-0.34484843f * m + 2.02466578f) * m - 0.67487759f;
}

static float coef48(float seconds)       /* one-pole e^(-1 / (t fs)) at 48 kHz, series (exact enough near 1) */
{
    float d = 1.0f / (seconds * 48000.0f);
    return 1.0f - d * (1.0f - d * (0.5f - d * (1.0f / 6.0f - d * (1.0f / 24.0f))));
}

static int pick(int v, int count, int def)
{
    return v >= 0 && v < count ? v : def;
}

static void ssl_run(float *l, float *r, int n, const int *set)
{
    volatile struct sslst *s = SST;
    if (s->magic != SMAGIC) {
        s->gf = s->gs = 0.0f;
        s->magic = SMAGIC;
    }
    if (n <= 0 || n > 512 || !l)
        return;
    if (r == l)
        r = 0;
    float mix = (float)set[5] * 0.001f;
    mix = mix < 0.0f ? 0.0f : mix > 1.0f ? 1.0f : mix;
    float *dl = PK_SSL_DRY_L, *dr = PK_SSL_DRY_R;
    if (mix < 1.0f)
        for (int k = 0; k < n; k++) {
            dl[k] = l[k];
            dr[k] = r ? r[k] : l[k];
        }
    float thr = (float)set[0] * 0.001f;
    float slope = 1.0f / ssl_ratio[pick(set[1], 3, 0)] - 1.0f;
    float makeup = (float)set[4] * 0.001f;
    int rel = pick(set[3], 5, SSL_AUTO);
    float aa = coef48(ssl_attack_s[pick(set[2], 6, 5)]);
    float ar = coef48(rel == SSL_AUTO ? 0.1f : ssl_release_s[rel]);
    float sa = coef48(0.3f), sr = coef48(1.2f);
    float gf = s->gf, gs = s->gs;
    for (int k = 0; k < n; k++) {
        float x = l[k] < 0.0f ? -l[k] : l[k];
        if (r) {
            float y = r[k] < 0.0f ? -r[k] : r[k];
            x = y > x ? y : x;
        }
        float over = (x > 1e-6f ? 6.0206f * log2_fast(x) : -120.0f) - thr;
        float gc;
        if (over <= -0.5f * SSL_KNEE)
            gc = 0.0f;
        else if (over < 0.5f * SSL_KNEE) {
            float t = over + 0.5f * SSL_KNEE;
            gc = slope * t * t * (0.5f / SSL_KNEE);
        } else
            gc = slope * over;
        gf = gc < gf ? aa * gf + (1.0f - aa) * gc : ar * gf + (1.0f - ar) * gc;
        float g = gf;
        if (rel == SSL_AUTO) {
            gs = gc < gs ? sa * gs + (1.0f - sa) * gc : sr * gs + (1.0f - sr) * gc;
            g = gs < gf ? gs : gf;
        }
        float lin = exp2_fast((g + makeup) * (1.0f / 6.0206f));
        l[k] *= lin;
        if (r)
            r[k] *= lin;
    }
    s->gf = gf;
    s->gs = gs;
    if (mix < 1.0f)
        for (int k = 0; k < n; k++) {
            l[k] = dl[k] + mix * (l[k] - dl[k]);
            if (r)
                r[k] = dr[k] + mix * (r[k] - dr[k]);
        }
}

/* ============================================ USB audio from the computer (Rec Input: USB) ========================== */
/* JOEBOX's usbdev.c (OTG_HS, device on the power jack) with build.py's USBIN_EDITS: endpoint 3, isochronous OUT,
   adaptive (the computer's clock), 2 x 24 bit at 48 kHz, 48 frames a packet (up to 49). The interrupt side is integer
   only (the USB interrupt must not touch the FPU, usbdev.c); the reader runs in the audio task. */
#define OTG(o)    (*(volatile uint32_t *)(0x40040000u + (o)))
#define DSTS_     OTG(0x808)
#define DOEPCTL3  OTG(0xb60)
#define DOEPTSIZ3 OTG(0xb70)
#define RXFIFO    OTG(0x1000)
#define EP_ENA    (1u << 31)
#define EP_DIS    (1u << 30)
#define EP_ODD    (1u << 29)
#define EP_EVEN   (1u << 28)
#define EP_SNAK   (1u << 27)
#define EP_CNAK   (1u << 26)
#define EP_ACTIVE (1u << 15)
#define EP_ISO    (1u << 18)
#define RD ((struct usbin_rd *)PK_USBIN_RD)
#define UR_TARGET 384u          /* frames kept between the computer and the recorder: 8 ms */

void pk_usbin_arm(void)
{
    DOEPTSIZ3 = (1u << 19) | USBIN_MAX;                 /* one packet, up to 294 bytes */
    DOEPCTL3 |= EP_ENA | EP_CNAK | (((DSTS_ >> 8) + 1u) & 1u ? EP_ODD : EP_EVEN);   /* for the next frame */
}

int pk_usbin_open(void)
{
    volatile struct usbin *u = PK_UI;
    u->write = 0;
    u->packets = 0;
    u->bad = 0;
    RD->magic = 0;                                      /* the reader starts over once enough has come in */
    RD->pos = 0;
    RD->integ = 0.0f;
    DOEPCTL3 = USBIN_MAX | EP_ACTIVE | EP_ISO;
    pk_usbin_arm();
    return 1;
}

void pk_usbin_close(void)
{
    if (DOEPCTL3 & EP_ENA)
        DOEPCTL3 |= EP_SNAK | EP_DIS;
    DOEPCTL3 &= ~EP_ACTIVE;
    RD->magic = 0;
}

void pk_usbin_rx(unsigned bytes)
{
    volatile struct usbin *u = PK_UI;
    uint8_t b[USBIN_MAX + 4];
    unsigned words = (bytes + 3u) / 4u;
    for (unsigned i = 0; i < words; i++) {              /* the whole packet comes out of the FIFO, always */
        uint32_t w = RXFIFO;
        if (i * 4u + 3u < sizeof b) {
            b[i * 4u] = (uint8_t)w;
            b[i * 4u + 1u] = (uint8_t)(w >> 8);
            b[i * 4u + 2u] = (uint8_t)(w >> 16);
            b[i * 4u + 3u] = (uint8_t)(w >> 24);
        }
    }
    if (bytes > USBIN_MAX || bytes % 6u) {
        u->bad++;
        return;
    }
    uint32_t wr = u->write, frames = bytes / 6u;
    int32_t *ring = PK_USBIN_RING;
    for (uint32_t f = 0; f < frames; f++) {
        const uint8_t *p = b + f * 6u;
        int32_t *dst = ring + ((wr + f) % USBIN_RING) * 2u;
        dst[0] = (int32_t)((uint32_t)p[0] << 8 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 24) >> 8;
        dst[1] = (int32_t)((uint32_t)p[3] << 8 | (uint32_t)p[4] << 16 | (uint32_t)p[5] << 24) >> 8;
    }
    u->write = wr + frames;
    u->packets++;
}

static float ur_at(const int32_t *ring, uint32_t frame, int ch)
{
    return (float)ring[(frame % USBIN_RING) * 2u + (uint32_t)ch] * (1.0f / 8388608.0f);
}

#define CYCCNT (*(volatile uint32_t *)0xe0001004u)    /* JOEBOX's cpu.c runs it (399 MHz): one block = ~1.07 M */
#define HALF_BLOCK 500000u

void pk_usbin_fill(int n)
{
    n = n > 0 && n <= 128 ? n : 128;
    struct usbin_rd *r = RD;
    uint32_t now = CYCCNT;
    if (r->magic == PK_URMAGIC && r->made_n == (uint32_t)n && now - r->made < HALF_BLOCK)
        return;                                         /* this block's already made (recorder and pad share it) */
    r->made = now;
    r->made_n = (uint32_t)n;
    volatile struct usbin *u = PK_UI;
    const int32_t *ring = PK_USBIN_RING;
    float *L = PK_USBIN_L, *R = PK_USBIN_R;
    uint32_t *sb = (uint32_t *)PK_USBIN_BUF;
    uint32_t w = u->write;
    sb[0] = 128;
    sb[1] = (uint32_t)n;
    sb[2] = (uint32_t)L;
    sb[3] = (uint32_t)R;
    sb[4] = 0x100;                                      /* silent 0, stereo 1 */
    if (r->magic != PK_URMAGIC) {
        /* start (again) only on fresh data: UR_TARGET frames since the stream opened or last ran dry */
        if (w - r->pos < UR_TARGET || w - r->pos > 0x80000000u) {
            sb[4] = 0x101;
            return;
        }
        r->magic = PK_URMAGIC;
        r->pos = w - UR_TARGET;
        r->frac = 0.0f;
        r->ratio = 1.0f;
        r->fill = (float)UR_TARGET;
        r->resyncs++;
    }
    uint32_t avail = w - r->pos;
    if (avail > USBIN_RING - 8u) {                      /* left behind (nobody read for a while): catch up */
        r->pos = w - UR_TARGET;
        r->frac = 0.0f;
        r->fill = (float)UR_TARGET;
        r->resyncs++;
        avail = UR_TARGET;
    }
    if (avail < (uint32_t)n + 8u) {                     /* the computer stopped (or fell far behind): silence */
        r->magic = 0;
        r->pos = w;                                     /* fresh data counts from here */
        r->underruns++;
        sb[4] = 0x101;
        return;
    }
    /* PI control of the read rate on the smoothed fill: P alone leaves +-200 frames at 0.1 % clock offset, the
       integral brings it back to UR_TARGET (tuned in a model of this loop; tests/test_jb.py runs +-0.1 %) */
    r->fill += 0.004f * ((float)avail - r->fill);       /* ~0.7 s of blocks */
    float e = r->fill - (float)UR_TARGET, in = r->integ + 2e-9f * e;
    in = in < -0.003f ? -0.003f : in > 0.003f ? 0.003f : in;
    r->integ = in;
    float ratio = 1.0f + 5e-6f * e + in;
    ratio = ratio < 0.997f ? 0.997f : ratio > 1.003f ? 1.003f : ratio;
    r->ratio = ratio;
    uint32_t pos = r->pos;
    float t = r->frac;
    for (int i = 0; i < n; i++) {                       /* cubic Hermite between frames pos and pos + 1 */
        for (int ch = 0; ch < 2; ch++) {
            float xm = ur_at(ring, pos - 1u, ch), x0 = ur_at(ring, pos, ch), x1 = ur_at(ring, pos + 1u, ch),
                  x2 = ur_at(ring, pos + 2u, ch);
            float c1 = 0.5f * (x1 - xm), c2 = xm - 2.5f * x0 + 2.0f * x1 - 0.5f * x2,
                  c3 = 0.5f * (x2 - xm) + 1.5f * (x0 - x1);
            float v = ((c3 * t + c2) * t + c1) * t + x0;
            (ch ? R : L)[i] = v;
        }
        t += ratio;
        while (t >= 1.0f) {
            t -= 1.0f;
            pos++;
        }
    }
    r->pos = pos;
    r->frac = t;
}

/* ============================================ entry points that read their own settings ============================
   (bank 1 only gates them on b2_live(): it is full; the settings store and its reader are stock's, callable from here) */
typedef int (*pk_setting_fn)(const void *store, unsigned id);
#define PK_SETTINGS ((const void *)(0x24020088u + 0x8c90u))
static void pk_settings(const uint16_t *ids, int n, int *set)
{
    for (int k = 0; k < n; k++)
        set[k] = ((pk_setting_fn)FN(0x08093e9c))(PK_SETTINGS, ids[k]);
}

void pk_dist_bus(uint8_t *bus0)
{
    static const uint16_t ids[5] = {P_D_TYPE, P_D_DRIVE, P_D_TONE, P_D_MIX, P_D_LEVEL};
    int set[5];
    pk_settings(ids, 5, set);
    if (set[0] <= 0 || set[0] >= 5) {
        *(volatile uint32_t *)PK_DIST_STATE = 0;      /* fresh state when switched on again */
        return;
    }
    if (!bus0[0x10])
        dist_bus(bus0, set);
}

void pk_fx_block(uint8_t *bus0, uint8_t *bus_fx2)
{
    static const uint16_t ids[6] = {P_R_TYPE, P_R_DECAY, P_R_DAMP, P_R_PREDLY, P_R_SIZE, P_R_LEVEL};
    int set[6];
    pk_settings(ids, 6, set);
    fx_block(bus0, bus_fx2, set);
}

void pk_ssl_run(float *l, float *r, int n)
{
    static const uint16_t ids[6] = {P_S_THRESH, P_S_RATIO, P_S_ATTACK, P_S_REL, P_S_GAIN, P_S_MIX};
    int set[6];
    pk_settings(ids, 6, set);
    ssl_run(l, r, n, set);
}

/* a pad's live input "USB" (JOEBOX insert.c add_input, via bank 1's usbin_add): this block of the computer's stream
   added into the pad's own mix; a mono pad gets the left channel (as JOEBOX does for In 1+2) */
void pk_usbin_add(float *l, float *r, int n)
{
    pk_usbin_fill(n);
    const uint32_t *sb = (const uint32_t *)PK_USBIN_BUF;
    if (((const uint8_t *)sb)[16])
        return;                                         /* silent */
    int m = (int)sb[1] < n ? (int)sb[1] : n;
    const float *a = PK_USBIN_L, *b = PK_USBIN_R;
    for (int i = 0; i < m; i++) {
        l[i] += a[i];
        if (r)
            r[i] += b[i];
    }
}

/* ============================================ FX3 send (bank 1 only gates it) ============================================ */
typedef float (*pk_curve_fn)(float x);
#define PK_APP_PADS (0x24020088u + 0x1840u)

static unsigned pk_pad_setting(const uint8_t *pad, unsigned param)
{
    if (!pad)
        return 0;
    uint32_t id = *(const uint32_t *)(pad + 0x18);
    unsigned row = (id >> 8) & 0xff, col = id & 0xff;
    if (row >= 4 || col >= 5)
        return 0;
    return (unsigned)((pk_setting_fn)FN(0x08093e9c))((const void *)(PK_APP_PADS + row * 0xf0u + col * 0x30u), param);
}

void pk_fx3_send(uint8_t *scratch, const uint8_t *pad)
{
    int v = (int)pk_pad_setting(pad, P_FX3SEND);
    if (v <= 0 || PK_F3->magic != PK_F3MAGIC)
        return;
    float g = ((pk_curve_fn)FN(0x08060930))((float)(v > 1000 ? 1000 : v) * 0.001f);
    if (g > 0.0f)
        pk_fx3_add(scratch, g);
}

/* ============================================ performance macros ============================================ */
#define MACRO_MS 30.0f          /* glide: short enough to feel instant, long enough not to click */
static const uint16_t macro_value[4] = {0xd71c, 0xd6b8, 0xd654, 0xd5f0};   /* mod5..mod8: object + 4 */
#define PADS_PANELS 0x2b58      /* JOEBOX solo.c: [0] velocity slider, [1] button panel */
#define PADS_POS    0x2b6c
static const uint16_t macro_btn[4] = {0x34, 0xd4, 0x174, 0x214};           /* MAC1..MAC4: top to bottom on the glass */
typedef void (*pk_select_fn)(void *button, int on);

static volatile struct pk_macro *macros(void)
{
    volatile struct pk_macro *m = PK_MACRO;
    if (m->magic != PK_MMAGIC) {                        /* every boot: all off (SRAM keeps old bytes over a reset) */
        for (int k = 0; k < 4; k++) {
            m->on[k] = 0;
            m->value[k] = 0.0f;
        }
        m->magic = PK_MMAGIC;
    }
    return m;
}

void pk_macro_tick(uint8_t *engine, float dt_ms)
{
    volatile struct pk_macro *m = macros();
    float step = dt_ms / MACRO_MS;
    for (int k = 0; k < 4; k++) {
        float v = m->value[k];
        v = m->on[k] ? (v + step > 1.0f ? 1.0f : v + step) : (v - step < 0.0f ? 0.0f : v - step);
        m->value[k] = v;
        *(volatile float *)(engine + macro_value[k]) = v;
    }
}

void pk_macro_lights(uint8_t *view)
{
    volatile struct pk_macro *m = macros();
    uint8_t *buttons = *(uint8_t **)(view + PADS_PANELS + 4);
    if (!buttons || *(int32_t *)(view + PADS_POS) != 0)
        return;
    for (int k = 0; k < 4; k++)
        ((pk_select_fn)FN(0x080a3e00))(buttons + macro_btn[k], m->on[k]);
}

void pk_macro_click(uint8_t *view, unsigned k)
{
    if (k >= 4)
        return;
    volatile struct pk_macro *m = macros();
    m->on[k] = !m->on[k];
    pk_macro_lights(view);
}

/* ============================================ Smooth stretch: does this slot want it (moved from bank 1) ============== */
#define PAD_SYNCED  0x1f5
#define PAD_SEGLEN  0x1fc
#define PAD_UNITOUT 0x204
#define PAD_SLICED  0x254
#define SLOT0       0x30
#define SLOT_SIZE   0x70
#define SLOT_FRAC   0x1c

int pk_smooth_decide(const uint8_t *pad, float *frac, const int32_t *srcbuf, float rate)
{
    if (!pad || pad[PAD_SLICED] || !pad[PAD_SYNCED] || !(rate > 0.0f) || !srcbuf || *srcbuf < 8)
        return 0;
    float seglen = *(const float *)(pad + PAD_SEGLEN), unit = *(const float *)(pad + PAD_UNITOUT);
    if (!(unit > 1.0f) || !(seglen > 1.0f))
        return 0;
    const uint8_t *slot = (const uint8_t *)frac - SLOT_FRAC;
    int si = (int)(slot - pad - SLOT0) / SLOT_SIZE;
    uint32_t id = *(const uint32_t *)(pad + 0x18);
    unsigned row = (id >> 8) & 0xff, col = id & 0xff;
    if (si < 0 || si > 3 || row > 3 || col > 3)
        return 0;
    volatile struct grains *g = &((volatile struct grains *)PK_GRAINS)[(row * 4 + col) * 4 + si];
    unsigned mode = pk_pad_setting(pad, P_SMODE);
    int want;
    if (mode == 1)
        want = 0;
    else if (mode == 2)
        want = 1;
    else {
        int st = (int)pk_pad_setting(pad, P_STRETCH);
        uint32_t now = pk_now16();
        /* Auto stays smooth while the slot keeps playing smoothly (no switch when Stretch crosses 0) */
        want = (st != 0 && st >= -100 && st <= 100)
            || (g->magic == PK_GMAGIC && ((now - (g->has_old >> 16)) & 0xffffu) < PK_GAP16);
    }
    if (!want)
        return 0;
    PK_WCTX->g = g;
    return 1;
}
