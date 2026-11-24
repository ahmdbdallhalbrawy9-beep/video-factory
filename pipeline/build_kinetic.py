#!/usr/bin/env python3
"""Kinetic-text vertical reel: big Arabic words that appear in sync with the voice, icons, progress bar,
soft drifting background, synthesized (royalty-free) sound bed. Everything is drawn by code.

Usage: python pipeline/build_kinetic.py MANIFEST.json OUT_DIR
Manifest: {"voice": path|null, "lines":[{"t0":s,"t1":s,"text":"words *highlighted* |line break","icon":"cart","big":"٥٥","sub":"قدم","wt":[...]}],
           "tail":0.7}
Times are in voice seconds (voice is delayed by LEAD in the final video).
"""
import json, os, re, shutil, subprocess, sys, wave
import numpy as np

man = json.load(open(sys.argv[1], encoding="utf-8"))
out = sys.argv[2]
os.makedirs(out, exist_ok=True)
W, H, FPS = 720, 1280, 30
LEAD = 0.25
TAIL = man.get("tail", 0.8)


def sh(cmd):
    print("+", " ".join(str(c) for c in cmd)[:300], flush=True)
    subprocess.run(cmd, check=True)


lines = man["lines"]
voice = man.get("voice")
if voice:
    sh(["ffmpeg", "-y", "-v", "error", "-i", voice, "-ar", "44100", "-ac", "1", f"{out}/voice.wav"])
    with wave.open(f"{out}/voice.wav") as w:
        D = w.getnframes() / w.getframerate()
else:
    D = max(l["t1"] for l in lines)
total = LEAD + D + TAIL

ICONS = {
    "cart": '<path d="M3 4h3l2.4 11h10.2l2-8H7" /><circle cx="10" cy="20" r="1.6"/><circle cx="18" cy="20" r="1.6"/>',
    "coins": '<ellipse cx="9" cy="8" rx="6" ry="3"/><path d="M3 8v4c0 1.7 2.7 3 6 3s6-1.3 6-3V8"/><path d="M15 11c3.3 0 6 1.3 6 3v4c0 1.7-2.7 3-6 3-2.2 0-4.1-.6-5.2-1.5"/>',
    "steps": '<path d="M7 3c2 0 3 2 3 5s-1 4-3 4-3-1-3-4 1-5 3-5z"/><path d="M5 15h4v2.5a2 2 0 0 1-4 0z"/><path d="M16 9c2 0 3 2 3 5s-1 4-3 4-3-1-3-4 1-5 3-5z"/><path d="M14 21h4"/>',
    "search": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5 21 21"/>',
    "store": '<path d="M3 9l2-5h14l2 5"/><path d="M4 9v11h16V9"/><path d="M3 9c0 2 3 2 3 0 0 2 3 2 3 0 0 2 3 2 3 0 0 2 3 2 3 0 0 2 3 2 3 0"/><path d="M10 20v-6h4v6"/>',
    "question": '<path d="M8.5 9a3.5 3.5 0 1 1 5.2 3c-1.2.7-1.7 1.3-1.7 2.5"/><circle cx="12" cy="18.5" r=".6"/>',
    "list": '<path d="M9 6h11M9 12h11M9 18h11"/><path d="M4 6l1 1 2-2M4 12l1 1 2-2M4 18l1 1 2-2"/>',
}

CSS = """
html,body{margin:0;background:transparent}
.w{width:720px;height:1280px;position:relative;font-family:'Noto Sans Arabic','Noto Naskh Arabic','DejaVu Sans',sans-serif;direction:rtl}
.stack{position:absolute;left:46px;right:46px;top:150px;height:900px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:34px;text-align:center}
.pill{display:flex;align-items:center;gap:14px;border:3px solid rgba(255,194,51,.85);border-radius:60px;padding:12px 30px 12px 26px;
 background:rgba(255,194,51,.10);color:#ffd77a;font-weight:700;font-size:40px}
.pill svg{width:54px;height:54px;stroke:#ffc233;fill:none;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}
.icon svg{width:190px;height:190px;stroke:#ffc233;fill:none;stroke-width:1.2;stroke-linecap:round;stroke-linejoin:round;filter:drop-shadow(0 0 28px rgba(255,194,51,.45))}
.big{font-size:230px;font-weight:800;line-height:1;color:#ffc233;text-shadow:0 0 60px rgba(255,194,51,.35)}
.sub{font-size:52px;font-weight:700;color:#cfd6e6}
.t{font-weight:800;font-size:84px;line-height:1.38;color:#fff;text-shadow:0 6px 24px rgba(0,0,0,.55)}
.t.small{font-size:70px}
.t .hl{color:#ffc233}
.t .hid{visibility:hidden}
"""


def parse(text):
    """-> list of tokens: ('w', word, hl) or ('br',)"""
    toks = []
    for part in re.split(r"(\|)", text):
        if part == "|":
            toks.append(("br",))
            continue
        for w in part.split():
            hl = w.startswith("*") and w.endswith("*") and len(w) > 2
            toks.append(("w", w.strip("*"), hl))
    return toks


def html_state(line, toks, k):
    """k = number of words visible."""
    n_seen = 0
    body = []
    for t in toks:
        if t[0] == "br":
            body.append("<br>")
            continue
        n_seen += 1
        cls = "hl" if t[2] else ""
        if n_seen > k:
            cls += " hid"
        body.append(f'<span class="{cls.strip()}">{t[1]}</span> ')
    parts = []
    if line.get("icon") and line.get("big") is None and line.get("pill") is None:
        parts.append(f'<div class="icon"><svg viewBox="0 0 24 24">{ICONS[line["icon"]]}</svg></div>')
    if line.get("pill"):
        parts.append(f'<div class="pill"><svg viewBox="0 0 24 24">{ICONS[line.get("icon","question")]}</svg><span>{line["pill"]}</span></div>')
    if line.get("big") is not None:
        parts.append(f'<div class="big">{line["big"]}</div>')
        if line.get("sub"):
            parts.append(f'<div class="sub">{line["sub"]}</div>')
    size = "small" if line.get("small") else ""
    parts.append(f'<div class="t {size}">{"".join(body)}</div>')
    return f'<style>{CSS}</style><div class="w"><div class="stack">{"".join(parts)}</div></div>'


# ---------- states ----------
from playwright.sync_api import sync_playwright

states = []  # (png, start, end, first_of_line)
with sync_playwright() as pw:
    br = pw.chromium.launch()
    pg = br.new_page(viewport={"width": W, "height": H})
    # background
    pg.set_content(f"""<style>html,body{{margin:0}}</style><div style="width:880px;height:1560px;position:relative;background:
      radial-gradient(ellipse 60% 38% at 50% 38%, #1d2b52 0%, #0e1630 55%, #070b18 100%)"></div>""")
    pg.set_viewport_size({"width": 880, "height": 1560})
    pg.screenshot(path=f"{out}/bg.png")
    pg.set_viewport_size({"width": W, "height": H})
    for li, line in enumerate(lines):
        toks = parse(line["text"])
        nw = sum(1 for t in toks if t[0] == "w")
        t0, t1 = line["t0"], line["t1"]
        wt = line.get("wt")
        if not wt or len(wt) != nw:
            span = max(0.4, (t1 - t0) * 0.8)
            wt = [t0 + span * i / max(nw, 1) for i in range(nw)]
        step = max(1, -(-nw // 5))
        ks = list(range(step, nw + 1, step))
        if not ks or ks[-1] != nw:
            ks.append(nw)
        end_line = min(max(t1 + 0.15, t0 + 0.5), lines[li + 1]["t0"]) if li + 1 < len(lines) else D + 0.5
        base = len(states)
        for si, k in enumerate(ks):
            ts = t0 if si == 0 else wt[ks[si - 1]]
            states.append([f"{out}/s{li}_{si}.png", ts, None, si == 0, li, k, line, toks])
        for j in range(len(ks)):
            states[base + j][2] = states[base + j + 1][1] if j + 1 < len(ks) else end_line
    for s in states:
        pg.set_content(html_state(s[6], s[7], s[5]))
        pg.screenshot(path=s[0], omit_background=True)
    br.close()

# ---------- video ----------
inputs = ["-loop", "1", "-framerate", str(FPS), "-t", f"{total:.3f}", "-i", f"{out}/bg.png"]
fc = [f"[0:v]crop={W}:{H}:x='80+70*sin(t/4.5)':y='140+90*cos(t/6)',format=yuv420p,noise=alls=5:allf=t,vignette=PI/5[b0]"]
cur = "b0"
for i, (png, ts, te, first, li, k, line, toks) in enumerate(states):
    a, b = LEAD + ts, LEAD + te
    inputs += ["-loop", "1", "-framerate", str(FPS), "-t", f"{b - a + 0.05:.3f}", "-i", png]
    fade = f",fade=t=in:st=0:d=0.14:alpha=1" if first else ""
    fc.append(f"[{i + 1}:v]format=rgba{fade},setpts=PTS+{a:.3f}/TB[o{i}]")
    fc.append(f"[{cur}][o{i}]overlay=0:0:eof_action=pass:format=auto[b{i + 1}]")
    cur = f"b{i + 1}"
fc.append(f"color=c=0xffc233:s={W}x10:r={FPS}:d={total:.3f},format=rgba[bar0]")
fc.append(f"[bar0]scale=w='max(2,{W}*t/{total:.3f})':h=10:eval=frame[bar]")
fc.append(f"[{cur}][bar]overlay=0:0:eof_action=pass,format=yuv420p[v]")
open(f"{out}/fc.txt", "w").write(";\n".join(fc))
sh(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex_script", f"{out}/fc.txt", "-map", "[v]", "-t", f"{total:.3f}",
    "-r", str(FPS), "-c:v", "libx264", "-crf", "20", "-preset", "veryfast", "-pix_fmt", "yuv420p", f"{out}/silent.mp4"])

# ---------- sound (synthesized) ----------
SR = 44100
Ns = int(total * SR) + SR
t = np.arange(Ns) / SR
rng = np.random.default_rng(5)
mus = 0.05 * np.sin(2 * np.pi * 55 * t) + 0.03 * np.sin(2 * np.pi * 82.4 * t + 1.0)
mus *= 0.6 + 0.4 * np.sin(2 * np.pi * 0.18 * t)
mus += 0.012 * np.convolve(rng.standard_normal(Ns), np.ones(400) / 400, mode="same")
sfx = np.zeros(Ns)


def add(buf, at, sig, g):
    i = int(at * SR)
    if 0 <= i < Ns:
        j = min(Ns, i + len(sig))
        buf[i:j] += sig[: j - i] * g


def soft_tick(f=520, d=0.09):
    tt = np.arange(int(d * SR)) / SR
    return np.sin(2 * np.pi * f * tt) * np.exp(-tt * 38)


for line in lines:
    add(sfx, LEAD + line["t0"] - 0.02, soft_tick(), 0.04)
mix = mus + sfx
mix[: int(0.3 * SR)] *= np.linspace(0, 1, int(0.3 * SR))
mix = mix[: int(total * SR)]
mix *= np.clip((total - t[: len(mix)]) / 0.8, 0, 1)
mix = mix / max(np.abs(mix).max(), 1e-9) * 0.30
with wave.open(f"{out}/bed.wav", "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes((mix * 32767).astype(np.int16).tobytes())

if voice:
    sh(["ffmpeg", "-y", "-v", "error", "-i", f"{out}/silent.mp4", "-i", f"{out}/voice.wav", "-i", f"{out}/bed.wav",
        "-filter_complex",
        f"[1:a]adelay={int(LEAD * 1000)}:all=1,volume=1.0,asplit=2[v][vs];[2:a]volume=0.45[b0];"
        f"[b0][vs]sidechaincompress=threshold=0.02:ratio=6:attack=5:release=300[b];"
        f"[v][b]amix=inputs=2:duration=longest:normalize=0,loudnorm=I=-15:TP=-1.5:LRA=9[a]",
        "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.3f}", f"{out}/final.mp4"])
else:
    sh(["ffmpeg", "-y", "-v", "error", "-i", f"{out}/silent.mp4", "-i", f"{out}/bed.wav",
        "-filter_complex", "[1:a]volume=1.6,loudnorm=I=-17:TP=-1.5:LRA=9[a]",
        "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.3f}", f"{out}/final.mp4"])
json.dump({"seconds": total}, open(f"{out}/info.json", "w"))
print("DONE", f"{out}/final.mp4")
