"""Generate ShabBOT brand assets (robot icon tiles, wordmark logos, sidebar icon) from vector shapes.

Run:  DYLD_FALLBACK_LIBRARY_PATH=/usr/local/lib uvx --with cairosvg --with fonttools python assets/build_brand.py

Outputs
  assets/*.svg, assets/*.png                      sources and previews
  custom_components/shabbot/brand/*.png           shown by Home Assistant (Integrations page, Marketplace)
  custom_components/shabbot/static/shabbot-icons.js  "shabbot:logo" icon for the HA sidebar
  frontend/src/brand.ts                           icon used in the panel header

The wordmark uses Fredoka SemiBold (SIL Open Font License), converted to outlines so no font is needed at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import urllib.request

import cairosvg
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
BRAND = ROOT / "custom_components/shabbot/brand"
STATIC = ROOT / "custom_components/shabbot/static"
FONT_URL = "https://github.com/google/fonts/raw/main/ofl/fredoka/Fredoka%5Bwdth,wght%5D.ttf"
FONT_CACHE = Path.home() / ".cache/shabbot/Fredoka.ttf"

NAVY = "#0c1935"
BLUE = "#4680ec"
BALL = "#4d9bf9"
CREAM = "#fcf8f5"

# Robot geometry, in a 720 x 600 design space.
ROBOT_BOX = (50, 30, 650, 560)  # x, y, w, h incl. strokes


@dataclass
class Style:
    ink: str  # head, ears, kippah outline, antenna stem
    visor: str
    eye: str
    star: str
    kippah_fill: str
    ball: str = BALL
    outline: str | None = None  # stroke around white shapes (for light backgrounds)
    ink_gradient: tuple[str, str] | None = None


def robot(s: Style, uid: str) -> str:
    defs = ""
    ink = s.ink
    if s.ink_gradient:
        defs = (f'<defs><linearGradient id="g{uid}" x1="0" y1="0" x2="0" y2="1">'
                f'<stop offset="0" stop-color="{s.ink_gradient[0]}"/><stop offset="1" stop-color="{s.ink_gradient[1]}"/>'
                f"</linearGradient></defs>")
        ink = f"url(#g{uid})"
    ol = f' stroke="{s.outline}" stroke-width="14" stroke-linejoin="round"' if s.outline else ""
    stem = s.outline or s.ink
    tri = []
    for start in (-90, 90):
        pts = [(377 + 37 * math.cos(math.radians(start + k * 120)), 101 + 37 * math.sin(math.radians(start + k * 120)))
               for k in range(3)]
        tri.append("M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + " Z")
    return f"""{defs}
  <line x1="638" y1="170" x2="638" y2="300" stroke="{stem}" stroke-width="12" stroke-linecap="round"/>
  <circle cx="638" cy="140" r="31" fill="{s.ball}"/>
  <path d="M128,300 H96 A34,34 0 0 0 62,334 V438 A34,34 0 0 0 96,472 H128 Z" fill="{ink}"{ol}/>
  <path d="M617,300 H649 A34,34 0 0 1 683,334 V438 A34,34 0 0 1 649,472 H617 Z" fill="{ink}"{ol}/>
  <rect x="140" y="190" width="465" height="372" rx="125" fill="{ink}"{ol}/>
  <rect x="185" y="272" width="375" height="218" rx="92" fill="{s.visor}"/>
  <path d="M236,414 A44,44 0 0 1 324,414 M436,414 A44,44 0 0 1 524,414" fill="none" stroke="{s.eye}"
        stroke-width="18" stroke-linecap="round"/>
  <path d="M206,168 A171,124 0 0 1 548,168 Z" fill="{s.kippah_fill}" stroke="{stem if s.outline else ink}"
        stroke-width="14" stroke-linejoin="round"/>
  <path d="{' '.join(tri)}" fill="none" stroke="{s.star}" stroke-width="8" stroke-linejoin="round"/>"""


def place(inner: str, box: tuple[float, float, float, float], target: tuple[float, float, float, float]) -> str:
    """Scale/translate a design-space group so `box` fits centered in `target`."""
    bx, by, bw, bh = box
    tx, ty, tw, th = target
    s = min(tw / bw, th / bh)
    ox = tx + (tw - bw * s) / 2 - bx * s
    oy = ty + (th - bh * s) / 2 - by * s
    return f'<g transform="translate({ox:.2f},{oy:.2f}) scale({s:.5f})">{inner}</g>'


def svg(w: float, h: float, body: str) -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:g}" height="{h:g}" viewBox="0 0 {w:g} {h:g}">{body}</svg>\n'


# ---------------------------------------------------------------- styles

ON_DARK = Style(ink=CREAM, visor=NAVY, eye=CREAM, star=CREAM, kippah_fill="none")
ON_LIGHT = Style(ink="#ffffff", visor=NAVY, eye="#a9c8ff", star=NAVY, kippah_fill="#ffffff", outline=NAVY)
GLOW = Style(ink="#4c83e5", visor="#071124", eye="#9cc6ff", star="#cfe0ff", kippah_fill="none",
             ink_gradient=("#6aa2f8", "#3567cf"))

TILES = {
    "cream": ("#f6e9d9", ON_LIGHT),
    "blue": ("#173d6b", Style(ink=CREAM, visor=NAVY, eye=CREAM, star=CREAM, kippah_fill="none")),
    "dark": ("#091320", GLOW),
}


def tile(name: str, size: int = 512) -> str:
    bg, style = TILES[name]
    pad = size * 0.13
    body = f'<rect width="{size}" height="{size}" rx="{size * 0.22:.1f}" fill="{bg}"/>'
    body += place(robot(style, name), ROBOT_BOX, (pad, pad * 1.05, size - 2 * pad, size - 2 * pad))
    return svg(size, size, body)


# ---------------------------------------------------------------- wordmark


def font() -> TTFont:
    if not FONT_CACHE.exists():
        FONT_CACHE.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(FONT_URL, FONT_CACHE)  # noqa: S310 - fixed https URL
    f = TTFont(FONT_CACHE)
    return instantiateVariableFont(f, {"wght": 600, "wdth": 100})


def wordmark(shab: str, f: TTFont, size: float = 200) -> tuple[str, float, float]:
    """'Shab' + 'B' + robot-O + 'T'. Returns (svg body, width, height); baseline at y=size*0.92."""
    gs = f.getGlyphSet()
    cmap = f.getBestCmap()
    upm = f["head"].unitsPerEm
    scale = size / upm
    baseline = size * 0.92
    x = 0.0
    parts: list[str] = []
    for ch in "ShabBOT":
        gname = cmap[ord(ch)]
        glyph = gs[gname]
        color = shab if ch in "Shab" else BLUE
        if ch == "O":
            # Robot face: ring + two dot eyes + antenna.
            cx = x + glyph.width * scale / 2
            cy = baseline - size * 0.355
            ro, ri = size * 0.36, size * 0.215
            parts.append(f'<path fill-rule="evenodd" fill="{BLUE}" d="M{cx - ro:.1f},{cy:.1f} a{ro:.1f},{ro:.1f} 0 1 0 {2 * ro:.1f},0 '
                         f'a{ro:.1f},{ro:.1f} 0 1 0 {-2 * ro:.1f},0 Z M{cx - ri:.1f},{cy:.1f} a{ri:.1f},{ri:.1f} 0 1 0 {2 * ri:.1f},0 '
                         f'a{ri:.1f},{ri:.1f} 0 1 0 {-2 * ri:.1f},0 Z"/>')
            for dx in (-0.085, 0.085):
                parts.append(f'<circle cx="{cx + dx * size:.1f}" cy="{cy:.1f}" r="{size * 0.045:.1f}" fill="{BLUE}"/>')
            top = cy - ro
            parts.append(f'<line x1="{cx:.1f}" y1="{top:.1f}" x2="{cx:.1f}" y2="{top - size * 0.12:.1f}" stroke="{BLUE}" '
                         f'stroke-width="{size * 0.05:.1f}" stroke-linecap="round"/>')
            parts.append(f'<circle cx="{cx:.1f}" cy="{top - size * 0.15:.1f}" r="{size * 0.06:.1f}" fill="{BLUE}"/>')
            x += glyph.width * scale
            continue
        pen = SVGPathPen(gs)
        glyph.draw(TransformPen(pen, (scale, 0, 0, -scale, x, baseline)))
        parts.append(f'<path fill="{color}" d="{pen.getCommands()}"/>')
        x += glyph.width * scale
        if ch == "b":
            x += size * 0.02  # breathing room between "Shab" and "BOT"
    return "".join(parts), x, size * 1.08


def stacked_logo(dark: bool, f: TTFont) -> tuple[str, float, float]:
    shab = CREAM if dark else NAVY
    words, ww, wh = wordmark(shab, f)
    style = ON_DARK if dark else ON_LIGHT
    rw = ww * 0.48
    rh = rw * ROBOT_BOX[3] / ROBOT_BOX[2]
    pad = 24
    w = ww + 2 * pad
    h = rh + wh + 2 * pad + 10
    body = place(robot(style, "dk" if dark else "lt"), ROBOT_BOX, ((w - rw) / 2, pad, rw, rh))
    body += f'<g transform="translate({pad},{pad + rh + 10})">{words}</g>'
    return body, w, h


def banner(f: TTFont) -> str:
    body, w, h = stacked_logo(True, f)
    W, H = 1280, 520
    out = f'<rect width="{W}" height="{H}" rx="28" fill="{NAVY}"/>'
    s = min((W - 160) / w, (H - 80) / h)
    out += f'<g transform="translate({(W - w * s) / 2:.1f},{(H - h * s) / 2:.1f}) scale({s:.4f})">{body}</g>'
    return svg(W, H, out)


# ---------------------------------------------------------------- monochrome sidebar icon


def rrect(x: float, y: float, w: float, h: float, r: float, cw: bool = True) -> str:
    if cw:
        return (f"M{x + r},{y}H{x + w - r}A{r},{r} 0 0 1 {x + w},{y + r}V{y + h - r}A{r},{r} 0 0 1 {x + w - r},{y + h}"
                f"H{x + r}A{r},{r} 0 0 1 {x},{y + h - r}V{y + r}A{r},{r} 0 0 1 {x + r},{y}Z")
    return (f"M{x + r},{y}A{r},{r} 0 0 0 {x},{y + r}V{y + h - r}A{r},{r} 0 0 0 {x + r},{y + h}H{x + w - r}"
            f"A{r},{r} 0 0 0 {x + w},{y + h - r}V{y + r}A{r},{r} 0 0 0 {x + w - r},{y}Z")


def mono_path() -> str:
    """One nonzero-winding path (holes run counter-clockwise), for <ha-svg-icon>."""
    d = [rrect(140, 190, 465, 372, 125)]  # head
    d.append(rrect(192, 276, 361, 210, 88, cw=False))  # visor hole
    for cx in (280, 480):  # smiling eyes: thick arcs with round caps
        cy, r, hw = 418, 44, 13
        ro, ri = r + hw, r - hw
        d.append(f"M{cx - ro},{cy}A{ro},{ro} 0 0 1 {cx + ro},{cy}A{hw},{hw} 0 0 1 {cx + ri},{cy}"
                 f"A{ri},{ri} 0 0 0 {cx - ri},{cy}A{hw},{hw} 0 0 1 {cx - ro},{cy}Z")
    d.append("M128,300H96A34,34 0 0 0 62,334V438A34,34 0 0 0 96,472H128Z")  # ears
    d.append("M617,300V472H649A34,34 0 0 0 683,438V334A34,34 0 0 0 649,300Z")
    d.append("M199,174A178,132 0 0 1 555,174Z")  # kippah (solid)
    pts = []  # Star of David cut out of the kippah (12-point outline, counter-clockwise)
    for k in range(12):
        ang = math.radians(-90 - k * 30)
        rad = 44 if k % 2 == 0 else 25.4
        pts.append((377 + rad * math.cos(ang), 104 + rad * math.sin(ang)))
    d.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + "Z")
    d.append(rrect(631, 160, 14, 140, 7))  # antenna
    d.append("M607,140A31,31 0 1 1 669,140A31,31 0 1 1 607,140Z")
    return "".join(d)


MONO_VIEWBOX = "32 -10 680 680"


# ---------------------------------------------------------------- write everything


def png(svg_text: str, path: Path, width: int | None = None, height: int | None = None) -> None:
    cairosvg.svg2png(bytestring=svg_text.encode(), write_to=str(path), output_width=width, output_height=height)


def main() -> None:
    ASSETS.mkdir(exist_ok=True)
    BRAND.mkdir(parents=True, exist_ok=True)
    STATIC.mkdir(parents=True, exist_ok=True)
    f = font()

    for name in TILES:
        s = tile(name)
        (ASSETS / f"icon-{name}.svg").write_text(s)
        png(s, ASSETS / f"icon-{name}.png", 512, 512)

    logos = {}
    for dark in (False, True):
        body, w, h = stacked_logo(dark, f)
        logos[dark] = (svg(round(w), round(h), body), w, h)
        (ASSETS / f"logo-{'dark' if dark else 'light'}.svg").write_text(logos[dark][0])
    (ASSETS / "banner.svg").write_text(banner(f))
    png(banner(f), ASSETS / "banner.png", 1280, 520)

    # Home Assistant brand images (Integrations page / Marketplace): icon 256 + @2x, logo shortest side 128-256.
    png(tile("blue"), BRAND / "icon.png", 256, 256)
    png(tile("blue"), BRAND / "icon@2x.png", 512, 512)
    png(tile("dark"), BRAND / "dark_icon.png", 256, 256)
    png(tile("dark"), BRAND / "dark_icon@2x.png", 512, 512)
    for dark, prefix in ((False, ""), (True, "dark_")):
        text, w, h = logos[dark]
        png(text, BRAND / f"{prefix}logo.png", round(256 * w / h), 256)
        png(text, BRAND / f"{prefix}logo@2x.png", round(512 * w / h), 512)

    mono = mono_path()
    (ASSETS / "icon-mono.svg").write_text(svg(680, 680, f'<path transform="translate(-32,10)" d="{mono}"/>'))
    png(svg(24, 24, f'<svg viewBox="{MONO_VIEWBOX}" width="24" height="24"><path d="{mono}"/></svg>'),
        ASSETS / "icon-mono-24.png", 96, 96)
    (STATIC / "shabbot-icons.js").write_text(
        "// Generated by assets/build_brand.py. Registers the \"shabbot:logo\" icon for the HA sidebar.\n"
        f'const ICONS = {{ logo: {{ path: "{mono}", viewBox: "{MONO_VIEWBOX}" }} }};\n'
        "window.customIcons = window.customIcons || {};\n"
        "window.customIcons.shabbot = {\n"
        "  getIcon: async (name) => ICONS[name] ?? ICONS.logo,\n"
        "  getIconList: async () => Object.keys(ICONS).map((name) => ({ name })),\n"
        "};\n"
        "// The sidebar may render before this script runs; <ha-icon> then gives up on the unknown\n"
        "// prefix and stays blank. Re-set the icon on any such element so it loads from this set.\n"
        "const repaint = (root) => {\n"
        "  for (const el of root.querySelectorAll('*')) {\n"
        "    if (el.localName === 'ha-icon' && el.icon?.startsWith('shabbot:') && (el._legacy || !el._path)) {\n"
        "      const icon = el.icon;\n"
        "      el._legacy = false;  // ha-icon never clears this flag for custom icon sets\n"
        "      el.icon = undefined;\n"
        "      setTimeout(() => { el.icon = icon; }, 0);\n"
        "    }\n"
        "    if (el.shadowRoot) repaint(el.shadowRoot);\n"
        "  }\n"
        "};\n"
        "for (const ms of [0, 500, 2000, 5000]) setTimeout(() => repaint(document), ms);\n"
    )
    (ROOT / "frontend/src/brand.ts").write_text(
        "// Generated by assets/build_brand.py.\n"
        f"export const ICON_SVG = {tile('blue', 64)!r};\n".replace("'", "`")
    )
    print("brand assets written")


if __name__ == "__main__":
    main()
