#!/usr/bin/env python3
"""Generate appicon.icns for Download Organizer.

Modern minimalist mark: a purple squircle with a white download arrow
dropping into an open tray. Rendered at 4x then downsampled for clean edges.
Run:  ./.venv/bin/python make_icon.py
"""
import math, subprocess, shutil
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

APP_DIR = Path(__file__).resolve().parent
OUT_ICNS = APP_DIR / "Download Organizer.app" / "Contents" / "Resources" / "appicon.icns"

S = 1024          # final canvas
SS = 4            # supersample factor
W = S * SS

PURPLE_TOP = (143, 107, 255)     # #8f6bff
PURPLE_BOT = (95, 61, 240)       # #5f3df0


def lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def rounded_mask(size, radius):
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return m


def main():
    canvas = Image.new("RGBA", (W, W), (0, 0, 0, 0))

    # squircle geometry (leave transparent margin, macOS style)
    margin = int(W * 0.085)
    box = W - 2 * margin
    radius = int(box * 0.2237)

    # vertical gradient tile
    grad = Image.new("RGBA", (box, box), (0, 0, 0, 0))
    gp = grad.load()
    for y in range(box):
        c = lerp(PURPLE_TOP, PURPLE_BOT, y / box)
        for x in range(box):
            gp[x, y] = (c[0], c[1], c[2], 255)
    grad.putalpha(rounded_mask(box, radius))

    # soft drop shadow
    shadow = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    sm = rounded_mask(box, radius)
    sh_layer = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    sh_solid = Image.new("RGBA", (box, box), (20, 12, 60, 150))
    sh_solid.putalpha(sm.point(lambda v: int(v * 0.55)))
    sh_layer.paste(sh_solid, (margin, margin + int(W * 0.018)), sh_solid)
    sh_layer = sh_layer.filter(ImageFilter.GaussianBlur(W * 0.022))
    canvas = Image.alpha_composite(canvas, sh_layer)

    # squircle body
    body = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    body.paste(grad, (margin, margin), grad)
    canvas = Image.alpha_composite(canvas, body)

    # top glossy highlight
    gloss = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    gd = ImageDraw.Draw(gloss)
    gh = int(box * 0.5)
    gd.rounded_rectangle([margin, margin, margin + box, margin + gh],
                         radius=radius, fill=(255, 255, 255, 30))
    gmask = Image.new("L", (W, W), 0)
    ImageDraw.Draw(gmask).rounded_rectangle(
        [margin, margin, margin + box - 1, margin + box - 1], radius=radius, fill=255)
    gloss.putalpha(Image.composite(gloss.getchannel("A"),
                                   Image.new("L", (W, W), 0), gmask))
    canvas = Image.alpha_composite(canvas, gloss)

    # ---- download glyph (white) ----
    g = ImageDraw.Draw(canvas)
    cx = W // 2
    white = (255, 255, 255, 255)

    # arrow shaft
    shaft_w = int(box * 0.115)
    shaft_top = margin + int(box * 0.235)
    shaft_bot = margin + int(box * 0.55)
    g.rounded_rectangle([cx - shaft_w // 2, shaft_top, cx + shaft_w // 2, shaft_bot],
                        radius=shaft_w // 2, fill=white)

    # arrowhead (triangle)
    head_w = int(box * 0.30)
    head_h = int(box * 0.22)
    head_top = shaft_bot - int(box * 0.02)
    g.polygon([(cx - head_w // 2, head_top),
               (cx + head_w // 2, head_top),
               (cx, head_top + head_h)], fill=white)

    # tray / open folder destination
    tray_w = int(box * 0.52)
    tray_th = int(box * 0.085)
    tray_y = margin + int(box * 0.80)
    tray_x0 = cx - tray_w // 2
    tray_x1 = cx + tray_w // 2
    # left wall
    g.rounded_rectangle([tray_x0, tray_y - int(box * 0.14), tray_x0 + tray_th, tray_y],
                        radius=tray_th // 2, fill=white)
    # right wall
    g.rounded_rectangle([tray_x1 - tray_th, tray_y - int(box * 0.14), tray_x1, tray_y],
                        radius=tray_th // 2, fill=white)
    # base
    g.rounded_rectangle([tray_x0, tray_y - tray_th, tray_x1, tray_y],
                        radius=tray_th // 2, fill=white)

    # downsample
    icon = canvas.resize((S, S), Image.LANCZOS)

    # build iconset
    iconset = APP_DIR / "AppIcon.iconset"
    if iconset.exists():
        shutil.rmtree(iconset)
    iconset.mkdir()
    specs = [(16, 1), (16, 2), (32, 1), (32, 2), (128, 1), (128, 2),
             (256, 1), (256, 2), (512, 1), (512, 2)]
    for px, scale in specs:
        size = px * scale
        im = icon.resize((size, size), Image.LANCZOS)
        suffix = "" if scale == 1 else "@2x"
        im.save(iconset / f"icon_{px}x{px}{suffix}.png")

    OUT_ICNS.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(OUT_ICNS)],
                   check=True)
    shutil.rmtree(iconset)
    # also keep a 1024 preview png
    icon.save(APP_DIR / "appicon_preview.png")
    print("wrote", OUT_ICNS)


if __name__ == "__main__":
    main()
