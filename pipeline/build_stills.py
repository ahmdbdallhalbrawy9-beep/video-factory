#!/usr/bin/env python3
"""Stills -> cinematic vertical reel.
AI-generated stills + ElevenLabs voice -> Ken-Burns shots, Arabic captions (Chromium), synthesized SFX/drone.

Usage: python pipeline/build_stills.py MANIFEST.json OUT_DIR
Manifest: {"voice": URL|path, "shots": [{"image": URL|path, "caption": "html", "focus": 0.5, "zoom": "in"|"out"}]}
Shot boundaries come from pauses in the voice (silencedetect), falling back to equal splits.
"""
import json, math, os, re, shutil, subprocess, sys, wave
import numpy as np

man = json.load(open(sys.argv[1], encoding="utf-8"))
out = sys.argv[2]
os.makedirs(out, exist_ok=True)
W, H, FPS = 720, 1280, 30
LEAD, TAIL = 0.25, 0.7
FG_Y = 170  # top of the picture window inside the 9:16 frame


def sh(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run(cmd, check=True, **kw)


def fetch(src, dst):
    if src.startswith("http"):
        sh(["curl", "-fsSL", "--retry", "3", "-o", dst, src])
    else:
        shutil.copy(src, dst)


def probe(path, entries):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", entries, "-of", "default=nw=1:nk=1", path],
                       capture_output=True, text=True, check=True)
    return r.stdout.split()


# ---------- voice ----------
fetch(man["voice"], f"{out}/voice_raw")
sh(["ffmpeg", "-y", "-v", "error", "-i", f"{out}/voice_raw", "-ar", "44100", "-ac", "1", f"{out}/voice.wav"])
D = float(probe(f"{out}/voice.wav", "format=duration")[0])
n = len(man["shots"])

# pauses -> cut points
cuts = []
if n > 1:
    r = subprocess.run(["ffmpeg", "-i", f"{out}/voice.wav", "-af", "silencedetect=noise=-32dB:d=0.16", "-f", "null", "-"],
                       capture_output=True, text=True)
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    gaps = [(s, e) for s, e in zip(starts, ends) if s > 0.5 and e < D - 0.3]
    gaps.sort(key=lambda g: g[1] - g[0], reverse=True)
    pick = sorted(gaps[: n - 1])
    cuts = [(s + e) / 2 for s, e in pick]
    if len(cuts) != n - 1:
        print("silence detection gave", len(cuts), "cuts; falling back to equal splits", flush=True)
        cuts = [D * (i + 1) / n for i in range(n - 1)]
print("voice seconds", D, "cuts", cuts, flush=True)
bounds = [0.0] + [LEAD + c for c in cuts] + [LEAD + D + TAIL]
total = bounds[-1]

# ---------- captions (Chromium) ----------
from playwright.sync_api import sync_playwright

CSS = """
html,body{margin:0;background:transparent}
.w{width:720px;height:1280px;position:relative;font-family:'Noto Sans Arabic','Noto Naskh Arabic','DejaVu Sans',sans-serif}
.c{position:absolute;left:44px;right:44px;top:940px;text-align:center;direction:rtl;font-weight:800;font-size:76px;line-height:1.3;
 color:#fff;-webkit-text-stroke:16px #0a1020;paint-order:stroke fill;text-shadow:0 8px 22px rgba(0,0,0,.6)}
.c .hl{color:#ffc233}
"""
with sync_playwright() as pw:
    br = pw.chromium.launch()
    pg = br.new_page(viewport={"width": W, "height": H})
    for i, s in enumerate(man["shots"]):
        pg.set_content(f"<style>{CSS}</style><div class='w'><div class='c'>{s['caption']}</div></div>")
        pg.wait_for_timeout(250)
        pg.screenshot(path=f"{out}/cap{i}.png", omit_background=True)
    br.close()

# ---------- shots ----------
files = []
for i, s in enumerate(man["shots"]):
    img = f"{out}/img{i}.png"
    fetch(s["image"], img)
    iw, ih = [int(x) for x in probe(img, "stream=width,height")]
    d = bounds[i + 1] - bounds[i]
    N = max(2, round(d * FPS))
    zin = s.get("zoom", "in") == "in"
    zexpr = f"1+0.13*on/{N}" if zin else f"1.13-0.13*on/{N}"
    if ih > iw * 1.3:  # already vertical: full bleed
        fg = (f"[0:v]scale=1440:2560:flags=lanczos,unsharp=5:5:0.9:5:5:0.0,zoompan=z='{zexpr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
              f"d={N}:s={W}x{H}:fps={FPS}[fg]")
        comp = "[fg]null[base]"
    else:  # landscape: square window, blurred full-bleed background
        side = min(iw, ih)
        x0 = int(max(0, min(iw - side, s.get("focus", 0.5) * iw - side / 2)))
        fg = (f"[0:v]crop={side}:{side}:{x0}:0,scale=1440:1440:flags=lanczos,"
              f"zoompan=z='{zexpr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={N}:s=720x720:fps={FPS}[fg]")
        comp = (f"[1:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},gblur=sigma=30,"
                f"eq=brightness=-0.30:saturation=0.85[bg];[bg][fg]overlay=0:{FG_Y}[base]")
    fc = (f"{fg};{comp};[2:v]format=rgba,fade=t=in:st=0.08:d=0.22:alpha=1[cap];"
          f"[base]noise=alls=6:allf=t,vignette=PI/5[gr];[gr][cap]overlay=0:0,format=yuv420p[v]")
    tmp = f"{out}/shot{i}.tmp.mp4"
    sh(["ffmpeg", "-y", "-v", "error", "-i", img, "-loop", "1", "-framerate", str(FPS), "-t", f"{d:.3f}", "-i", img,
        "-loop", "1", "-framerate", str(FPS), "-t", f"{d:.3f}", "-i", f"{out}/cap{i}.png",
        "-filter_complex", fc, "-map", "[v]", "-frames:v", str(N), "-r", str(FPS),
        "-c:v", "libx264", "-crf", "18", "-preset", "veryfast", "-pix_fmt", "yuv420p", tmp])
    os.replace(tmp, f"{out}/shot{i}.mp4")
    files.append(f"{out}/shot{i}.mp4")
with open(f"{out}/list.txt", "w") as f:
    f.write("".join(f"file '{os.path.abspath(p)}'\n" for p in files))
sh(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", f"{out}/list.txt", "-c", "copy", f"{out}/silent.mp4"])

# ---------- sound design ----------
SR = 44100
Ns = int(total * SR) + SR
t = np.arange(Ns) / SR
rng = np.random.default_rng(3)
mus = 0.05 * np.sin(2 * np.pi * 55 * t) + 0.03 * np.sin(2 * np.pi * 82.4 * t + 1.0)
mus *= 0.6 + 0.4 * np.sin(2 * np.pi * 0.18 * t)
mus += 0.012 * np.convolve(rng.standard_normal(Ns), np.ones(400) / 400, mode="same")
sfx = np.zeros(Ns)


def add(buf, at, sig, g):
    i = int(at * SR)
    if 0 <= i < Ns:
        j = min(Ns, i + len(sig))
        buf[i:j] += sig[: j - i] * g


def whoosh(d=0.45):
    tt = np.arange(int(d * SR)) / SR
    nz = np.convolve(rng.standard_normal(len(tt)), np.ones(30) / 30, mode="same")
    return nz * np.sin(np.pi * tt / d) ** 2 * 3.0


def hit(f=62, d=0.7):
    tt = np.arange(int(d * SR)) / SR
    return np.sin(2 * np.pi * f * tt * (1 + 0.5 * np.exp(-tt * 18))) * np.exp(-tt * 5)


add(sfx, 0.05, hit(), 0.55)
for b in bounds[1:-1]:
    add(sfx, b - 0.28, whoosh(), 0.45)
    add(sfx, b, hit(70, 0.5), 0.40)
mix = mus + sfx
mix[: int(0.3 * SR)] *= np.linspace(0, 1, int(0.3 * SR))
mix = mix[: int(total * SR)]
mix *= np.clip((total - t[: len(mix)]) / 0.8, 0, 1)
pk = np.abs(mix).max()
mix = mix / max(pk, 1e-9) * 0.5
with wave.open(f"{out}/bed.wav", "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes((mix * 32767).astype(np.int16).tobytes())

sh(["ffmpeg", "-y", "-v", "error", "-i", f"{out}/silent.mp4", "-i", f"{out}/voice.wav", "-i", f"{out}/bed.wav",
    "-filter_complex",
    f"[1:a]adelay={int(LEAD * 1000)}:all=1,volume=1.0[v];[2:a]volume=0.55[b];"
    f"[v][b]amix=inputs=2:duration=longest:normalize=0,loudnorm=I=-15:TP=-1.5:LRA=9[a]",
    "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.3f}", f"{out}/final.mp4"])
json.dump({"seconds": total, "bounds": bounds, "voice_seconds": D}, open(f"{out}/info.json", "w"))
print("DONE", f"{out}/final.mp4")
