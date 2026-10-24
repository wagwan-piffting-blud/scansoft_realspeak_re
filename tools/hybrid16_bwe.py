"""Tom-specific bandwidth extension, trained on the REAL 3.4-8 kHz band found in SS / RS.

Envelope: a dilated Conv1d net maps tom8's 0-3.4 kHz log power spectrum (frames +-~0.3 s)
to the real band's 3.4-8 kHz log power spectrum. Trained only on frames whose 20 ms cells
were verified by hybrid16_extract.py. Recordings with index % 20 == 0 and the demo
recordings are held out.

Fine structure: full-wave rectified tom8 low band (harmonics stay on the pitch grid,
nothing is mirrored), whitened per frame, then shaped by the predicted envelope.

    python -I hybrid16_bwe.py train
    python -I hybrid16_bwe.py eval
"""
import json
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from scipy import signal as sg

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hybrid16_demo as HD  # noqa: E402

OUT = Path(r"C:\tmp\hybrid16")
NFFT, HOP = 512, 160
KX = int(HD.XOVER / (16000 / NFFT))          # bins 0..KX-1 are the input band
NY = NFFT // 2 + 1 - KX
CTX = 256                                     # training chunk, frames
DEV = "cuda"


class Net(nn.Module):
    def __init__(self, ch=192, drop=0.2):
        super().__init__()
        self.inp = nn.Conv1d(KX, ch, 1)
        self.blocks = nn.ModuleList()
        for d in (1, 2, 4, 8, 1, 2):
            self.blocks.append(nn.Sequential(nn.Conv1d(ch, ch, 5, padding=2 * d, dilation=d), nn.GELU(),
                                             nn.Dropout(drop), nn.Conv1d(ch, ch, 1)))
        self.out = nn.Conv1d(ch, NY, 1)

    def forward(self, x):
        h = self.inp(x)
        for b in self.blocks:
            h = h + b(h)
        return self.out(h)


def logpow(x):
    """x (N,) float32 at 16 kHz -> (frames, bins) log10 power, frame t centred on t*HOP."""
    xt = torch.from_numpy(np.ascontiguousarray(x, np.float32)).to(DEV)
    w = torch.hann_window(NFFT, device=DEV)
    S = torch.stft(xt, NFFT, HOP, window=w, center=True, return_complex=True)
    return torch.log10(S.abs() ** 2 + 1.0).T


def stream():
    tom8 = np.load(OUT / "tom8_f32.npy", mmap_mode="r")
    x16 = sg.resample_poly(np.asarray(tom8, np.float32), 2, 1).astype(np.float32)
    hi = np.load(OUT / "hi_real.f16.npy", mmap_mode="r")
    cell = np.load(OUT / "cell_ok.u8.npy")
    return tom8, x16, hi, cell


def frames_in_chunks(x, fn, chunk=16000 * 600):
    out, mg = [], 4 * HOP                       # margin on the hop grid
    for a in range(0, len(x), chunk):
        seg = x[max(0, a - mg):a + chunk + mg]
        f = fn(seg)
        lead = (a - max(0, a - mg)) // HOP
        n = (min(len(x), a + chunk) - a) // HOP
        out.append(f[lead:lead + n].cpu())
    return torch.cat(out)


def split_masks(nframes, cell, offs, names):
    """Valid-target mask and held-out mask per 10 ms frame."""
    c = np.repeat(cell > 0, 2)[:nframes]
    c = np.r_[c, np.zeros(max(0, nframes - len(c)), bool)]
    ok = c.copy()
    for s in (-2, -1, 1, 2):                    # frame spans +-16 ms: neighbours must be ok too
        ok &= np.roll(c, s)
    held = np.zeros(nframes, bool)
    ends = np.r_[offs[1:], offs[-1] + 10 ** 9]
    demo = set(HD.DEFAULT_RECS)
    for i, (o, e, n) in enumerate(zip(offs, ends, names)):
        if i % 20 == 0 or n in demo:
            held[o // 80:min(nframes, e // 80)] = True     # 8 kHz samples -> 10 ms frames
    return ok, held


def entries():
    import tom_overlap as T
    e = T.vdb_fast.VdbSearcher(T.TOM8, probe_len=320).entries
    return np.array([x[0] for x in e], np.int64), [x[1] for x in e]


def train():
    tom8, x16, hi, cell = stream()
    X = frames_in_chunks(x16, lambda s: logpow(HD.split(s)[0]))[:, :KX]
    Y = frames_in_chunks(np.asarray(hi, np.float32), logpow)[:, KX:]
    n = min(len(X), len(Y))
    X, Y = X[:n], Y[:n]
    offs, names = entries()
    ok, held = split_masks(n, cell, offs, names)
    mu, sd = X.mean(0), X.std(0) + 1e-3
    ymu, ysd = Y[ok].mean(0), Y[ok].std(0) + 1e-3
    Xn = ((X - mu) / sd).to(DEV)
    Yn = ((Y - ymu) / ysd).to(DEV)
    M = torch.from_numpy(ok).to(DEV)
    H = torch.from_numpy(held).to(DEV)
    print(f"frames {n}, target frames {ok.sum()} ({ok.sum() / 100 / 60:.1f} min), "
          f"held-out target {(ok & held).sum()}", flush=True)
    starts = np.where(ok[:n - CTX])[0]
    tr = starts[~held[starts]]
    va = starts[held[starts]]
    net = Net().to(DEV)
    opt = torch.optim.AdamW(net.parameters(), 1e-3, weight_decay=1e-2)
    steps = 4000
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, 1e-3, total_steps=steps)
    rng = np.random.default_rng(3)
    ar = torch.arange(CTX, device=DEV)

    def batch(pool, b=64, r=rng):
        st = torch.from_numpy(r.choice(pool, b)).to(DEV) - CTX // 2
        st = st.clamp(0, n - CTX)
        idx = st[:, None] + ar
        m = M[idx] & (H[idx] == H[idx[:, CTX // 2:CTX // 2 + 1]])
        return Xn[idx].transpose(1, 2), Yn[idx].transpose(1, 2), m

    def loss_on(xb, yb, m):
        p = net(xb)
        e = (p - yb).abs().mean(1)
        return (e * m).sum() / m.sum().clamp_min(1)

    vrng = np.random.default_rng(99)
    vset = [batch(va, r=vrng) for _ in range(40)]
    best, best_state = 9.0, None
    for it in range(steps):
        net.train()
        xb, yb, m = batch(tr)
        xb = xb + 0.1 * torch.randn_like(xb)
        loss = loss_on(xb, yb, m)
        opt.zero_grad()
        loss.backward()
        opt.step()
        sched.step()
        if it % 250 == 0 or it == steps - 1:
            net.eval()
            with torch.no_grad():
                vl = float(np.mean([loss_on(*v).item() for v in vset]))
            if vl < best:
                best, best_state = vl, {k: t.detach().clone() for k, t in net.state_dict().items()}
            print(f"step {it:5d}  train {loss.item():.3f}  val {vl:.3f}{'  *' if vl == best else ''}", flush=True)
    torch.save({"net": best_state, "mu": mu, "sd": sd, "ymu": ymu, "ysd": ysd}, OUT / "bwe.pt")
    print(f"saved {OUT / 'bwe.pt'} (best val {best:.3f})")


_M = {}


def load():
    if not _M:
        ck = torch.load(OUT / "bwe.pt", map_location=DEV)
        net = Net().to(DEV)
        net.load_state_dict(ck["net"])
        net.eval()
        _M.update(net=net, **{k: ck[k].to(DEV) for k in ("mu", "sd", "ymu", "ysd")})
    return _M


BP_PITCH = sg.firwin(255, [1000, 3400], fs=16000, pass_zero=False)
LP_ENV = sg.firwin(63, 800, fs=16000)


def excitation(lo, exc, depth=0.6, seed=0):
    """Wideband excitation whose 3.4-8 kHz part gets shaped. 'rect' = |low band| (v1);
    'modnoise' = noise carrying the low band's pitch-rate envelope; 'noise' = plain noise."""
    if exc == "rect":
        r = np.abs(lo)
        return r - np.convolve(r, np.ones(321) / 321, mode="same")
    nz = np.random.default_rng(seed).standard_normal(len(lo))
    if exc == "noise":
        return nz
    e = np.abs(sg.hilbert(HD.zconv(lo, BP_PITCH)))
    e = HD.zconv(e, LP_ENV)
    slow = np.convolve(e, np.ones(321) / 321, mode="same") + 1e-3
    mod = np.clip(e / slow, 0, 3)
    return nz * (1 - depth + depth * mod)


@torch.no_grad()
def render(x16, gain=1.0, exc="rect", tsm=1, fsm=5, depth=0.6):
    """tom8 x2 (one recording, 16 kHz) -> synthetic 3.4-8 kHz band, same length."""
    m = load()
    lo, _ = HD.split(np.asarray(x16, np.float64))
    w = torch.hann_window(NFFT, device=DEV)
    lt = torch.from_numpy(lo.astype(np.float32)).to(DEV)
    S = torch.stft(lt, NFFT, HOP, window=w, center=True, return_complex=True)
    X = (torch.log10(S.abs() ** 2 + 1.0).T[:, :KX] - m["mu"]) / m["sd"]
    env = m["net"](X.T[None])[0].T * m["ysd"] + m["ymu"]            # frames, NY (log10 power)
    env = torch.nn.functional.avg_pool1d(env.T[None], fsm, 1, fsm // 2, count_include_pad=False)[0].T
    if tsm > 1:
        env = torch.nn.functional.avg_pool1d(env.T[:, None], tsm, 1, tsm // 2, count_include_pad=False)[:, 0].T
    ex = torch.from_numpy(excitation(lo, exc, depth).astype(np.float32)).to(DEV)
    E = torch.stft(ex, NFFT, HOP, window=w, center=True, return_complex=True)[KX:]
    mag = E.abs()
    sm = torch.nn.functional.avg_pool1d(mag.T[:, None], 11, 1, 5, count_include_pad=False)[:, 0].T
    Ew = E / sm.clamp_min(1e-6)
    Y = torch.zeros(NFFT // 2 + 1, Ew.shape[1], dtype=torch.complex64, device=DEV)
    Y[KX:] = Ew * torch.sqrt(10 ** env.T) * gain
    y = torch.istft(Y, NFFT, HOP, window=w, center=True, length=len(x16)).cpu().numpy()
    return HD.split(y.astype(np.float64))[1]


def _smooth(L, tsm, fsm):
    """L (frames, bins) smoothed over fsm bins and tsm frames."""
    L = torch.nn.functional.avg_pool1d(L[None], fsm, 1, fsm // 2, count_include_pad=False)[0]
    return torch.nn.functional.avg_pool1d(L.T[:, None], tsm, 1, tsm // 2, count_include_pad=False)[:, 0].T


@torch.no_grad()
def envelopes(x16, real=None, tsm=3, fsm=9):
    """-> lo, predicted top-band envelope, real band's envelope (or None); (frames, NY) log10 power."""
    m = load()
    lo, _ = HD.split(np.asarray(x16, np.float64))
    w = torch.hann_window(NFFT, device=DEV)
    S = torch.stft(torch.from_numpy(lo.astype(np.float32)).to(DEV), NFFT, HOP, window=w,
                   center=True, return_complex=True)
    X = (torch.log10(S.abs() ** 2 + 1.0).T[:, :KX] - m["mu"]) / m["sd"]
    ep = _smooth(m["net"](X.T[None])[0].T * m["ysd"] + m["ymu"], tsm, fsm)
    er = None
    if real is not None:
        R = torch.stft(torch.from_numpy(np.asarray(real, np.float32)).to(DEV), NFFT, HOP, window=w,
                       center=True, return_complex=True)
        er = _smooth(torch.log10(R.abs() ** 2 + 1.0).T[:, KX:], tsm, fsm)
    return lo, ep, er


def sibilance(lo, nframes):
    """Per frame 0..1: how far tom8's 2.5-3.4 kHz power exceeds its 0-1 kHz power (0 dB -> 0, 6 dB -> 1)."""
    w = torch.hann_window(NFFT, device=DEV)
    S = torch.stft(torch.from_numpy(lo.astype(np.float32)).to(DEV), NFFT, HOP, window=w,
                   center=True, return_complex=True).abs() ** 2
    f = torch.fft.rfftfreq(NFFT, 1 / 16000).to(DEV)
    r = 10 * torch.log10((S[(f >= 2500) & (f < 3400)].sum(0) + 1) / (S[f < 1000].sum(0) + 1))
    s = ((r / 6).clamp(0, 1))[None, None]
    return torch.nn.functional.avg_pool1d(s, 3, 1, 1, count_include_pad=False)[0, 0][:nframes]


@torch.no_grad()
def render2(x16, real=None, mask=None, depth=0.3, bias=0.0, gain=1.0, tsm=3, fsm=9, deess=0.0):
    """One smooth excitation for the whole recording; envelope = the REAL band's where
    mask (16 kHz, 0..1) says so, the predicted one (+ bias, log10 power per bin) elsewhere.
    Only the envelope ever crossfades, so there is no fine-structure splice.
    deess: dB cut at >= 6 kHz (ramped in from 4.5 kHz), scaled by per-frame sibilance."""
    lo, ep, er = envelopes(x16, real, tsm, fsm)
    env = ep + torch.as_tensor(bias, dtype=ep.dtype, device=DEV)
    if deess:
        fb = torch.fft.rfftfreq(NFFT, 1 / 16000)[KX:].to(DEV)
        ramp = ((fb - 4500) / 1500).clamp(0, 1)
        env = env - sibilance(lo, env.shape[0])[:, None] * ramp[None] * (deess / 10)
    if er is not None and mask is not None:
        idx = np.clip(np.arange(env.shape[0]) * HOP, 0, len(mask) - 1)
        mf = torch.from_numpy(np.asarray(mask, np.float32)[idx]).to(DEV)[:, None]
        env = mf * er + (1 - mf) * env
    w = torch.hann_window(NFFT, device=DEV)
    ex = torch.from_numpy(excitation(lo, "modnoise", depth).astype(np.float32)).to(DEV)
    E = torch.stft(ex, NFFT, HOP, window=w, center=True, return_complex=True)[KX:]
    sm = torch.nn.functional.avg_pool1d(E.abs().T[:, None], 11, 1, 5, count_include_pad=False)[:, 0].T
    Y = torch.zeros(NFFT // 2 + 1, E.shape[1], dtype=torch.complex64, device=DEV)
    Y[KX:] = E / sm.clamp_min(1e-6) * torch.sqrt(10 ** env.T) * gain
    y = torch.istft(Y, NFFT, HOP, window=w, center=True, length=len(x16)).cpu().numpy()
    return lo, HD.split(y.astype(np.float64))[1]


def evaluate():
    """Held-out log-spectral distance on the real band: BWE vs AudioSR."""
    tom8, x16, hi, cell = stream()
    offs, names = entries()
    ends = np.r_[offs[1:], len(tom8)]
    rows = {"bwe": [], "asr": []}
    lev = []
    for i, nm in enumerate(names):
        if not (i % 20 == 0 or nm in HD.DEFAULT_RECS):
            continue
        s0, s1 = int(offs[i]), int(ends[i])
        c = cell[s0 // 160:s1 // 160]
        if (c > 0).sum() < 10:
            continue
        xr = x16[2 * s0:2 * s1]
        real = np.asarray(hi[2 * s0:2 * s1], np.float64)
        b = render(xr)
        _, a = HD.split(HD.tom16_slice(s0, s1 - s0))
        ok = np.repeat(c > 0, 2)
        Lr, Lb, La = (logpow(v)[:, KX:].cpu().numpy() for v in (real, b, a))
        k = min(len(ok), len(Lr))
        sel = ok[:k]
        for key, L in (("bwe", Lb), ("asr", La)):
            rows[key].append(10 * np.sqrt(np.mean((L[:k][sel] - Lr[:k][sel]) ** 2, 1)))
        m16 = np.repeat(c > 0, 320)[:len(real)]
        m16 = np.r_[m16, np.zeros(len(real) - len(m16), bool)]
        lev.append((np.sqrt(np.mean(real[m16] ** 2)), np.sqrt(np.mean(b[m16] ** 2))))
    for k, v in rows.items():
        v = np.concatenate(v)
        print(f"{k}: HF log-spectral distance vs real, dB  p25 {np.quantile(v, .25):.2f}  "
              f"p50 {np.median(v):.2f}  p75 {np.quantile(v, .75):.2f}  (n {len(v)})")
    r, b = np.array(lev).T
    g = float(np.median(r / b))
    print(f"BWE level vs real: {20 * np.log10(1 / g):+.2f} dB (median over {len(lev)} recordings)")
    (OUT / "bwe_eval.json").write_text(json.dumps({"level_gain": g}))


if __name__ == "__main__":
    {"train": train, "eval": evaluate}[sys.argv[1]]()
