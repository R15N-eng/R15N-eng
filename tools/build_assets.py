"""Generates every SVG used by the profile README.

One monochrome system: panels share the same background, border, radius,
type scale and spacing, so the README reads as a single composition.
Text is converted to paths, so it renders the same on every device
(GitHub serves SVGs as images, which cannot load web fonts).

Usage (from the repository root):
    pip install fonttools uharfbuzz
    npm install --no-save @fontsource/bricolage-grotesque @fontsource/ibm-plex-sans simple-icons@16.38.1
    python tools/build_assets.py

Fonts: Bricolage Grotesque and IBM Plex Sans (SIL Open Font License).
Icons: Simple Icons (CC0-1.0). Logos remain trademarks of their owners.
"""
import io
import random
import re
from pathlib import Path
from xml.sax.saxutils import escape

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets"
MODULE_DIRS = [ROOT / "node_modules", Path.cwd() / "node_modules"]

# ------------------------------------------------------------------ palette
BG = "#0A0E15"       # Black 100: panel background
SURFACE = "#212631"  # Black 90: cards and surfaces
SECOND = "#373F4E"   # Black 80: secondary elements, panel border
LINE = "#4E576A"     # Black 70: quiet strokes
AUX = "#667085"      # Black 60: non-text details only (3.9:1 on Black 100)
WHITE = "#FFFFFF"    # White 100: titles and maximum emphasis
W90 = "#F0F1F5"      # highlights
W80 = "#E0E4EB"      # body text
W70 = "#D1D6E0"      # secondary text
W60 = "#BFC6D4"      # labels and captions (smallest text never goes darker)

DESK, PHONE = 880, 360
RADIUS, INNER = 20, 12


def _module(rel):
    for d in MODULE_DIRS:
        if (d / rel).exists():
            return d / rel
    raise SystemExit(f"Not found: node_modules/{rel}. See the usage notes at the top of this file.")


class Font:
    def __init__(self, family, weight):
        self.key = f"{family[0]}{weight}"
        self.tt = TTFont(_module(f"@fontsource/{family}/files/{family}-latin-{weight}-normal.woff"))
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

    def width(self, s, size, track=0.0):
        adv = sum(p.x_advance for p in self._shape(s)[1]) * size / self.upem
        return adv + track * size * max(len(s) - 1, 0)

    def fit(self, s, width, track=0.0):
        """Font size at which the string is exactly `width` wide."""
        return width / (self.width(s, 100, track) / 100)

    def wrap(self, s, size, max_width):
        lines, cur = [], ""
        for word in s.split():
            trial = f"{cur} {word}".strip()
            if cur and self.width(trial, size) > max_width:
                lines.append(cur)
                cur = word
            else:
                cur = trial
        return lines + [cur]

    def path(self, defs, s, x, y, size, fill, anchor="start", track=0.0, max_width=None):
        w = self.width(s, size, track)
        limit = max_width if max_width is not None else 10 ** 6
        if w > limit + 0.5:
            raise SystemExit(f"Text overflows ({w:.0f}px > {limit}px): {s!r}")
        x -= {"start": 0, "middle": w / 2, "end": w}[anchor]
        scale = size / self.upem
        infos, positions = self._shape(s)
        pen_x, parts = 0.0, []
        for info, pos in zip(infos, positions):
            name = self.order[info.codepoint]
            if name == ".notdef":
                raise SystemExit(f"Missing glyph in {s!r}")
            ref = f"{self.key}-{info.codepoint}"
            if ref not in defs:
                pen = SVGPathPen(self.glyphs)
                self.glyphs[name].draw(pen)
                d = pen.getCommands()
                defs[ref] = f'<path id="{ref}" d="{d}"/>' if d else ""
            if defs[ref]:
                parts.append(f'<use href="#{ref}" x="{pen_x + pos.x_offset:.0f}" y="{pos.y_offset}"/>')
            pen_x += pos.x_advance + track * self.upem
        return (f'<g fill="{fill}" transform="translate({x:.1f} {y:.1f}) scale({scale:.5f} {-scale:.5f})">'
                + "".join(parts) + "</g>")


XBOLD = Font("bricolage-grotesque", 800)
DISPLAY = Font("bricolage-grotesque", 600)
BODY = Font("ibm-plex-sans", 400)
MEDIUM = Font("ibm-plex-sans", 500)
STRONG = Font("ibm-plex-sans", 600)


class Canvas:
    def __init__(self, width, edge):
        self.w, self.edge, self.items, self.css, self.defs = width, edge, [], [], {}

    def add(self, *items):
        self.items.extend(items)

    def text(self, s, x, y, size, fill=W80, font=BODY, anchor="start", track=0.0, max_width=None):
        if max_width is None:
            max_width = {"start": self.w - self.edge - x, "end": x - self.edge,
                         "middle": 2 * min(x - self.edge, self.w - self.edge - x)}[anchor]
        self.add(font.path(self.defs, s, x, y, size, fill, anchor, track, max_width))

    def para(self, s, x, y, size, width, leading, fill=W80, font=BODY):
        """Wrapped text. Returns the y of the line after the last one."""
        for line in font.wrap(s, size, width):
            self.text(line, x, y, size, fill, font, max_width=width)
            y += leading
        return y

    def rule(self, y, x1=None, x2=None, color=SURFACE):
        x1 = self.edge if x1 is None else x1
        x2 = self.w - self.edge if x2 is None else x2
        self.add(f'<path d="M{x1} {y} H{x2}" stroke="{color}" stroke-width="1"/>')

    def pill(self, s, x, y, size=14, anchor="end"):
        w = MEDIUM.width(s, size) + 26
        x0 = x - w if anchor == "end" else x
        self.add(rect(x0, y, w, size + 16, "none", LINE, (size + 16) / 2))
        self.text(s, x0 + 13, y + size + 6, size, W70, MEDIUM, max_width=w)

    def render(self, height, title):
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{height:.0f}" '
                f'viewBox="0 0 {self.w} {height:.0f}" role="img"><title>{escape(title)}</title>'
                + (f'<style>{"".join(self.css)}</style>' if self.css else "")
                + f'<defs>{"".join(self.defs.values())}</defs>'
                + rect(0.5, 0.5, self.w - 1, round(height) - 1, BG, SECOND, RADIUS)
                + "".join(self.items) + "</svg>\n")


def rect(x, y, w, h, fill, stroke="none", rx=INNER, extra=""):
    return (f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx}" '
            f'fill="{fill}" stroke="{stroke}" {extra}/>')


# ------------------------------------------------- hero: a matching you can check
SCORES = [92, 85, 78, 74, 66, 61, 55, 47, 40]
CAPACITY = [2, 2, 2, 1]          # 7 seats for 9 applicants (made-up example)


def deferred_acceptance(prefs):
    """Applicant-proposing deferred acceptance, in synchronous rounds."""
    nxt = [0] * len(prefs)
    held = [[] for _ in CAPACITY]
    free = list(range(len(prefs)))
    events, rnd = {}, 0
    while True:
        proposers = [a for a in free if nxt[a] < len(prefs[a])]
        if not proposers:
            return events, held
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
        events, held = deferred_acceptance(prefs)
        rounds = max(s for s, _ in events.values())
        displaced = sum(1 for s, e in events.values() if e is not None and e > s)
        if rounds == 4 and displaced >= 2 and sum(map(len, held)) == 7:
            return prefs, events, held
    raise SystemExit("No suitable instance found")


def check_stable(prefs, held):
    """No applicant prefers a program with a free seat or a lower-scored holder."""
    match = {a: p for p, hs in enumerate(held) for a in hs}
    for a, preference_list in enumerate(prefs):
        for p in preference_list:
            if match.get(a) == p:
                break
            if len(held[p]) < CAPACITY[p] or any(SCORES[b] < SCORES[a] for b in held[p]):
                raise SystemExit(f"Unstable matching: applicant {a} and program {p} form a blocking pair")


def matching(c, x0, y0, w, h, r, num, seat):
    prefs, events, held = pick_instance()
    check_stable(prefs, held)          # the picture is only drawn if this passes
    ax = [x0 + r + i * (w - 2 * r) / (len(SCORES) - 1) for i in range(len(SCORES))]
    pad, gap = seat * 0.5, seat * 0.36
    widths = [2 * pad + cap * seat + (cap - 1) * gap for cap in CAPACITY]
    space = (w - sum(widths)) / (len(widths) - 1)
    boxes, x = [], x0
    for bw in widths:
        boxes.append((x, bw))
        x += bw + space
    y1 = y0 + h
    edges, step = [], 1.1
    ordered = sorted(events.items(), key=lambda kv: (kv[1][1] is None, kv[1][0]))
    for i, ((a, p), (start, end)) in enumerate(ordered):
        px = boxes[p][0] + boxes[p][1] / 2
        mid = (y0 + y1) / 2
        d = f"M{ax[a]:.1f} {y0 + r:.1f} C{ax[a]:.1f} {mid:.1f} {px:.1f} {mid:.1f} {px:.1f} {y1:.1f}"
        final = end is None
        style = (f'stroke="{W80}" stroke-width="2"' if final
                 else f'stroke="{LINE}" stroke-width="1.5" stroke-dasharray="3 6"')
        edges.append(f'<path class="e{i}" d="{d}" fill="none" {style}/>')
        t0 = 0.4 + (start - 1) * step
        if final:
            c.css.append(f".e{i}{{animation:in .6s ease-out {t0:.2f}s backwards}}")
        else:
            t1 = 0.4 + (end - 1) * step + 0.8
            total = t1 + 0.4
            a0, a1, a2 = 100 * t0 / total, 100 * min(t0 + .35, t1) / total, 100 * t1 / total
            c.css.append(
                f"@keyframes k{i}{{0%,{a0:.1f}%{{opacity:0;stroke:{W90}}}"
                f"{a1:.1f}%,{a2:.1f}%{{opacity:1;stroke:{W90}}}"
                f"100%{{opacity:1;stroke:{LINE}}}}}.e{i}{{animation:k{i} {total:.2f}s linear both}}")
    c.css.append("@keyframes in{from{opacity:0}to{opacity:1}}")
    c.css.append("@media (prefers-reduced-motion:reduce){path{animation:none!important}}")
    c.add(*edges)
    matched = {a for hs in held for a in hs}
    for a, score in enumerate(SCORES):
        on = a in matched
        c.add(f'<circle cx="{ax[a]:.1f}" cy="{y0:.1f}" r="{r}" fill="{SURFACE if on else BG}" '
              f'stroke="{W70 if on else AUX}" stroke-width="1.5"/>')
        c.text(str(score), ax[a], y0 + num * 0.36, num, WHITE if on else W60, STRONG, "middle", max_width=2 * r)
    for p, cap in enumerate(CAPACITY):
        bx, bw = boxes[p]
        c.add(rect(bx, y1, bw, seat + 2 * pad, SURFACE, SECOND, 8))
        for s in range(cap):
            c.add(rect(bx + pad + s * (seat + gap), y1 + pad, seat, seat,
                       W80 if s < len(held[p]) else "none", W80, 3))
    return y1 + seat + 2 * pad


PHRASE = "Built to be checked."
INTRO = ("I build web products and show how they work: the sentence behind a rule, "
         "the trade-off behind a result.")
HERO_TITLE = (f"Raimundo Nonato. {PHRASE} {INTRO} Computer Engineering student at IME, "
              "co-founder of LEPV, Rio de Janeiro. Graphic: a deferred-acceptance matching on a "
              "made-up example, checked for stability by the code that draws it.")


def hero(mobile):
    if not mobile:
        c = Canvas(DESK, 44)
        c.text("Computer Engineering at IME", 44, 58, 15, W70, MEDIUM)
        c.text("Co-founder of LEPV, Rio de Janeiro", DESK - 44, 58, 15, W70, MEDIUM, "end")
        c.rule(80)
        track = -0.028
        size = XBOLD.fit("Raimundo Nonato", DESK - 92, track)
        c.text("Raimundo Nonato", 42, 80 + size * 0.98, size, WHITE, XBOLD, track=track, max_width=DESK - 88)
        y = 80 + size * 0.98 + 80
        c.text(PHRASE, 44, y, 42, W90, DISPLAY, track=-0.012, max_width=470)
        c.para(INTRO, 552, y - 29, 16.5, 284, 25, W70)
        end = matching(c, 44, y + 80, DESK - 88, 118, 19, 14, 17)
        c.text("A made-up example: nine applicants ranked by score, seven seats, matched by deferred "
               "acceptance.", DESK / 2, end + 36, 13.5, W60, anchor="middle")
        c.text("The code that draws it first checks that the match is stable.", DESK / 2, end + 57, 13.5, W80,
               MEDIUM, "middle")
        return c.render(end + 82, HERO_TITLE)
    c = Canvas(PHONE, 24)
    c.text("Computer Engineering at IME", 24, 44, 16, W70, MEDIUM)
    c.text("Co-founder of LEPV, Rio de Janeiro", 24, 68, 16, W70, MEDIUM)
    c.rule(88)
    track = -0.03
    size = XBOLD.fit("Raimundo", PHONE - 52, track)
    c.text("Raimundo", 22, 88 + size * 1.0, size, WHITE, XBOLD, track=track, max_width=PHONE - 46)
    c.text("Nonato", 22, 88 + size * 1.92, size, WHITE, XBOLD, track=track)
    y = 88 + size * 1.92 + 62
    c.text("Built to be", 24, y, 40, W90, DISPLAY, track=-0.012)
    c.text("checked.", 24, y + 43, 40, W90, DISPLAY, track=-0.012)
    y = c.para(INTRO, 24, y + 86, 17, PHONE - 48, 26, W70)
    end = matching(c, 24, y + 32, PHONE - 48, 128, 15.5, 14, 13)
    y = c.para("A made-up example: nine applicants by score, seven seats. The code that draws it first "
               "checks that the match is stable.",
               24, end + 34, 16, PHONE - 48, 23, W60)
    return c.render(y + 4, HERO_TITLE)


# ------------------------------------------------------------- selected work
def facts(c, items, y, mobile):
    """My part / result / stack, as an editorial three-column block (stacked on phones)."""
    if mobile:
        for label, body in items:
            c.rule(y)
            c.text(label, 24, y + 32, 16, W60, MEDIUM)
            y = c.para(body, 24, y + 60, 17, PHONE - 48, 25, W80) + 4
        return y
    c.rule(y)
    cols = [(44, 258), (338, 262), (636, 200)]
    bottom = y
    for (label, body), (x, w) in zip(items, cols):
        c.text(label, x, y + 36, 14, W60, MEDIUM)
        bottom = max(bottom, c.para(body, x, y + 66, 15.5, w, 23.5, W80))
    return bottom + 12


QUOTE = ("Applicants must hold a PhD and", "keep an up-to-date research CV.")


def document(c, x, y, w, fs, h):
    c.add(rect(x, y, w, h, SURFACE))
    c.text("Funding call, illustrative excerpt", x + 20, y + 34, fs - 2, W60, MEDIUM, max_width=w - 32)
    for i, frac in enumerate((0.88, 0.68)):
        c.add(rect(x + 20, y + 54 + i * 18, (w - 40) * frac, 7, SECOND, rx=3.5))
    yy = y + 116
    right = 0
    for line in QUOTE:
        right = max(right, x + 25 + BODY.width(line, fs))
        c.add(rect(x + 16, yy - fs - 3, BODY.width(line, fs) + 9, fs + 11, W80, rx=3))
        c.text(line, x + 20, yy, fs, BG, max_width=w - 32)
        yy += fs + 13
    c.add(rect(x + 20, yy - 2, (w - 40) * 0.78, 7, SECOND, rx=3.5))
    first = y + 116
    return right, first - fs - 3 + (fs + 11) / 2     # right end of the highlighted quote


def rule_cards(c, x, y, w, fs):
    c.add(rect(x, y, w, 100, SURFACE, W80))
    c.text("Rule: applicants need a PhD", x + 20, y + 40, fs + 1, WHITE, STRONG, max_width=w - 32)
    cx, cy = x + 30, y + 70
    c.add(f'<circle cx="{cx}" cy="{cy}" r="10" fill="{W80}"/>'
          f'<path d="M{cx-4.5} {cy} l3 3.5 l6 -7" fill="none" stroke="{BG}" stroke-width="2.2" '
          'stroke-linecap="round" stroke-linejoin="round"/>')
    c.text("Quote found word for word", x + 48, y + 75, fs, W80, max_width=w - 58)
    c.add(rect(x, y + 114, w, 72, "none", LINE, extra='stroke-dasharray="5 5"'))
    c.text("No matching quote in the text?", x + 20, y + 144, fs - 1, W60, max_width=w - 32)
    c.text("Rule marked unconfirmed", x + 20, y + 169, fs, W80, STRONG, max_width=w - 32)


LUNETA_PARTS = [
    ("My part", "Project management, product discovery, brand and site copy. Accountable for the site "
                "and user experience in a team of five."),
    ("Result", "Public site listing 179 calls from 10 funding agencies (12 Nov 2026). IME's InovaIME "
               "portal links to it as a prototype in testing."),
    ("Team's stack", "Python, Docling, language models, a rule-based quote check, Next.js, TypeScript."),
]
LUNETA_PROBLEM = "Eligibility rules hide inside long research funding calls."
LUNETA_TITLE = (f"Luneta. {LUNETA_PROBLEM} It shows each rule next to the sentence it came from. A check "
                "without AI confirms the quote exists; otherwise the rule is marked unconfirmed. "
                + " ".join(f"{k}: {v}" for k, v in LUNETA_PARTS))
PIPELINE = ["Official PDF", "Converted text", "Language model", "Quote check, no AI"]


def luneta(mobile):
    if not mobile:
        c = Canvas(DESK, 44)
        c.text("Selected work", 44, 52, 15, W60, MEDIUM)
        c.rule(74)
        c.text("Luneta", 42, 144, 60, WHITE, XBOLD, track=-0.025)
        c.pill("Prototype in testing", DESK - 44, 108)
        c.text(LUNETA_PROBLEM, 44, 190, 21, W90, MEDIUM)
        c.text("Each rule is shown next to the sentence it came from.", 44, 221, 18, W70)
        qx, qy = document(c, 44, 256, 388, 17, 200)
        c.add(f'<path d="M{qx:.1f} {qy:.1f} C{qx + 100:.1f} {qy:.1f} {500 - 100} 306 500 306" fill="none" '
              f'stroke="{W80}" stroke-width="2"/>',
              f'<circle cx="{qx:.1f}" cy="{qy:.1f}" r="4" fill="{W80}"/>',
              f'<circle cx="500" cy="306" r="4.5" fill="{W80}"/>')
        rule_cards(c, 500, 262, 336, 16)
        # the real pipeline, from the project's public documentation
        y, x = 488, 44
        sizes = [MEDIUM.width(s, 14) + 28 for s in PIPELINE]
        gap = (DESK - 88 - sum(sizes)) / (len(sizes) - 1)
        for i, (s, w) in enumerate(zip(PIPELINE, sizes)):
            last = i == len(PIPELINE) - 1
            c.add(rect(x, y, w, 36, W80 if last else "none", W80 if last else LINE, 8))
            c.text(s, x + 14, y + 23, 14, BG if last else W70, MEDIUM, max_width=w)
            if not last:
                c.add(f'<path d="M{x + w + 10:.1f} {y + 18} H{x + w + gap - 10:.1f}" stroke="{AUX}" stroke-width="1.5"/>')
            x += w + gap
        end = facts(c, LUNETA_PARTS, 558, False)
        return c.render(end + 8, LUNETA_TITLE)
    c = Canvas(PHONE, 24)
    c.text("Selected work", 24, 42, 16, W60, MEDIUM)
    c.rule(62)
    c.text("Luneta", 22, 126, 56, WHITE, XBOLD, track=-0.025)
    c.pill("Prototype in testing", 24, 148, 15, "start")
    y = c.para(LUNETA_PROBLEM, 24, 218, 20, PHONE - 48, 28, W90, MEDIUM)
    y = c.para("Each rule is shown next to the sentence it came from.", 24, y + 6, 17, PHONE - 48, 25, W70)
    document(c, 24, y + 4, PHONE - 48, 16.5, 200)
    c.add(f'<path d="M180 {y + 204} v26" stroke="{W80}" stroke-width="2"/>')
    rule_cards(c, 24, y + 230, PHONE - 48, 16.5)
    y += 446
    for i, s in enumerate(PIPELINE):
        last = i == len(PIPELINE) - 1
        c.add(rect(24, y, PHONE - 48, 38, W80 if last else "none", W80 if last else LINE, 8))
        c.text(s, PHONE / 2, y + 25, 16, BG if last else W70, MEDIUM, "middle")
        if not last:
            c.add(f'<path d="M180 {y + 38} v14" stroke="{AUX}" stroke-width="1.5"/>')
        y += 52
    end = facts(c, LUNETA_PARTS, y + 12, True)
    return c.render(end + 4, LUNETA_TITLE)


MC_ROWS = [("Priority group", 78.0, 93.5), ("Everyone else", 76.8, 59.2)]
MC_PARTS = [
    ("My part", "Front end for the family and city-office views, wiring the allocation engine into the "
                "API, and documentation. Team project."),
    ("Result", "One of 5 finalist teams out of 42 at Claude Impact Lab Rio. The simulation places 912 "
               "fewer children in total: 48,680 to 47,768."),
    ("Built with", "HTML, CSS, JavaScript, Python, FastAPI, Gale-Shapley deferred acceptance."),
]
MC_PROBLEM = "Daycare seats in 2025: what changes if they are filled child by child?"
MC_NOTE = ("Priority group: score 51 or more, which in 2025 means registered in CadÚnico. Anonymized data; "
           "the source warns its indicators do not represent reality.")
MC_TITLE = (f"Match Carioca, an independent hackathon prototype, not a city service. {MC_PROBLEM} "
            "Share of children placed: priority group 78.0% in the real process and 93.5% in the "
            "simulation; everyone else 76.8% and 59.2%. " + MC_NOTE + " "
            + " ".join(f"{k}: {v}" for k, v in MC_PARTS))


def bar(c, x, y, track_w, value, emphasis, fs, h):
    c.add(rect(x, y, track_w, h, SURFACE, rx=3),
          rect(x, y, track_w * value / 100, h, W80 if emphasis else AUX, rx=3))
    c.text(f"{value:.1f}%", x + track_w + 12, y + h / 2 + fs * 0.36, fs,
           WHITE if emphasis else W60, STRONG if emphasis else BODY)


def legend(c, x, y, fs, stacked):
    for i, (label, color) in enumerate((("Real 2025 process", AUX), ("Simulated, child by child", W80))):
        c.add(rect(x, y - 11, 12, 12, color, rx=2))
        c.text(label, x + 20, y, fs, W70)
        if stacked:
            y += fs + 12
        else:
            x += BODY.width(label, fs) + 52


def match(mobile):
    if not mobile:
        c = Canvas(DESK, 44)
        c.text("Match Carioca", 42, 90, 60, WHITE, XBOLD, track=-0.025)
        c.pill("Independent hackathon prototype", DESK - 44, 54)
        c.text(MC_PROBLEM, 44, 138, 21, W90, MEDIUM)
        c.text("Priority families gain seats. Other families lose them.", 44, 169, 18, W70)
        legend(c, 44, 220, 14.5, False)
        y = 244
        for name, before, after in MC_ROWS:
            c.text(name, 44, y + 33, 17, W90, STRONG)
            bar(c, 220, y, 540, before, False, 17, 24)
            bar(c, 220, y + 32, 540, after, True, 17, 24)
            y += 86
        y = c.para(MC_NOTE, 44, y + 18, 13.5, DESK - 88, 20, W60)
        end = facts(c, MC_PARTS, y + 12, False)
        return c.render(end + 8, MC_TITLE)
    c = Canvas(PHONE, 24)
    c.text("Match", 22, 72, 52, WHITE, XBOLD, track=-0.025)
    c.text("Carioca", 22, 122, 52, WHITE, XBOLD, track=-0.025)
    c.pill("Independent prototype", 24, 144, 15, "start")
    y = c.para(MC_PROBLEM, 24, 214, 20, PHONE - 48, 28, W90, MEDIUM)
    y = c.para("Priority families gain seats. Other families lose them.", 24, y + 6, 17, PHONE - 48, 25, W70)
    legend(c, 24, y + 18, 16, True)
    y += 78
    for name, before, after in MC_ROWS:
        c.text(name, 24, y + 18, 18, W90, STRONG)
        bar(c, 24, y + 32, 240, before, False, 17, 22)
        bar(c, 24, y + 62, 240, after, True, 17, 22)
        y += 114
    y = c.para(MC_NOTE, 24, y + 16, 16, PHONE - 48, 23, W60)
    end = facts(c, MC_PARTS, y + 8, True)
    return c.render(end + 4, MC_TITLE)


# ----------------------------------------------------------------- stack
STACK = [
    ("Languages", [("javascript", "JavaScript"), ("python", "Python"), ("c", "C"), ("dart", "Dart"),
                   ("html5", "HTML"), ("css", "CSS")]),
    ("Frameworks and libraries", [("react", "React"), ("nodedotjs", "Node.js"), ("express", "Express"),
                                  ("fastapi", "FastAPI"), ("flutter", "Flutter"), ("pandas", "pandas"),
                                  ("numpy", "NumPy")]),
    ("Data and tooling", [("postgresql", "PostgreSQL"), ("git", "Git"), ("github", "GitHub"),
                          ("vite", "Vite")]),
    ("Design and engineering", [("figma", "Figma"), ("arduino", "Arduino"), ("latex", "LaTeX")]),
]
# Brands without an icon in Simple Icons are listed as text; logos are not redrawn.
STACK_TEXT = "Also SolidWorks and Power BI."
STACK_TITLE = ("Technical stack. " + " ".join(
    f"{cat}: {', '.join(n for _, n in items)}." for cat, items in STACK) + " " + STACK_TEXT)


def icon(slug, cx, y, size, fill):
    svg = _module(f"simple-icons/icons/{slug}.svg").read_text(encoding="utf-8")
    paths = re.findall(r'<path d="([^"]+)"', svg)
    if len(paths) != 1:
        raise SystemExit(f"Unexpected icon structure: {slug}")
    return (f'<path transform="translate({cx - size / 2:.1f} {y:.1f}) scale({size / 24:.4f})" '
            f'fill="{fill}" d="{paths[0]}"/>')


def stack(mobile):
    c = Canvas(PHONE if mobile else DESK, 24 if mobile else 44)
    if mobile:
        c.text("Technical stack", 24, 56, 30, WHITE, XBOLD, track=-0.02)
        y = c.para("Tools from projects and coursework.", 24, 86, 16, PHONE - 48, 23, W60) + 4
        cols, cell = 4, (PHONE - 40) / 4
        for cat, items in STACK:
            c.rule(y)
            c.text(cat, 24, y + 32, 16, W60, MEDIUM)
            y += 52
            for i, (slug, name) in enumerate(items):
                cx = 20 + cell * (i % cols) + cell / 2
                row = y + (i // cols) * 74
                c.add(icon(slug, cx, row, 28, W80))
                c.text(name, cx, row + 51, 14.5, W70, anchor="middle", max_width=cell)
            y += ((len(items) - 1) // cols + 1) * 74 + 2
        c.text(STACK_TEXT, 24, y + 8, 16, W70)
        return c.render(y + 34, STACK_TITLE)
    c.text("Technical stack", 42, 66, 34, WHITE, XBOLD, track=-0.02)
    c.text("Tools from projects and coursework.", DESK - 44, 64, 15, W60, anchor="end")
    y, left = 92, 252
    cell = (DESK - 44 - left) / 7
    for cat, items in STACK:
        c.rule(y)
        c.text(cat, 44, y + 52, 15, W70, MEDIUM, max_width=left - 54)
        for i, (slug, name) in enumerate(items):
            cx = left + cell * i + cell / 2
            c.add(icon(slug, cx, y + 20, 28, W80))
            c.text(name, cx, y + 71, 13.5, W70, anchor="middle", max_width=cell - 2)
        if cat == "Design and engineering":
            c.text(STACK_TEXT, left + cell * len(items) + 20, y + 52, 15, W70)
        y += 92
    return c.render(y + 6, STACK_TITLE)


# ------------------------------------------------------------- background
TIMELINE = [
    ("2026 to now", "Co-founder, LEPV",
     "Entrepreneurship league at IME. Set up its selection process and operating model; helped run "
     "its first hackathon, with FGV, in October 2026."),
    ("2025 to now", "Coordinator, IME Júnior",
     "Tech and people management at IME's junior enterprise, including web and mobile client projects."),
    ("2025 to now", "Member, IME Finance", "Financial markets league."),
    ("2025", "Reserve officer aspirant, Brazilian Army", ""),
    ("2019, 2020", "Brazilian Astronomy Olympiad", "Silver medal in 2019, gold medal in 2020."),
]
LANGUAGES = "Portuguese (native) and English."
EXPLORING = ("Advanced React patterns, REST APIs with Node.js, mobile development with Flutter and data "
             "analysis with Python.")
BG_TITLE = ("Background. " + " ".join(f"{a}: {b}. {d}" for a, b, d in TIMELINE)
            + f" Currently exploring: {EXPLORING}")


def background(mobile):
    c = Canvas(PHONE if mobile else DESK, 24 if mobile else 44)
    if mobile:
        c.text("Background", 24, 56, 30, WHITE, XBOLD, track=-0.02)
        y = 80
        for when, role, detail in TIMELINE:
            c.rule(y)
            c.text(when, 24, y + 30, 16, W60, MEDIUM)
            yy = c.para(role, 24, y + 57, 18, PHONE - 48, 25, WHITE, STRONG)
            if detail:
                yy = c.para(detail, 24, yy + 2, 16.5, PHONE - 48, 24, W70)
            y = yy
        lines = BODY.wrap(EXPLORING, 17, PHONE - 64)
        h = 58 + 25 * len(lines)
        c.add(rect(12, y + 8, PHONE - 24, h, SURFACE))
        c.text("Currently exploring", 28, y + 40, 16, W60, MEDIUM)
        c.para(EXPLORING, 28, y + 68, 17, PHONE - 64, 25, W90)
        return c.render(y + h + 20, BG_TITLE)
    c.text("Background", 42, 66, 34, WHITE, XBOLD, track=-0.02)
    y = 92
    for when, role, detail in TIMELINE:
        c.rule(y)
        c.text(when, 44, y + 33, 15, W60, MEDIUM)
        c.text(role, 188, y + 33, 16, WHITE, STRONG, max_width=306)
        if detail:
            yy = c.para(detail, 506, y + 33, 14.5, DESK - 550, 21.5, W70)
        else:
            yy = y + 55
        y = max(yy - 3, y + 54)
    lines = BODY.wrap(EXPLORING, 15.5, 560)
    h = 36 + 23 * len(lines)
    c.add(rect(24, y + 8, DESK - 48, h, SURFACE))
    c.text("Currently exploring", 44, y + 40, 15, W70, MEDIUM)
    c.para(EXPLORING, 252, y + 40, 15.5, 560, 23, W90)
    return c.render(y + h + 32, BG_TITLE)


# ------------------------------------------------------------ contact buttons
def button(label):
    w = round(STRONG.width(label, 16) + 48)
    defs = {}
    text = STRONG.path(defs, label, w / 2, 26, 16, W90, "middle")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="40" viewBox="0 0 {w} 40" role="img">'
            f"<title>{label}</title>" + rect(0.5, 0.5, w - 1, 39, BG, LINE, 19.5)
            + f'<defs>{"".join(defs.values())}</defs>' + text + "</svg>\n")


PANELS = {"hero": hero, "luneta": luneta, "match-carioca": match, "stack": stack, "background": background}


def main():
    OUT.mkdir(exist_ok=True)
    wanted = set()
    for name, fn in PANELS.items():
        for mobile in (False, True):
            path = OUT / f"{name}{'-mobile' if mobile else ''}.svg"
            path.write_text(fn(mobile), encoding="utf-8")
            wanted.add(path.name)
    for label in ("LinkedIn", "Email"):
        path = OUT / f"button-{label.lower()}.svg"
        path.write_text(button(label), encoding="utf-8")
        wanted.add(path.name)
    stale = sorted(p.name for p in OUT.glob("*.svg") if p.name not in wanted)
    print("OK:", len(wanted), "files; hero matching is stable")
    if stale:
        print("Unused SVGs still in assets/:", ", ".join(stale))


if __name__ == "__main__":
    main()
