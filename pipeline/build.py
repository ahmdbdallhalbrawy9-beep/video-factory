#!/usr/bin/env python3
"""Episode builder: Arabic voice (edge-tts) + 3D render (Blender) + Arabic captions (Chromium) -> final.mp4
Usage: python pipeline/build.py episodes/<name>/episode.json OUT_DIR
"""
import asyncio, json, os, subprocess, sys, shutil

ep_path, out = sys.argv[1], sys.argv[2]
ep = json.load(open(ep_path, encoding="utf-8"))
os.makedirs(out, exist_ok=True)
W, H = ep.get("width", 720), ep.get("height", 1280)
GAP, LEAD, TAIL = 0.28, 0.25, 0.6


def run(cmd, **kw):
    print("+", " ".join(map(str, cmd)), flush=True)
    return subprocess.run(cmd, check=True, **kw)


def duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", path], capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


# ---------- 1) voice ----------
async def tts(text, voice, path):
    import edge_tts
    last = None
    for attempt in range(4):
        try:
            await edge_tts.Communicate(text, voice, rate=ep.get("rate", "+0%")).save(path)
            if os.path.getsize(path) > 1000:
                return "edge-tts"
        except Exception as e:  # noqa
            last = e
            print("edge-tts attempt", attempt, "failed:", repr(e), flush=True)
            await asyncio.sleep(2 + attempt * 2)
    print("FALLBACK to gTTS (MSA Arabic) because:", repr(last), flush=True)
    from gtts import gTTS
    gTTS(text, lang="ar").save(path)
    return "gtts"


wavs, starts, ends = [], [], []
cursor = LEAD
engine_used = set()
for i, sc in enumerate(ep["scenes"]):
    mp3 = f"{out}/v{i}.mp3"
    engine_used.add(asyncio.run(tts(sc["text"], ep["voice"], mp3)))
    wav = f"{out}/v{i}.wav"
    run(["ffmpeg", "-y", "-v", "error", "-i", mp3, "-ar", "44100", "-ac", "1", wav])
    d = duration(wav)
    starts.append(cursor)
    ends.append(cursor + d)
    cursor += d + GAP
    wavs.append(wav)
total = cursor - GAP + TAIL
print("TTS engine:", engine_used, "| total seconds:", round(total, 2), flush=True)

# build one voice track with lead/gaps/tail
parts = []
inputs = []
fc = []
idx = 0
inputs += ["-f", "lavfi", "-t", str(LEAD), "-i", "anullsrc=r=44100:cl=mono"]
parts.append(f"[{idx}:a]"); idx += 1
for i, w in enumerate(wavs):
    inputs += ["-i", w]; parts.append(f"[{idx}:a]"); idx += 1
    gap = GAP if i < len(wavs) - 1 else TAIL
    inputs += ["-f", "lavfi", "-t", str(gap), "-i", "anullsrc=r=44100:cl=mono"]
    parts.append(f"[{idx}:a]"); idx += 1
run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex",
     "".join(parts) + f"concat=n={len(parts)}:v=0:a=1[a]", "-map", "[a]", f"{out}/voice.wav"])

# ---------- 2) 3D render ----------
scene_script = ep.get("scene_script", "pipeline/scene_test.py")
run(["blender", "-b", "-P", scene_script, "--", f"{out}/render.mp4", str(W), str(H),
     f"{total:.3f}", str(ep.get("samples", 16))])

# ---------- 3) captions ----------
from playwright.sync_api import sync_playwright

CSS = """
html,body{margin:0;background:transparent}
.w{width:%dpx;height:%dpx;position:relative;font-family:'Noto Sans Arabic','Noto Naskh Arabic',sans-serif}
.c{position:absolute;left:5%%;right:5%%;top:68%%;text-align:center;direction:rtl;
 font-weight:800;font-size:%dpx;line-height:1.35;color:#fff;
 -webkit-text-stroke:%dpx #0b1220;paint-order:stroke fill;
 text-shadow:0 6px 18px rgba(0,0,0,.55)}
""" % (W, H, int(W * 0.105), max(8, int(W * 0.022)))

cap_pngs = []
with sync_playwright() as pw:
    br = pw.chromium.launch()
    pg = br.new_page(viewport={"width": W, "height": H})
    for i, sc in enumerate(ep["scenes"]):
        pg.set_content(f"<style>{CSS}</style><div class='w'><div class='c'>{sc['caption']}</div></div>")
        pg.wait_for_timeout(300)
        p = f"{out}/cap{i}.png"
        pg.screenshot(path=p, omit_background=True)
        cap_pngs.append(p)
    br.close()

# ---------- 4) mux ----------
cmd = ["ffmpeg", "-y", "-v", "error", "-i", f"{out}/render.mp4"]
for p in cap_pngs:
    cmd += ["-i", p]
cmd += ["-i", f"{out}/voice.wav"]
chain, last = [], "[0:v]"
for i in range(len(cap_pngs)):
    nxt = f"[v{i}]"
    chain.append(f"{last}[{i+1}:v]overlay=0:0:enable='between(t,{starts[i]:.3f},{ends[i]+GAP:.3f})'{nxt}")
    last = nxt
cmd += ["-filter_complex", ";".join(chain), "-map", last, "-map", f"{len(cap_pngs)+1}:a",
        "-c:v", "libx264", "-crf", "18", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k", "-shortest", f"{out}/final.mp4"]
run(cmd)
json.dump({"tts_engine": sorted(engine_used), "seconds": total, "scenes": list(zip(starts, ends))},
          open(f"{out}/info.json", "w"))
print("DONE", f"{out}/final.mp4")
