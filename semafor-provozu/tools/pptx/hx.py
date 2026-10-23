"""Stavební blok pro prezentace ve firemní šabloně Hranipex.

Vychází z vzorové prezentace 07_2026_Board_meeting_Operations_final.pptx:
rozměry, mřížka, barvy, fonty a tvarosloví karet jsou převzaty z ní.
"""
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR

import os as _os
TEMPLATE = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "Hranipex_sablona.pptx")

# ---- barvy (theme accent1..6 + neutrály ze vzoru) ----
RED    = RGBColor(0xED, 0x1B, 0x34)   # accent1 – firemní červená
GREEN  = RGBColor(0x00, 0xB1, 0x40)   # accent4
AMBER  = RGBColor(0xE8, 0xA5, 0x00)
BLUE   = RGBColor(0x00, 0x77, 0xC8)   # accent6
CYAN   = RGBColor(0x00, 0xB5, 0xE2)   # accent5
PURPLE = RGBColor(0x96, 0x60, 0x7D)
TEAL   = RGBColor(0x46, 0x78, 0x86)
CARD   = RGBColor(0xF2, 0xF2, 0xF2)   # výplň karet
INK    = RGBColor(0x2B, 0x2B, 0x2B)   # text v kartách
TITLE  = RGBColor(0x5E, 0x5E, 0x5E)   # nadpis snímku
MUTED  = RGBColor(0x6E, 0x6E, 0x6E)
WHITE  = RGBColor(0xFF, 0xFF, 0xFF)
PALE   = RGBColor(0xFC, 0xE8, 0xEB)   # světlý červený podklad pod ikonu

# ---- fonty ze šablony ----
HEAD = "HelveticaNeueLT Pro 65 Md"
BODY = "HelveticaNeueLT Pro 45 Lt"

# ---- mřížka (13.33 x 7.5") ----
W, H = 13.333, 7.5
MX     = 0.53          # levý okraj karet
TITLE_X, TITLE_Y, TITLE_W, TITLE_H = 0.26, 0.79, 12.52, 0.55
TOP    = 1.73          # první řada obsahu
BOT    = 6.85          # spodní hranice obsahu
COL3   = [0.53, 4.63, 8.73]
CW3    = 3.77
GAP    = 0.33

LAY_TITLE, LAY_CONTENT, LAY_THANKS = 0, 1, 9


def deck():
    return Presentation(TEMPLATE)


# ---------------- primitiva ----------------
def _tf(shape):
    tf = shape.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    return tf


def text(slide, x, y, w, h, paras, align="l", anchor="t"):
    """paras = [ [(text, opts), ...], ... ] ; opts: size, bold, color, font, space_after, align"""
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = _tf(box)
    tf.vertical_anchor = {"t": MSO_ANCHOR.TOP, "m": MSO_ANCHOR.MIDDLE, "b": MSO_ANCHOR.BOTTOM}[anchor]
    for i, runs in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        first = runs[0][1] if runs else {}
        p.alignment = {"l": PP_ALIGN.LEFT, "c": PP_ALIGN.CENTER, "r": PP_ALIGN.RIGHT}[first.get("align", align)]
        if first.get("space_after"):
            p.space_after = Pt(first["space_after"])
        if first.get("line"):
            p.line_spacing = first["line"]
        if first.get("hang"):
            pPr = p._p.get_or_add_pPr()
            pPr.set("marL", str(int(Inches(first["hang"]))))
            pPr.set("indent", str(-int(Inches(first["hang"]))))
        for t, o in runs:
            r = p.add_run()
            r.text = t
            f = r.font
            f.name = o.get("font", BODY)
            f.size = Pt(o.get("size", 12))
            f.bold = o.get("bold", False)
            f.italic = o.get("italic", False)
            f.color.rgb = o.get("color", INK)
    return box


def rect(slide, x, y, w, h, fill, radius=0.10, line=None):
    s = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    s.adjustments[0] = min(0.5, radius / min(w, h))
    s.fill.solid()
    s.fill.fore_color.rgb = fill
    if line is None:
        s.line.fill.background()
    else:
        s.line.color.rgb = line
        s.line.width = Pt(1)
    s.shadow.inherit = False
    s.text_frame.text = ""
    return s


def ellipse(slide, x, y, d, fill):
    s = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x), Inches(y), Inches(d), Inches(d))
    s.fill.solid()
    s.fill.fore_color.rgb = fill
    s.line.fill.background()
    s.shadow.inherit = False
    return s


def icon(slide, name, x, y, d):
    slide.shapes.add_picture(f"ico/{name}.png", Inches(x), Inches(y), Inches(d), Inches(d))


def notes(slide, txt):
    slide.notes_slide.notes_text_frame.text = txt


# ---------------- typy snímků ----------------
def title_slide(prs, lines, note=None):
    """Červený úvodní snímek s bílým logem (layout Úvodní snímek)."""
    s = prs.slides.add_slide(prs.slide_layouts[LAY_TITLE])
    ph = s.placeholders[10]
    tf = ph.text_frame
    tf.word_wrap = True
    for i, (t, size, bold) in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        r = p.add_run()
        r.text = t
        r.font.name = HEAD if bold else BODY
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.color.rgb = WHITE
    if note:
        notes(s, note)
    return s


def section_slide(prs, num, title, sub, mins, note=None):
    s = prs.slides.add_slide(prs.slide_layouts[LAY_TITLE])
    ph = s.placeholders[10]
    ph._element.getparent().remove(ph._element)
    text(s, 4.76, 2.75, 8.1, 0.9, [[(num, {"size": 40, "bold": True, "font": HEAD, "color": WHITE})]])
    text(s, 4.76, 3.55, 8.1, 0.95, [[(title, {"size": 28, "bold": True, "font": HEAD, "color": WHITE})]])
    text(s, 4.76, 4.50, 8.1, 0.9, [[(sub, {"size": 14, "color": WHITE, "line": 1.25})]])
    r = rect(s, 4.76, 5.45, 1.55, 0.44, WHITE, radius=0.22)
    text(s, 4.76, 5.45, 1.55, 0.44, [[(mins, {"size": 11.5, "bold": True, "font": HEAD, "color": RED, "align": "c"})]], anchor="m")
    if note:
        notes(s, note)
    return s


def content_slide(prs, title, tag=None):
    """Bílý snímek s červeným logem vlevo nahoře (layout Data Visualization)."""
    s = prs.slides.add_slide(prs.slide_layouts[LAY_CONTENT])
    for ph in list(s.placeholders):
        ph._element.getparent().remove(ph._element)
    tw = TITLE_W - 3.4 if tag else TITLE_W
    text(s, TITLE_X, TITLE_Y, tw, TITLE_H,
         [[(title, {"size": 18, "bold": True, "font": HEAD, "color": TITLE})]])
    if tag:
        text(s, W - 0.26 - 3.2, TITLE_Y + 0.05, 3.2, 0.4,
             [[(tag.upper(), {"size": 11, "bold": True, "font": HEAD, "color": RED, "align": "r"})]])
    return s


def footnote(slide, txt, y):
    text(slide, TITLE_X, y, TITLE_W, 0.4,
         [[(txt, {"size": 12, "italic": True, "color": RED})]])


def page(slide, n):
    text(slide, W - 0.26 - 0.8, 7.02, 0.8, 0.3,
         [[(str(n), {"size": 9.5, "color": RGBColor(0x9E, 0x9E, 0x9E), "align": "r"})]])
