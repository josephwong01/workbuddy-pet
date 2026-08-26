"""
make_pet_from_static.py - Build a PetDex-compatible pet sprite package
from ONE static character image (PNG with transparency strongly preferred).

Why this exists
---------------
PetDex pets need a 9-state spritesheet (8 columns x 9 rows, 192x208 per
frame = 1536x1872). A single still image can't magically become 9 distinct
*pose* animations, but we CAN turn it into a "living" pet via programmatic
"puppet" motion: bob/breathing for idle, step loops for running, a wobble for
waving, a hop for jumping, red shake for failed, slow tilt for waiting/review.

Pipeline (fully offline, Pillow only):
  1. Load static image, auto-trim transparent padding, fit into 192x208
     canvas (preserve aspect), anchor near bottom-center.
  2. Synthesize per-state animated frames via puppet motion.
  3. Export per-state GIFs (editable animation assets).
  4. Compose high-quality atlas PNG (in-memory RGBA, no GIF re-encode loss).
  5. Emit pet.json (with slug) and optionally install into
     ~/.petdex/pets/<slug>/ as spritesheet.png + pet.json.

Usage:
  python make_pet_from_static.py --image char.png --slug my-pet --name "My Pet" --install
  python make_pet_from_static.py --make-demo --slug wb-demo --name "WB Demo" --install
"""
import os
import sys
import json
import math
import argparse
from PIL import Image, ImageChops, ImageDraw

FRAME_W = 192
FRAME_H = 208
COLS = 8
ROWS = 9

STATE_ORDER = [
    "idle", "running-right", "running-left", "waving",
    "jumping", "failed", "waiting", "running", "review",
]

# Per-state frame durations (ms) — mirrors compose_gif_atlas DEFAULT_DURATIONS.
DURATIONS = {
    "idle":          [280, 110, 110, 140, 140, 320],
    "running-right": [120, 120, 120, 120, 120, 120, 120, 220],
    "running-left":  [120, 120, 120, 120, 120, 120, 120, 220],
    "waving":        [140, 140, 140, 280],
    "jumping":       [140, 140, 140, 140, 280],
    "failed":        [140, 140, 140, 140, 140, 140, 140, 240],
    "waiting":       [150, 150, 150, 150, 150, 260],
    "running":       [120, 120, 120, 120, 120, 120, 120, 220],
    "review":        [150, 150, 150, 150, 150, 280],
}


# --------------------------------------------------------------------------
# Image helpers
# --------------------------------------------------------------------------
def remove_background(img: Image.Image, threshold: int = 220) -> Image.Image:
    """Make near-white / near-solid-bg pixels transparent.

    Works well for character art on plain white or light-grey backgrounds
    (e.g. JPG product shots).  For complex backgrounds use rembg instead.
    """
    img = img.convert("RGBA")
    data = img.getdata()
    new_data = []
    for r, g, b, a in data:
        # Pixel is "background" if it's bright AND low-saturation (near-white/grey)
        brightness = (int(r) + int(g) + int(b)) / 3
        saturation = max(abs(int(r) - int(g)), abs(int(g) - int(b)), abs(int(r) - int(b)))
        if brightness >= threshold and saturation < 30:
            new_data.append((r, g, b, 0))
        else:
            new_data.append((r, g, b, a))
    img.putdata(new_data)

    # Clean up stray opaque specks near edges with a small morphological erode
    # on the alpha channel only — softens jagged edges from threshold cut.
    # Pure PIL implementation (no numpy needed).
    alpha = img.split()[3]
    w, h = alpha.size
    pixels = alpha.load()
    new_alpha = alpha.copy()
    out = new_alpha.load()
    for y in range(h):
        for x in range(w):
            if pixels[x, y] > 0:
                # Check 8-neighbourhood for any transparent pixel
                has_trans_neighbour = False
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        if dx == 0 and dy == 0:
                            continue
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < w and 0 <= ny < h:
                            if pixels[nx, ny] == 0:
                                has_trans_neighbour = True
                                break
                    if has_trans_neighbour:
                        break
                if has_trans_neighbour:
                    out[x, y] = max(0, pixels[x, y] - 80)
    img.putalpha(new_alpha)
    return img


def fit_char(src: Image.Image, margin: float = 0.86) -> Image.Image:
    """Trim transparent padding, scale to fit, center horizontally, anchor low."""
    src = src.convert("RGBA")

    # Auto-detect and remove solid background if image has no real transparency
    extrema = src.getextrema()
    has_alpha = len(extrema) == 4 and extrema[3][0] < 255
    if not has_alpha:
        src = remove_background(src)

    bbox = src.getbbox()
    if bbox:
        src = src.crop(bbox)
    w, h = src.size
    if w == 0 or h == 0:
        raise ValueError("Source image has no opaque pixels.")
    scale = min((FRAME_W * margin) / w, (FRAME_H * margin) / h)
    nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    src = src.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGBA", (FRAME_W, FRAME_H), (0, 0, 0, 0))
    x = (FRAME_W - nw) // 2
    y = FRAME_H - nh - 6  # anchor near bottom
    canvas.paste(src, (x, y), src)
    return canvas


def shift(img: Image.Image, dx: int, dy: int) -> Image.Image:
    return ImageChops.offset(img, dx, dy)


def rot(img: Image.Image, angle: float) -> Image.Image:
    # rotate around bottom-center so the "feet" stay planted
    return img.rotate(angle, resample=Image.BICUBIC, center=(FRAME_W / 2, FRAME_H - 4),
                     expand=False)


def apply_tint(rgba: Image.Image, color, amount: float) -> Image.Image:
    src = rgba.convert("RGBA")
    r, g, b, a = src.split()
    tint = Image.new("RGBA", src.size, tuple(color) + (255,))
    blended = Image.blend(src, tint, amount)
    # keep original alpha (blend would push alpha toward 255)
    br, bg, bb, _ = blended.split()
    return Image.merge("RGBA", (br, bg, bb, a))


# --------------------------------------------------------------------------
# State synthesis (puppet motion from a single still)
# --------------------------------------------------------------------------
def build_states(base: Image.Image) -> dict:
    states: dict = {}

    # idle: very subtle breathing bob (6 frames) — nearly still
    idle = []
    for i in range(6):
        dy = round(1 * math.sin(2 * math.pi * i / 6))
        idle.append(shift(base, 0, dy))
    states["idle"] = idle

    # running-right: step loop (8 frames) — gentler
    rr = []
    for i in range(8):
        phase = 2 * math.pi * i / 8
        dx = round(5 * math.sin(phase))
        dy = round(2 * abs(math.sin(math.pi * i / 4)))
        rr.append(shift(base, dx, dy))
    states["running-right"] = rr

    # running-left: mirror base + move left (8 frames)
    base_m = base.transpose(Image.FLIP_LEFT_RIGHT)
    rl = []
    for i in range(8):
        phase = 2 * math.pi * i / 8
        dx = -round(5 * math.sin(phase))
        dy = round(2 * abs(math.sin(math.pi * i / 4)))
        rl.append(shift(base_m, dx, dy))
    states["running-left"] = rl

    # running: neutral left-right shuffle (8 frames) — 首尾回中，循环无跳变
    run_dx = [0, 3, 5, 3, 0, -3, -5, 0]
    run_dy = [0, 1, 1, 0, 0, 1, 1, 0]
    states["running"] = [shift(base, run_dx[i], run_dy[i]) for i in range(8)]

    # waving: small rotation wobble (4 frames)
    angles = [0, -4, 0, 4]
    states["waving"] = [rot(base, a) for a in angles]

    # jumping: vertical hop (5 frames) — gentler
    heights = [0, -7, -12, -7, 0]
    fwd = [0, 1, 2, 1, 0]
    states["jumping"] = [shift(base, fwd[i], heights[i]) for i in range(5)]

    # failed: red tint + horizontal shake (8 frames) — gentler
    shake = [-3, 3, -3, 3, -2, 2, -2, 2]
    red = apply_tint(base, (220, 40, 40), 0.35)
    states["failed"] = [shift(red, shake[i], 0) for i in range(8)]

    # waiting: slow bob + tiny tilt (6 frames)
    tilt = [-1, 0, 1, 0, -1, 0]
    w = []
    for i in range(6):
        dy = round(1 * math.sin(2 * math.pi * i / 6))
        w.append(rot(shift(base, 0, dy), tilt[i]))
    states["waiting"] = w

    # review: blue tint + slow tilt (6 frames)
    blue = apply_tint(base, (60, 120, 220), 0.30)
    rv = []
    for i in range(6):
        dy = round(1 * math.sin(2 * math.pi * i / 6))
        rv.append(rot(shift(blue, 0, dy), tilt[i]))
    states["review"] = rv

    return states


# --------------------------------------------------------------------------
# Tight crop: trim every frame to the union opaque bbox + pad.
# Window then hugs the pet so the WHOLE pet (not just a corner) is draggable,
# and the small remaining transparent margin no longer eats drag events.
# --------------------------------------------------------------------------
def tighten(states: dict, pad: int = 6):
    minx, miny, maxx, maxy = 10**9, 10**9, -1, -1
    for frames in states.values():
        for fr in frames:
            b = fr.split()[3].getbbox()
            if b:
                minx = min(minx, b[0]); miny = min(miny, b[1])
                maxx = max(maxx, b[2]); maxy = max(maxy, b[3])
    if maxx < 0:
        return states, FRAME_W, FRAME_H
    minx = max(0, minx - pad); miny = max(0, miny - pad)
    maxx = min(FRAME_W, maxx + pad); maxy = min(FRAME_H, maxy + pad)
    nw, nh = maxx - minx, maxy - miny
    out = {}
    for k, v in states.items():
        out[k] = [fr.crop((minx, miny, maxx, maxy)) for fr in v]
    return out, nw, nh


# --------------------------------------------------------------------------
# Output: GIFs + atlas + manifest
# --------------------------------------------------------------------------
def save_gif(frames, path, durations):
    frames[0].save(
        path, save_all=True, append_images=frames[1:],
        duration=durations, loop=0, disposal=2, optimize=False,
    )


def compose_atlas(states: dict, slug: str, name: str, out_dir: str, fw=FRAME_W, fh=FRAME_H):
    os.makedirs(out_dir, exist_ok=True)
    atlas = Image.new("RGBA", (fw * COLS, fh * ROWS), (0, 0, 0, 0))
    manifest_states = []
    gifs_dir = os.path.join(out_dir, "gifs")
    os.makedirs(gifs_dir, exist_ok=True)

    for row, state in enumerate(STATE_ORDER):
        frames = states.get(state, [])
        if not frames:
            print(f"[WARN] no frames for {state}")
            continue
        durs = DURATIONS.get(state, [120] * len(frames))
        if len(durs) != len(frames):
            durs = durs[:len(frames)] or [120] * len(frames)

        # place into atlas
        for col, fr in enumerate(frames[:COLS]):
            fr = fr.resize((fw, fh), Image.LANCZOS) if fr.size != (fw, fh) else fr
            atlas.paste(fr, (col * fw, row * fh), fr)

        # export editable GIF
        save_gif(frames, os.path.join(gifs_dir, f"{slug}-{state}.gif"), durs)

        manifest_states.append({
            "name": state,
            "row": row,
            "frames": min(len(frames), COLS),
            "durations": durs,
        })

    atlas_path = os.path.join(out_dir, f"{slug}_atlas.png")
    atlas.save(atlas_path, "PNG")

    manifest = {
        "name": name,
        "version": "1.0",
        "frame_width": fw,
        "frame_height": fh,
        "columns": COLS,
        "states": manifest_states,
        "slug": slug,
    }
    manifest_path = os.path.join(out_dir, "pet.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    return atlas_path, manifest_path


def install(slug: str, atlas_path: str, manifest_path: str):
    dest = os.path.join(os.path.expanduser("~"), ".petdex", "pets", slug)
    os.makedirs(dest, exist_ok=True)
    with open(atlas_path, "rb") as src, open(os.path.join(dest, "spritesheet.png"), "wb") as dst:
        dst.write(src.read())
    with open(manifest_path, "rb") as src, open(os.path.join(dest, "pet.json"), "wb") as dst:
        dst.write(src.read())
    print(f"[install] -> {dest}")
    return dest


# --------------------------------------------------------------------------
# Demo character (placeholder so the pipeline is self-testable)
# --------------------------------------------------------------------------
def make_demo_image() -> Image.Image:
    img = Image.new("RGBA", (FRAME_W, FRAME_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # body (PCB green rounded rect)
    d.rounded_rectangle([46, 70, 146, 188], radius=26, fill=(34, 139, 34, 255),
                        outline=(20, 90, 20, 255), width=3)
    # chest chip
    d.rectangle([78, 110, 114, 140], fill=(25, 25, 25, 255))
    d.rectangle([82, 114, 92, 136], fill=(212, 175, 55, 255))
    d.rectangle([100, 114, 110, 136], fill=(212, 175, 55, 255))
    # eyes
    for cx in (82, 110):
        d.ellipse([cx - 9, 84, cx + 9, 102], fill=(255, 255, 255, 255))
        d.ellipse([cx - 4, 88, cx + 4, 96], fill=(15, 15, 15, 255))
    # antennae
    d.line([96, 70, 96, 52], fill=(20, 90, 20, 255), width=3)
    d.ellipse([91, 44, 101, 54], fill=(250, 120, 40, 255))
    return img


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", help="Path to static character PNG (transparent bg)")
    ap.add_argument("--slug", required=True, help="Pet slug, e.g. pcb-shiba")
    ap.add_argument("--name", default=None, help="Display name (default = slug)")
    ap.add_argument("--output", default=None, help="Output dir (default: ./output/<slug>)")
    ap.add_argument("--install", action="store_true", help="Install into ~/.petdex/pets/<slug>/")
    ap.add_argument("--make-demo", action="store_true", help="Generate a placeholder mascot")
    args = ap.parse_args()

    name = args.name or args.slug
    out_dir = args.output or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "..", "output", args.slug)

    if args.make_demo and not args.image:
        base = fit_char(make_demo_image())
    elif args.image:
        base = fit_char(Image.open(args.image))
    else:
        print("ERROR: provide --image <png> or --make-demo", file=sys.stderr)
        sys.exit(1)

    print(f"[base] fitted character canvas {base.size}")
    states = build_states(base)
    states, fw, fh = tighten(states)
    print(f"[tighten] frame cropped to {fw}x{fh} (was {FRAME_W}x{FRAME_H}) — 窗口更贴合宠物")
    atlas_path, manifest_path = compose_atlas(states, args.slug, name, out_dir, fw=fw, fh=fh)
    size_kb = os.path.getsize(atlas_path) / 1024
    print(f"[ok] atlas {atlas_path} ({size_kb:.0f} KB) + pet.json + gifs/")

    if args.install:
        install(args.slug, atlas_path, manifest_path)


if __name__ == "__main__":
    main()
