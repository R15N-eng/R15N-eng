"""Generates every SVG used by the profile README.

Text is converted to paths, so it renders identically on every device
(GitHub serves SVGs as images, which cannot load web fonts).

Usage (from the repository root):
    pip install fonttools uharfbuzz
    npm install --no-save @fontsource/bricolage-grotesque @fontsource/ibm-plex-sans
    python tools/build_assets.py

Fonts: Bricolage Grotesque and IBM Plex Sans (SIL Open Font License).
"""
import io
import random
from pathlib import Path
from xml.sax.saxutils import escape

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets"
FONT_DIRS = [ROOT / "node_modules", Path.cwd() / "node_modules"]

THEMES = {
    "dark": dict(surface="#0F1A30", panel="#17254200", card="#18274A", line="#314470",
                 ink="#EEF3FC", muted="#A9B8D4", faint="#3D517C", accent="#FFB454",
                 on_accent="#0F1A30", mark="#FFB45455", base="#7F93BC"),
    "light": dict(surface="#EEF2F9", panel="#FFFFFF00", card="#FFFFFF", line="#C5D0E4",
                  ink="#101A30", muted="#475775", faint="#B3C0D9", accent="#9A5300",
                  on_accent="#FFFFFF", mark="#FFC56B66", base="#7586A8"),
}


def _find_font(family, weight):
    rel = Path("@fontsource") / family / "files" / f"{family}-latin-{weight}-normal.woff"
    for d in FONT_DIRS:
        if (d / rel).exists():
            return d / rel
    raise SystemExit(f"Font not found: {rel}. See the usage notes at the top of this file.")


class Font:
    def __init__(self, family, weight):
        self.tt = TTFont(_find_font(family, weight))
        self.tt.flavor = None
        buf = io.BytesIO()
        self.tt.save(buf)
        self.hb = hb.Font(hb.Face(buf.getvalue()))
        self.upem = self.tt["head"].unitsPerEm
        self.glyphs = self.tt.getGlyphSet()
        self.order = self.tt.getGlyphOrder()

    def _shape(self, s):
        b = hb.Buffer()
        b.add_str(s)
        b.guess_segment_properties()
        hb.shape(self.hb, b)
        return b.glyph_infos, b.glyph_positions

    def width(self, s, size):
        return sum(p.x_advance for p in self._shape(s)[1]) * size / self.upem

    def path(self, s, x, y, size, fill, anchor="start", max_width=None):
        w = self.width(s, size)
        if max_width is not None and w > max_width:
            raise SystemExit(f"Text overflows ({w:.0f}px > {max_width}px): {s!r}")
        x -= {"start": 0, "middle": w / 2, "end": w}[anchor]
        scale = size / self.upem
        infos, positions = self._shape(s)
        pen_x, parts = 0, []
        for info, pos in zip(infos, positions):
            name = self.order[info.codepoint]
            if name == ".notdef":
                raise SystemExit(f"Missing glyph in {s!r}")
            pen = SVGPathPen(self.glyphs)
            self.glyphs[name].draw(pen)
            d = pen.getCommands()
            if d:
                parts.append(f'<path transform="translate({pen_x + pos.x_offset} {pos.y_offset})" d="{d}"/>')
            pen_x += pos.x_advance
        return (f'<g fill="{fill}" transform="translate({x:.1f} {y:.1f}) scale({scale:.5f} {-scale:.5f})">'
                + "".join(parts) + "</g>")


DISPLAY = Font("bricolage-grotesque", 700)
BODY = Font("ibm-plex-sans", 400)
STRONG = Font("ibm-plex-sans", 600)


def svg(w, h, title, body, theme, css=""):
    t = THEMES[theme]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img">'
            f"<title>{escape(title)}</title>"
            + (f"<style>{css}</style>" if css else "")
            + f'<rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="14" fill="{t["surface"]}" stroke="{t["line"]}"/>'
            + body + "</svg>")


def rect(x, y, w, h, fill, stroke="none", rx=6, extra=""):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" {extra}/>'


# --------------------------------------------------------------- header graph
SCORES = [92, 85, 78, 74, 66, 61, 55, 47, 40]
CAPACITY = [2, 2, 2, 1]          # 7 seats for 9 applicants


def deferred_acceptance(prefs):
    """Applicant-proposing deferred acceptance, in synchronous rounds.

    Returns (events, held). events maps each proposed edge to
    [round proposed, round rejected or None].
    """
    nxt = [0] * len(prefs)
    held = [[] for _ in CAPACITY]
    free = list(range(len(prefs)))
    events, rnd = {}, 0
    while True:
        proposers = [a for a in free if nxt[a] < len(prefs[a])]
        if not proposers:
            return events, held, rnd
        rnd += 1
        for a in proposers:
            p = prefs[a][nxt[a]]
            nxt[a] += 1
            held[p].append(a)
            events[(a, p)] = [rnd, None]
            free.remove(a)
        for p, cap in enumerate(CAPACITY):
            held[p].sort(key=lambda a: -SCORES[a])
            for a in held[p][cap:]:
                events[(a, p)][1] = rnd
                free.append(a)
            held[p] = held[p][:cap]


def pick_instance():
    """First seed that gives a readable run: 4 rounds and some displacement."""
    for seed in range(5000):
        r = random.Random(seed)
        prefs = [r.sample(range(4), r.choice([2, 3])) for _ in SCORES]
        events, held, rounds = deferred_acceptance(prefs)
        displaced = sum(1 for s, e in events.values() if e is not None and e > s)
        if rounds == 4 and displaced >= 2 and sum(map(len, held)) == 7:
            return prefs, events, held
    raise SystemExit("No suitable instance found")


def check_stable(prefs, held):
    """No applicant prefers a program that has a free seat or a lower-scored holder."""
    match = {a: p for p, hs in enumerate(held) for a in hs}
    for a, pl in enumerate(prefs):
        for p in pl:
            if match.get(a) == p:
                break
            assert len(held[p]) == CAPACITY[p], "free seat that should be taken"
            assert all(SCORES[b] > SCORES[a] for b in held[p]), "blocking pair"


def graph(theme, x0, y0, w, h, r, label_size, num_size):
    t = THEMES[theme]
    prefs, events, held = pick_instance()
    check_stable(prefs, held)
    ax, px = x0 + r, x0 + w - 96
    ay = [y0 + i * h / (len(SCORES) - 1) for i in range(len(SCORES))]
    py = [y0 + h * f for f in (0.08, 0.37, 0.66, 0.93)]
    step = 1.1
    css, edges = [], []
    for i, ((a, p), (start, end)) in enumerate(sorted(events.items(), key=lambda kv: kv[1][0])):
        final = end is None
        mid = (ax + px) / 2
        d = f"M{ax + r:.0f} {ay[a]:.1f} C{mid:.0f} {ay[a]:.1f} {mid:.0f} {py[p]:.1f} {px:.0f} {py[p]:.1f}"
        style = (f'stroke="{t["accent"]}" stroke-width="3"' if final
                 else f'stroke="{t["faint"]}" stroke-width="1.5" stroke-dasharray="4 6"')
        edges.append((final, f'<path class="e{i}" d="{d}" fill="none" {style}/>'))
        t0 = 0.4 + (start - 1) * step
        if final:
            css.append(f".e{i}{{animation:in .6s ease-out {t0:.2f}s backwards}}")
        else:
            t1 = 0.4 + (end - 1) * step + 0.8
            total = t1 + 0.4
            a0, a1, a2 = 100 * t0 / total, 100 * min(t0 + .35, t1) / total, 100 * t1 / total
            css.append(
                f"@keyframes k{i}{{0%,{a0:.1f}%{{opacity:0;stroke:{t['ink']}}}"
                f"{a1:.1f}%,{a2:.1f}%{{opacity:1;stroke:{t['ink']};stroke-dasharray:none}}"
                f"100%{{opacity:1;stroke:{t['faint']}}}}}"
                f".e{i}{{animation:k{i} {total:.2f}s linear both}}")
    css.append("@keyframes in{from{opacity:0}to{opacity:1}}")
    css.append("@media (prefers-reduced-motion:reduce){path{animation:none!important}}")
    out = [e for _, e in sorted(edges, key=lambda e: e[0])]
    matched = {a for hs in held for a in hs}
    for a, s in enumerate(SCORES):
        on = a in matched
        out.append(f'<circle cx="{ax}" cy="{ay[a]:.1f}" r="{r}" fill="{t["card"]}" '
                   f'stroke="{t["accent"] if on else t["base"]}" stroke-width="{2.5 if on else 1.5}"/>')
        out.append(STRONG.path(str(s), ax, ay[a] + num_size * 0.36, num_size,
                               t["ink"] if on else t["muted"], "middle"))
    for p, cap in enumerate(CAPACITY):
        out.append(rect(px, py[p] - 24, 17 + cap * 35, 48, t["card"], t["line"], 8))
        for s in range(cap):
            fill = t["accent"] if s < len(held[p]) else "none"
            out.append(rect(px + 11 + s * 35, py[p] - 13, 26, 26, fill, t["accent"], 4))
    out.append(BODY.path("applicants, by score", x0, y0 - r - 16, label_size, t["muted"]))
    out.append(BODY.path("seats", px + 42, y0 - r - 16, label_size, t["muted"], "middle"))
    return "".join(out), "".join(css)


HEADER_TITLE = ("Raimundo Nonato. Software that shows its work. Computer Engineering at IME. "
                "Graphic: a deferred-acceptance run on a made-up example, 9 applicants and 7 seats.")


def header(theme, mobile):
    t = THEMES[theme]
    b = []
    if not mobile:
        w, h = 1200, 460
        b.append(DISPLAY.path("Raimundo", 56, 126, 88, t["ink"], max_width=540))
        b.append(DISPLAY.path("Nonato", 56, 214, 88, t["ink"]))
        b.append(DISPLAY.path("Software that shows its work.", 58, 286, 35, t["accent"], max_width=540))
        b.append(BODY.path("Computer Engineering student at IME", 58, 340, 24, t["muted"]))
        b.append(BODY.path("Rio de Janeiro, Brazil", 58, 374, 24, t["muted"]))
        g, css = graph(theme, 690, 70, 450, 312, 17, 18, 15)
        b.append(g)
        b.append(BODY.path("Deferred acceptance, run on a made-up example", 1140, 434, 17, t["muted"], "end"))
    else:
        w, h = 600, 830
        b.append(DISPLAY.path("Raimundo", 40, 100, 80, t["ink"]))
        b.append(DISPLAY.path("Nonato", 40, 180, 80, t["ink"]))
        b.append(DISPLAY.path("Software that shows its work.", 42, 244, 35, t["accent"], max_width=520))
        b.append(BODY.path("Computer Engineering student at IME", 42, 294, 26, t["muted"], max_width=520))
        b.append(BODY.path("Rio de Janeiro, Brazil", 42, 330, 26, t["muted"]))
        g, css = graph(theme, 56, 420, 488, 330, 17, 23, 16)
        b.append(g)
        b.append(BODY.path("Deferred acceptance on a made-up example", 300, 804, 23, t["muted"], "middle", 540))
    return svg(w, h, HEADER_TITLE, "".join(b), theme, css)


# --------------------------------------------------------------- Luneta cover
LUNETA_TITLE = ("How Luneta works, illustrated: a rule is shown next to the exact sentence of the call "
                "that proves it. A check without AI confirms the quote exists; otherwise the rule is marked unconfirmed.")


def check_icon(x, y, color, on):
    return (f'<circle cx="{x}" cy="{y}" r="14" fill="{color}"/>'
            f'<path d="M{x-6} {y} l4 5 l8 -10" fill="none" stroke="{on}" stroke-width="3" '
            'stroke-linecap="round" stroke-linejoin="round"/>')


def luneta(theme, mobile):
    t = THEMES[theme]
    b = []

    def page(x, y, w, fs):
        out = [rect(x, y, w, 232, t["card"], t["line"], 8)]
        out.append(BODY.path("Funding call, illustrative excerpt", x + 24, y + 38, fs - 4, t["muted"]))
        for i, frac in enumerate((0.86, 0.70)):
            out.append(rect(x + 24, y + 62 + i * 22, (w - 48) * frac, 9, t["faint"], rx=4))
        s1, s2 = "Applicants must hold a PhD and keep", "an up-to-date research CV."
        for i, s in enumerate((s1, s2)):
            yy = y + 134 + i * 34
            out.append(rect(x + 20, yy - fs, BODY.width(s, fs) + 8, fs + 10, t["mark"], rx=3))
            out.append(BODY.path(s, x + 24, yy, fs, t["ink"], max_width=w - 40))
        out.append(rect(x + 24, y + 200, (w - 48) * 0.78, 9, t["faint"], rx=4))
        return "".join(out)

    def cards(x, y, w, fs):
        out = [rect(x, y, w, 132, t["card"], t["accent"], 8, 'stroke-width="2"')]
        out.append(STRONG.path("Rule: the applicant needs a PhD", x + 24, y + 46, fs + 1, t["ink"], max_width=w - 40))
        out.append(check_icon(x + 38, y + 91, t["accent"], t["on_accent"]))
        out.append(BODY.path("Quote found word for word", x + 62, y + 99, fs, t["ink"], max_width=w - 74))
        out.append(rect(x, y + 148, w, 84, "none", t["base"], 8, 'stroke-dasharray="6 6"'))
        out.append(BODY.path("No matching quote in the document?", x + 24, y + 182, fs - 2, t["muted"], max_width=w - 40))
        out.append(STRONG.path("The rule is marked unconfirmed", x + 24, y + 214, fs - 1, t["ink"], max_width=w - 40))
        return "".join(out)

    if not mobile:
        w, h = 1200, 440
        b.append(DISPLAY.path("Each rule sits next to the sentence it came from", 48, 74, 40, t["ink"], max_width=1100))
        b.append(page(48, 112, 520, 24))
        b.append(f'<path d="M570 258 C610 258 600 178 646 178" fill="none" stroke="{t["accent"]}" stroke-width="3"/>')
        b.append(f'<circle cx="646" cy="178" r="6" fill="{t["accent"]}"/>')
        b.append(cards(646, 112, 506, 24))
        b.append(BODY.path("Official PDF, converted to text, read by a language model, then checked by code with no AI",
                           600, 398, 22, t["muted"], "middle", 1100))
    else:
        w, h = 600, 780
        b.append(DISPLAY.path("Each rule sits next to the", 32, 66, 42, t["ink"], max_width=540))
        b.append(DISPLAY.path("sentence it came from", 32, 116, 42, t["ink"], max_width=540))
        b.append(page(32, 150, 536, 25))
        b.append(f'<path d="M300 382 L300 424" stroke="{t["accent"]}" stroke-width="3"/>')
        b.append(cards(32, 424, 536, 26))
        for i, s in enumerate(("Official PDF, converted to text, read by",
                               "a language model, then checked by", "code with no AI")):
            b.append(BODY.path(s, 300, 696 + i * 32, 24, t["muted"], "middle", 540))
    return svg(w, h, LUNETA_TITLE, "".join(b), theme)


# -------------------------------------------------------- Match Carioca cover
MC_ROWS = [("Priority group", 78.0, 93.5), ("Everyone else", 76.8, 59.2)]
MC_TITLE = ("Match Carioca simulation on anonymized 2025 data. Share of children placed: priority group "
            "78.0% in the real process and 93.5% with deferred acceptance; everyone else 76.8% and 59.2%. "
            "Total placements 48,680 and 47,768. Hackathon prototype, not an official city service.")


def match(theme, mobile):
    t = THEMES[theme]
    b = []

    def bar(x, y, maxw, value, color, fs, label_color):
        bw = maxw * value / 100
        return (rect(x, y, maxw, 30, t["card"], rx=4) + rect(x, y, round(bw, 1), 30, color, rx=4)
                + STRONG.path(f"{value:.1f}%", x + maxw + 16, y + 24, fs, label_color))

    def legend(x, y, fs):
        return (rect(x, y - 16, 18, 18, t["base"], rx=3)
                + BODY.path("Real 2025 process", x + 28, y, fs, t["muted"])
                + rect(x + 36 + BODY.width("Real 2025 process", fs) + 14, y - 16, 18, 18, t["accent"], rx=3)
                + BODY.path("Deferred acceptance", x + 78 + BODY.width("Real 2025 process", fs), y, fs, t["muted"]))

    if not mobile:
        w, h = 1200, 440
        b.append(DISPLAY.path("Priority-group placements rose. Others fell.", 48, 74, 40, t["ink"], max_width=1100))
        b.append(legend(48, 122, 22))
        for i, (name, before, after) in enumerate(MC_ROWS):
            y = 156 + i * 100
            b.append(STRONG.path(name, 48, y + 46, 26, t["ink"]))
            b.append(bar(290, y, 760, before, t["base"], 24, t["muted"]))
            b.append(bar(290, y + 40, 760, after, t["accent"], 24, t["ink"]))
        b.append(BODY.path("Share of children placed. Total placements went from 48,680 to 47,768.",
                           48, 380, 22, t["ink"], max_width=1100))
        b.append(BODY.path("Simulation on anonymized data, not official statistics. Hackathon prototype, not a city service.",
                           48, 414, 20, t["muted"], max_width=1100))
    else:
        w, h = 600, 780
        b.append(DISPLAY.path("Priority-group placements", 32, 66, 40, t["ink"], max_width=540))
        b.append(DISPLAY.path("rose. Others fell.", 32, 116, 40, t["ink"], max_width=540))
        b.append(BODY.path("Share of children placed", 32, 168, 25, t["muted"]))
        b.append(rect(32, 192, 18, 18, t["base"], rx=3) + BODY.path("Real 2025 process", 60, 209, 24, t["muted"]))
        b.append(rect(32, 226, 18, 18, t["accent"], rx=3) + BODY.path("Deferred acceptance", 60, 243, 24, t["muted"]))
        for i, (name, before, after) in enumerate(MC_ROWS):
            y = 286 + i * 150
            b.append(STRONG.path(name, 32, y + 20, 28, t["ink"]))
            b.append(bar(32, y + 38, 420, before, t["base"], 27, t["muted"]))
            b.append(bar(32, y + 78, 420, after, t["accent"], 27, t["ink"]))
        b.append(STRONG.path("Total placements: 48,680 to 47,768", 32, 628, 26, t["ink"], max_width=540))
        for i, s in enumerate(("Simulation on anonymized data, not",
                               "official statistics. Hackathon",
                               "prototype, not a city service.")):
            b.append(BODY.path(s, 32, 678 + i * 33, 24, t["muted"], max_width=540))
    return svg(w, h, MC_TITLE, "".join(b), theme)


# ------------------------------------------------------------ contact buttons
def button(theme, label):
    t = THEMES[theme]
    w = round(STRONG.width(label, 20) + 56)
    body = STRONG.path(label, w / 2, 29, 20, t["ink"], "middle")
    body += rect(w / 2 - 18, 36, 36, 3, t["accent"], rx=1)
    return svg(w, 48, label, body, theme)


def main():
    OUT.mkdir(exist_ok=True)
    for theme in THEMES:
        for name, fn in (("header", header), ("luneta", luneta), ("match-carioca", match)):
            (OUT / f"{name}-{theme}.svg").write_text(fn(theme, False), encoding="utf-8")
            (OUT / f"{name}-mobile-{theme}.svg").write_text(fn(theme, True), encoding="utf-8")
        for label in ("LinkedIn", "Email"):
            (OUT / f"button-{label.lower()}-{theme}.svg").write_text(button(theme, label), encoding="utf-8")
    prefs, events, held = pick_instance()
    check_stable(prefs, held)
    print("OK:", len(list(OUT.glob("*.svg"))), "files; header matching is stable")


if __name__ == "__main__":
    main()
