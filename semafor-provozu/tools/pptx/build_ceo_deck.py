# -*- coding: utf-8 -*-
"""Přehled pro CEO jako deck ve firemní šabloně: titul, portfolio (tabulka), časová osa portfolia, pak charter + Gantt každého
CEO projektu.   python3 build_ceo_deck.py <snapshot_dir> <out.pptx>"""
import sys, datetime
import hx, charter_lib as C
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR
snap, out = sys.argv[1], sys.argv[2]; C.init(snap)
today = C.today
ceo = [(k, p) for k, p in C.P.items() if p.get('ceoScope') and not p.get('archived')]
ORDER = {'red': 0, 'yellow': 1, 'green': 2}
ceo.sort(key=lambda kp: (ORDER.get(kp[1].get('status'), 3), kp[1].get('dueDate') or '9999'))
def tasks_of(k): return [t for t in C.T.values() if t.get('projectId') == k and not t.get('archived')]
prs = hx.deck()
hx.title_slide(prs, [('Přehled projektů pro CEO', 30, True), ('Semafor Provozu · stav k %s · %d projektů ve výběru CEO' % (today.strftime('%-d. %-m. %Y'), len(ceo)), 17, False)])
# ---------- snímek 2: portfolio ----------
s = hx.content_slide(prs, 'Portfolio — projekty ve výběru CEO', tag='Přehled CEO')
cnt = {'green': 0, 'yellow': 0, 'red': 0}; overdue = 0; decisions = 0; blocked = 0
for k, p in ceo:
    cnt[p.get('status', 'green')] = cnt.get(p.get('status', 'green'), 0) + 1
    if C.d(p.get('dueDate')) and C.d(p['dueDate']) < today and p.get('lifecycle') != 'done': overdue += 1
    if p.get('decisionNeeded'): decisions += 1
    if p.get('blocker'): blocked += 1
tiles = [('PROJEKTŮ', str(len(ceo)), hx.INK), ('NA DOBRÉ CESTĚ', str(cnt['green']), hx.GREEN), ('POZOR', str(cnt['yellow']), hx.AMBER), ('KRITICKÉ', str(cnt['red']), hx.RED), ('PO TERMÍNU', str(overdue), hx.RED if overdue else hx.INK), ('K ROZHODNUTÍ CEO', str(decisions), hx.RED if decisions else hx.INK)]
tw, gap = (12.8 - 5 * 0.12) / 6, 0.12
for i, (lab, val, col) in enumerate(tiles):
    x = 0.26 + i * (tw + gap); hx.rect(s, x, hx.TOP, tw, 0.72, hx.CARD)
    hx.text(s, x + 0.12, hx.TOP + 0.08, tw - 0.24, 0.2, [[(lab, {'size': 8, 'bold': True, 'font': hx.HEAD, 'color': hx.MUTED})]])
    hx.text(s, x + 0.12, hx.TOP + 0.28, tw - 0.24, 0.4, [[(val, {'size': 18, 'bold': True, 'font': hx.HEAD, 'color': col})]], anchor='m')
# tabulka
cols = [('', 0.3), ('Projekt', 3.1), ('Útvar', 1.1), ('Vlastník', 1.3), ('Termín', 1.15), ('Kroky', 0.75), ('Další krok / rozhodnutí', 5.1)]
y = hx.TOP + 0.72 + 0.2; x0 = 0.26
xx = x0
for lab, w in cols:
    hx.text(s, xx + 0.05, y, w, 0.22, [[(lab.upper(), {'size': 8, 'bold': True, 'font': hx.HEAD, 'color': hx.MUTED})]]); xx += w
y += 0.26
ln = s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x0), Inches(y - 0.03), Inches(x0 + 12.8), Inches(y - 0.03)); ln.line.color.rgb = RGBColor(0xDD, 0xDD, 0xDD); ln.line.width = Pt(0.75)
RH = 0.56
for k, p in ceo:
    ts = tasks_of(k); done = sum(1 for t in ts if t.get('status') == 'done'); od = sum(1 for t in ts if t.get('status') != 'done' and C.d(t.get('dueDate')) and C.d(t['dueDate']) < today)
    col = C.STATUS.get(p.get('status'), C.STATUS['green'])[1]
    hx.ellipse(s, x0 + 0.08, y + 0.14, 0.16, col)
    xx = x0 + cols[0][1]
    nxt = p.get('nextStep') or (C.T.get(p.get('nextStepTaskId') or '', {}).get('title') if p.get('nextStepTaskId') else '') or '—'
    extra = (' · ROZHODNUTÍ: ' + p['decisionNeeded']) if p.get('decisionNeeded') else ((' · PŘEKÁŽKA: ' + p['blocker']) if p.get('blocker') else '')
    vals = [[(p.get('title', ''), {'size': 9.5, 'bold': True, 'font': hx.HEAD, 'color': hx.INK})],
            [(C.DEPT.get(p.get('department'), p.get('department')), {'size': 9, 'color': hx.INK})],
            [(C.person(p.get('ownerEmail')), {'size': 9, 'color': hx.INK})],
            [(C.fmt(p.get('dueDate'), p.get('duePrecision')) + (' ?' if p.get('dueUnconfirmed') else ''), {'size': 9, 'color': hx.RED if (C.d(p.get('dueDate')) and C.d(p['dueDate']) < today) else hx.INK})],
            [('%d/%d' % (done, len(ts)) + ((' · %d!' % od) if od else ''), {'size': 9, 'color': hx.RED if od else hx.INK})],
            [(nxt, {'size': 8.5, 'color': hx.INK}), (extra, {'size': 8.5, 'bold': True, 'font': hx.HEAD, 'color': hx.RED})]]
    for (lab, w), v in zip(cols[1:], vals):
        hx.text(s, xx + 0.05, y + 0.04, w - 0.1, RH - 0.08, [v], anchor='t'); xx += w
    y += RH
    ln = s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x0), Inches(y - 0.03), Inches(x0 + 12.8), Inches(y - 0.03)); ln.line.color.rgb = RGBColor(0xEE, 0xEE, 0xEE); ln.line.width = Pt(0.5)
hx.text(s, 0.26, 6.95, 10, 0.25, [[('Řazeno: kritické → pozor → na dobré cestě, pak podle termínu. „?“ = nepotvrzený termín, „N!“ = kroky po termínu. Detail každého projektu na dalších snímcích.', {'size': 8.5, 'italic': True, 'color': hx.MUTED})]])
hx.page(s, 2)
# ---------- snímek 3: časová osa portfolia ----------
s3 = hx.content_slide(prs, 'Časová osa — projekty ve výběru CEO', tag='Přehled CEO')
dates = [x for k, p in ceo for x in (C.d(p.get('startDate')), C.d(p.get('dueDate'))) if x] + [today]
for k, p in ceo:
    for t in tasks_of(k):
        for x in (C.d(t.get('startDate')), C.d(t.get('dueDate'))):
            if x: dates.append(x)
d0 = min(dates).replace(day=1); d1 = max(dates) + datetime.timedelta(days=15); days = (d1 - d0).days
GX, GW, LW = 0.26, 12.8, 3.4; X0 = GX + LW; PW = GW - LW
def xo(dt): return X0 + (dt - d0).days / days * PW
y = hx.TOP; m = d0
while m <= d1:
    nm = (m.replace(day=28) + datetime.timedelta(days=4)).replace(day=1); xa, xb = max(xo(m), X0), min(xo(nm), X0 + PW)
    if xb > xa:
        hx.rect(s3, xa, y, xb - xa, 0.24, RGBColor(0xF1, 0xF1, 0xF1) if m.month % 2 else RGBColor(0xE6, 0xE6, 0xE6), radius=0)
        if xb - xa > 0.45: hx.text(s3, xa + 0.04, y + 0.03, xb - xa, 0.2, [[(m.strftime('%m/%y'), {'size': 8, 'bold': True, 'font': hx.HEAD, 'color': hx.INK})]])
    m = nm
yy = y + 0.34; RH = 0.62
for k, p in ceo:
    ts = tasks_of(k); col = C.STATUS.get(p.get('status'), C.STATUS['green'])[1]
    tds = [x for t in ts for x in (C.d(t.get('startDate')), C.d(t.get('dueDate'))) if x]
    ps_ = C.d(p.get('startDate')) or (min(tds) if tds else None); pe_ = C.d(p.get('dueDate')) or (max(tds) if tds else None)
    hx.ellipse(s3, GX, yy + 0.08, 0.14, col)
    hx.text(s3, GX + 0.2, yy, LW - 0.3, 0.3, [[(p.get('title', ''), {'size': 9, 'bold': True, 'font': hx.HEAD, 'color': hx.INK})]], anchor='m')
    hx.text(s3, GX + 0.2, yy + 0.27, LW - 0.3, 0.22, [[(C.DEPT.get(p.get('department'), '') + ' · ' + C.person(p.get('ownerEmail')), {'size': 7.5, 'color': hx.MUTED})]])
    if ps_ and pe_:
        if pe_ < ps_: pe_ = ps_
        hx.rect(s3, xo(ps_), yy + 0.06, max(xo(pe_) - xo(ps_), 0.06), 0.18, col, radius=0.05, line=hx.RED if (pe_ < today and p.get('lifecycle') != 'done') else None)
        lab = C.fmt(p.get('dueDate'), p.get('duePrecision')) if p.get('dueDate') else 'bez termínu'
        if xo(pe_) + 1.25 <= X0 + PW: hx.text(s3, xo(pe_) + 0.05, yy + 0.04, 1.2, 0.22, [[(lab, {'size': 7.5, 'color': hx.MUTED})]], anchor='m')
        else: hx.text(s3, xo(pe_) - 1.25, yy + 0.04, 1.2, 0.22, [[(lab, {'size': 7.5, 'color': hx.WHITE, 'align': 'r'})]], anchor='m')
    # kroky jako tenké tečky pod pruhem (hotové zeleně, otevřené šedě, po termínu červeně)
    for t in ts:
        e = C.d(t.get('dueDate'))
        if not e: continue
        c = hx.GREEN if t.get('status') == 'done' else (hx.RED if e < today else RGBColor(0xB0, 0xB8, 0xC4))
        hx.ellipse(s3, xo(e) - 0.04, yy + 0.3, 0.08, c)
    yy += RH
tx = xo(today); ln = s3.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(tx), Inches(y + 0.24), Inches(tx), Inches(yy)); ln.line.color.rgb = hx.RED; ln.line.width = Pt(1.25); ln.line.dash_style = 4
hx.text(s3, tx + 0.03, yy, 0.6, 0.18, [[('dnes', {'size': 7, 'bold': True, 'font': hx.HEAD, 'color': hx.RED})]])
lx = GX; ly = 6.95
for lab, col in [('projekt — barva = semafor', hx.AMBER), ('krok hotový', hx.GREEN), ('krok otevřený', RGBColor(0xB0, 0xB8, 0xC4)), ('krok po termínu', hx.RED)]:
    hx.rect(s3, lx, ly + 0.05, 0.22, 0.12, col, radius=0.03); hx.text(s3, lx + 0.27, ly, 2.2, 0.22, [[(lab, {'size': 8, 'color': hx.MUTED})]], anchor='m'); lx += 2.3
hx.page(s3, 3)
# ---------- charter + Gantt každého projektu ----------
page = 4
for k, p in ceo:
    page += C.charter_slides(prs, k, page)
prs.save(out); print(out, 'snímků', len(prs.slides._sldIdLst), 'projektů', len(ceo))
