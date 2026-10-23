# -*- coding: utf-8 -*-
"""Project Charter jako 2 snímky ve firemní šabloně Hranipex (vzor pro CEO/Board).
  python3 build_charter_pptx.py <snapshot_dir> <project_id> <out.pptx>"""
import json, glob, os, sys, datetime
import hx
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
from pptx.oxml.ns import qn
from lxml import etree
from zoneinfo import ZoneInfo
TZ = ZoneInfo('Europe/Prague')
today = datetime.datetime.now(TZ).date()
P = T = H = None
def init(snap):
    global P, T, H
    def load(col): return {os.path.basename(f)[:-5]: json.load(open(f, encoding='utf-8')) for f in glob.glob(os.path.join(snap, col, '*.json'))}
    P = load('projects'); T = load('tasks'); H = load('history')
DEPT = {'vyroba': 'Výroba', 'kvalita': 'Kvalita & BOZP/ESH', 'facility': 'Facility', 'ie': 'IE & R&D', 'bvr': 'BVR', 'erp': 'Ostatní / HQ', 'hq': 'Ostatní / HQ'}
STATUS = {'green': ('Na dobré cestě', hx.GREEN), 'yellow': ('Pozor', hx.AMBER), 'red': ('Kritické', hx.RED)}
LC = {'active': 'Aktivní', 'done': 'Dokončený', 'planned': 'Plánovaný', 'paused': 'Pozastavený'}
TS = {'todo': 'K udělání', 'in_progress': 'Probíhá', 'done': 'Hotovo'}
PEOPLE = {'tomas.juranek@hranipex.com': 'Tomáš Juránek', 'ondrej.svoboda@hranipex.com': 'Ondřej Svoboda', 'karel.byrtus@hranipex.com': 'Karel Byrtus', 'jakub.simon@hranipex.com': 'Jakub Šimon', 'jan.kratky@hranipex.com': 'Jan Krátký'}
def person(e): return PEOPLE.get((e or '').lower(), e or '—')
def d(s):
    try: return datetime.date.fromisoformat(s)
    except Exception: return None
def fmt(s, prec='day'):
    x = d(s)
    if not x: return '—'
    if prec == 'week': return 'týden %d/%d' % (x.isocalendar()[1], x.year)
    if prec == 'month': return x.strftime('%m/%Y')
    return x.strftime('%-d. %-m. %Y')
def eff_due(it):   # efektivní termín jako v aplikaci: týden = neděle, měsíc = poslední den
    x = d(it.get('dueDate'))
    if not x: return None
    if it.get('duePrecision') == 'week': return x + datetime.timedelta(days=6 - x.weekday())
    if it.get('duePrecision') == 'month': return (x.replace(day=28) + datetime.timedelta(days=4)).replace(day=1) - datetime.timedelta(days=1)
    return x
def team_names(s):
    out = []
    for x in [y.strip() for y in str(s or '').replace(';', ',').split(',') if y.strip()]: out.append(person(x) if '@' in x else x)
    return ', '.join(out)
def ts_ms(ms, f='%-d. %-m. %Y'): return datetime.datetime.fromtimestamp(ms / 1000, TZ).strftime(f)
def money(v, cur):
    return '—' if v in (None, '', 0) else '{:,.0f}'.format(v).replace(',', ' ') + ' ' + (cur or 'CZK')
def charter_slides(prs, pid, page0=1):
    p = P[pid]; tasks = [(k, t) for k, t in T.items() if t.get('projectId') == pid and not t.get('archived')]
    alltasks = [t for k, t in T.items() if t.get('projectId') == pid]
    ev = (H.get(pid) or {}).get('events', {}); ev = ev.values() if isinstance(ev, dict) else ev
    hist = sorted([e for e in ev if e], key=lambda e: e.get('at', 0))
    TODO = 'doplnit'
    done = [t for k, t in tasks if t.get('status') == 'done']; overdue = [t for k, t in tasks if t.get('status') != 'done' and eff_due(t) and eff_due(t) < today]
    # stejná pravidla jako aplikace (v2.30): náklady z projectCost, čekání na otevřené předchůdce, potvrzení stavu
    task_plan = sum((t.get('costPlanned') or 0) for t in alltasks if not t.get('archived') or t.get('status') == 'done'); actual = sum((t.get('costActual') or 0) for t in alltasks)
    arch_n = sum(1 for t in alltasks if t.get('archived'))
    def openpred(ref):
        kind, _, i = str(ref).partition(':'); it = (P if kind == 'project' else T).get(i)
        if not it: return 'smazaná položka'
        closed = it.get('lifecycle') == 'done' if kind == 'project' else it.get('status') == 'done'
        return None if closed else ('projekt ' if kind == 'project' else 'úkol ') + '„' + it.get('title', '') + '“' + (' (v koši)' if it.get('archived') else '') + (' (' + DEPT.get(it.get('department'), '') + ')' if it.get('department') != p.get('department') else '')
    waiting = [x for x in (openpred(r) for r in (p.get('dependsOn') or [])) if x]
    if p.get('confirmedAt') and not p.get('confirmStale') and (today - datetime.datetime.fromtimestamp(p['confirmedAt'] / 1000, TZ).date()).days <= 14: conf, conf_col = ts_ms(p['confirmedAt']) + ' · ' + person(p.get('confirmedBy')), None
    elif p.get('confirmedAt') and p.get('confirmStale'): conf, conf_col = 'změněno po potvrzení', hx.RED
    elif p.get('confirmedAt'): conf, conf_col = ts_ms(p['confirmedAt']) + ' · zastaralé', hx.RED
    else: conf, conf_col = 'nepotvrzeno', hx.RED
    nextstep = p.get('nextStep') or (T.get(p.get('nextStepTaskId') or '', {}).get('title') if p.get('nextStepTaskId') else '') or '—'
    decisions = [e for e in hist if e.get('type') == 'decision'][-3:]; due_changes = [e for e in hist if e.get('type') == 'due'][-2:]
    upcoming = sorted([t for k, t in tasks if t.get('status') != 'done'], key=lambda t: (t.get('dueDate') or '9999'))[:5]
    st_label, st_color = STATUS.get(p.get('status'), STATUS['green'])

    # ================= snímek 1: one-pager =================
    s = hx.content_slide(prs, p.get('title', ''), tag='Project Charter')
    hx.text(s, hx.TITLE_X, 1.28, 12.5, 0.3, [[('%s  ·  Vlastník: %s  ·  Sponzor: %s%s  ·  Stav k %s  ·  Zadání v%d%s' % (DEPT.get(p.get('department'), p.get('department')), person(p.get('ownerEmail')), person(p['sponsorEmail']) if p.get('sponsorEmail') else TODO, '  ·  CEO výběr' if p.get('ceoScope') else '', today.strftime('%-d. %-m. %Y'), p.get('charterVersion') or 0, (' · změněno ' + ts_ms(p['charterChangedAt'])) if p.get('charterChangedAt') else ''), {'size': 11, 'color': hx.MUTED})]])
    # pás ukazatelů (6 karet)
    tiles = [('SEMAFOR', st_label, st_color), ('FÁZE', LC.get(p.get('lifecycle'), '—'), None), ('ZAČÁTEK', fmt(p.get('startDate')), None),
             ('TERMÍN', fmt(p.get('dueDate'), p.get('duePrecision')) + (' · nepotvrzený' if p.get('dueUnconfirmed') else ''), hx.RED if p.get('dueUnconfirmed') else None),
             ('KROKY', '%d / %d hotovo' % (len(done), len(tasks)) + (' · %d po termínu' % len(overdue) if overdue else ''), hx.RED if overdue else None),
             ('STAV PLATÍ', conf, conf_col)]
    tw, gap, y0 = (12.8 - 5 * 0.12) / 6, 0.12, hx.TOP
    for i, (lab, val, col) in enumerate(tiles):
        x = 0.26 + i * (tw + gap); hx.rect(s, x, y0, tw, 0.72, hx.CARD)
        hx.text(s, x + 0.12, y0 + 0.08, tw - 0.24, 0.2, [[(lab, {'size': 8, 'bold': True, 'font': hx.HEAD, 'color': hx.MUTED})]])
        runs = []
        if lab == 'SEMAFOR': hx.ellipse(s, x + 0.12, y0 + 0.37, 0.14, col); runs = [(val, {'size': 11, 'bold': True, 'font': hx.HEAD, 'color': hx.INK})]; hx.text(s, x + 0.32, y0 + 0.3, tw - 0.4, 0.3, [runs], anchor='m'); continue
        hx.text(s, x + 0.12, y0 + 0.3, tw - 0.24, 0.34, [[(val, {'size': 10.5, 'bold': True, 'font': hx.HEAD, 'color': col or hx.INK})]], anchor='m')
    # dva sloupce karet
    def card(x, y, w, h, title, rows, size=9.5):
        hx.rect(s, x, y, w, h, hx.CARD)
        hx.text(s, x + 0.15, y + 0.08, w - 0.3, 0.25, [[(title.upper(), {'size': 9, 'bold': True, 'font': hx.HEAD, 'color': hx.RED})]])
        paras = []
        for lab, val in rows:
            paras.append([(lab + ': ', {'size': size, 'bold': True, 'font': hx.HEAD, 'color': hx.INK, 'space_after': 3}), (val, {'size': size, 'color': hx.RED if val == TODO else hx.INK})])
        hx.text(s, x + 0.15, y + 0.36, w - 0.3, h - 0.42, paras)
    LX, RX, CW = 0.26, 6.73, 6.33; Y1 = y0 + 0.72 + 0.16
    card(LX, Y1, CW, 2.45, 'Proč a co', [('Cíl / business case', p.get('charterGoal') or TODO), ('Očekávaný výsledek', p.get('outcome') or TODO), ('Rozsah — je součástí', p.get('scopeIn') or TODO), ('Rozsah — není součástí', p.get('scopeOut') or TODO), ('Přínosy / KPI úspěchu', p.get('benefits') or TODO), ('Poznámka', p.get('note') or '—')])
    card(LX, Y1 + 2.45 + 0.14, CW, 1.3, 'Lidé', [('Vlastník', person(p.get('ownerEmail'))), ('Sponzor', person(p['sponsorEmail']) if p.get('sponsorEmail') else TODO), ('Tým', team_names(p.get('team')) or TODO), ('Rozhoduje', 'vedení' if p.get('decisionBy') == 'vedeni' else 'CEO')])
    card(RX, Y1, CW, 1.45, 'Stav a řízení', [('Další krok', nextstep), ('Překážka', p.get('blocker') or '—'), ('Čeká na', '; '.join(waiting) or '—'), ('Potřebné rozhodnutí', (p.get('decisionNeeded') + (' (vedení)' if p.get('decisionBy') == 'vedeni' else ' (CEO)')) if p.get('decisionNeeded') else '—'), ('Rizika', p.get('risks') or TODO)], size=9)
    cur = p.get('costCurrency') or 'CZK'
    card(RX, Y1 + 1.45 + 0.14, CW, 0.8, 'Náklady', [('Plán projektu', money(p.get('costPlanned'), cur) + '   ·   plán kroků: ' + money(task_plan, cur) + '   ·   skutečnost: ' + money(actual, cur) + (' (vč. %d v koši)' % arch_n if arch_n else ''))], size=9)
    # nejbližší kroky jako tabulka v kartě
    y2 = Y1 + 1.45 + 0.14 + 0.8 + 0.14; h2 = Y1 + 2.45 + 0.14 + 1.3 - y2
    hx.rect(s, RX, y2, CW, h2, hx.CARD)
    hx.text(s, RX + 0.15, y2 + 0.08, CW - 0.3, 0.25, [[('NEJBLIŽŠÍ KROKY', {'size': 9, 'bold': True, 'font': hx.HEAD, 'color': hx.RED})]])
    rowsy = y2 + 0.36
    for t in upcoming:
        hx.text(s, RX + 0.15, rowsy, 3.9, 0.22, [[(t.get('title', ''), {'size': 9, 'color': hx.INK})]])
        hx.text(s, RX + 4.1, rowsy, 1.0, 0.22, [[(fmt(t.get('dueDate'), t.get('duePrecision')), {'size': 9, 'color': hx.RED if (eff_due(t) and eff_due(t) < today) else hx.INK})]])
        hx.text(s, RX + 5.15, rowsy, 1.05, 0.22, [[(TS.get(t.get('status'), ''), {'size': 9, 'color': hx.AMBER if t.get('status') == 'in_progress' else hx.MUTED})]])
        rowsy += 0.22
    if decisions or due_changes:
        hx.text(s, RX + 0.15, rowsy + 0.04, CW - 0.3, h2 - (rowsy - y2) - 0.08, [[('Rozhodnutí / změny termínu: ', {'size': 8.5, 'bold': True, 'font': hx.HEAD, 'color': hx.INK}), ('; '.join([ts_ms(e['at'], '%-d. %-m.') + ' ' + str(e.get('text', '')) for e in decisions] + [ts_ms(e['at'], '%-d. %-m.') + ' termín %s → %s' % (fmt(e.get('from'), e.get('fromP') or 'day'), fmt(e.get('to'), e.get('toP') or 'day')) for e in due_changes]), {'size': 8.5, 'color': hx.INK})]])
    else:
        hx.text(s, RX + 0.15, rowsy + 0.04, CW - 0.3, 0.22, [[('Rozhodnutí / změny termínu: ', {'size': 8.5, 'bold': True, 'font': hx.HEAD, 'color': hx.INK}), ('zatím žádné', {'size': 8.5, 'color': hx.MUTED})]])
    hx.text(s, hx.TITLE_X, 7.02, 8, 0.3, [[('Vygenerováno ze Semaforu Provozu · %s' % datetime.datetime.now(TZ).strftime('%-d. %-m. %Y %H:%M'), {'size': 9, 'color': RGBColor(0x9E, 0x9E, 0x9E)})]])
    hx.page(s, page0)

    # ================= snímek 2: Gantt =================
    s2 = hx.content_slide(prs, p.get('title', '') + ' — harmonogram', tag='Project Charter')
    # pořadí řetězů: následník hned za předchůdcem
    _sorted = sorted(tasks, key=lambda kt: (kt[1].get('startDate') or kt[1].get('dueDate') or '9999', kt[1].get('dueDate') or '9999'))
    ids = {k for k, t in _sorted}
    def preds(t): return [r.split(':', 1)[-1] for r in (t.get('dependsOn') or []) if r.split(':', 1)[-1] in ids]
    rows, placed = [], set()
    def place(k, t):
        if k in placed: return
        placed.add(k); rows.append((k, t))
        for k2, t2 in _sorted:
            if k2 not in placed and k in preds(t2) and all(pp in placed for pp in preds(t2)): place(k2, t2)
    for k, t in _sorted:
        if all(pp in placed for pp in preds(t)): place(k, t)
    for k, t in _sorted: place(k, t)
    # kapacita stránky: 20 řádků; při přeplnění skrýt nejstarší hotové; zbytek → další snímek
    CAP = 20
    hidden_done = 0
    if len(rows) > CAP:
        done_sorted = sorted([kt for kt in rows if kt[1].get('status') == 'done'], key=lambda kt: kt[1].get('dueDate') or '')
        while len(rows) > CAP and done_sorted:
            k, t = done_sorted.pop(0); rows.remove((k, t)); hidden_done += 1
    pages = [rows[i:i + CAP] for i in range(0, len(rows), CAP)] or [[]]
    dates = [x for kt in rows for x in (d(kt[1].get('startDate')), d(kt[1].get('dueDate'))) if x] + [x for x in (d(p.get('startDate')), d(p.get('dueDate')), today) if x]
    d0 = min(dates) - datetime.timedelta(days=min(dates).weekday() + 7); d1 = max(dates) + datetime.timedelta(days=10); days = (d1 - d0).days or 1
    GX, GW, LW = 0.26, 12.8, 3.6; X0 = GX + LW; PW = GW - LW
    def xo(dt): return X0 + (dt - d0).days / days * PW
    COL = {'todo': RGBColor(0xCF, 0xD6, 0xE0), 'in_progress': hx.AMBER, 'done': hx.GREEN}
    def arrow(slide, x1, y1, x2, y2):
        c = slide.shapes.add_connector(MSO_CONNECTOR.ELBOW, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
        c.line.color.rgb = RGBColor(0x7A, 0x1F, 0x2B); c.line.width = Pt(1)
        ln = c.line._get_or_add_ln(); te = etree.SubElement(ln, qn('a:tailEnd')); te.set('type', 'triangle'); te.set('w', 'sm'); te.set('len', 'sm')
    def gantt_page(slide, prow, first):
        y = hx.TOP; RH = 0.24
        # měsíce + týdny
        m = d0.replace(day=1)
        while m <= d1:
            nm = (m.replace(day=28) + datetime.timedelta(days=4)).replace(day=1); xa, xb = max(xo(m), X0), min(xo(nm), X0 + PW)
            if xb > xa:
                hx.rect(slide, xa, y, xb - xa, 0.22, RGBColor(0xF1, 0xF1, 0xF1) if m.month % 2 else RGBColor(0xE6, 0xE6, 0xE6), radius=0)
                if xb - xa > 0.5: hx.text(slide, xa + 0.05, y + 0.02, xb - xa, 0.2, [[(m.strftime('%m/%Y'), {'size': 8, 'bold': True, 'font': hx.HEAD, 'color': hx.INK})]])
            m = nm
        w = d0; nrows = len(prow) + 1
        while w <= d1:
            xx = xo(w); ln = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(xx), Inches(y + 0.22), Inches(xx), Inches(y + 0.4 + RH * nrows)); ln.line.color.rgb = RGBColor(0xE3, 0xE3, 0xE3); ln.line.width = Pt(0.5)
            hx.text(slide, xx + 0.02, y + 0.23, 0.4, 0.16, [[('T%d' % w.isocalendar()[1], {'size': 6.5, 'color': hx.MUTED})]]); w += datetime.timedelta(days=7)
        yy = y + 0.42
        if first:
            ps_, pe_ = d(p.get('startDate')) or min(dates), d(p.get('dueDate')) or max(dates)
            hx.text(slide, GX, yy, LW - 0.1, RH, [[(p.get('title', ''), {'size': 9, 'bold': True, 'font': hx.HEAD, 'color': hx.INK})]], anchor='m')
            hx.rect(slide, xo(ps_), yy + 0.08, max(xo(pe_) - xo(ps_), 0.05), 0.08, hx.INK, radius=0.03)
        yy += RH; pos = {}
        for k, t in prow:
            s_, e_ = d(t.get('startDate')) or d(t.get('dueDate')), d(t.get('dueDate')) or d(t.get('startDate'))
            hx.text(slide, GX, yy, LW - 0.1, RH, [[(t.get('title', ''), {'size': 8.5, 'color': hx.INK})]], anchor='m')
            if s_:
                if e_ < s_: e_ = s_
                e_ = max(e_, eff_due(t) or e_); xa = xo(s_); xb = max(xo(e_ + datetime.timedelta(days=1)), xa + 0.06); od = t.get('status') != 'done' and e_ < today
                hx.rect(slide, xa, yy + 0.04, xb - xa, RH - 0.08, COL.get(t.get('status'), COL['todo']), radius=0.05, line=hx.RED if od else None)
                if t.get('status') != 'done': hx.text(slide, xb + 0.14, yy, 1.0, RH, [[(fmt(t.get('dueDate'), t.get('duePrecision')), {'size': 7, 'color': hx.MUTED})]], anchor='m')
                pos[k] = (xa, xb, yy + RH / 2)
            else:
                hx.text(slide, X0 + 0.05, yy, 2.0, RH, [[('termín nezadán', {'size': 7, 'italic': True, 'color': hx.MUTED})]], anchor='m')
            yy += RH
        for k, t in prow:
            for pp in preds(t):
                if pp in pos and k in pos:
                    a, b = pos[pp], pos[k]; arrow(slide, a[1], a[2], b[0], b[2])
        tx = xo(today); ln = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(tx), Inches(y + 0.22), Inches(tx), Inches(yy)); ln.line.color.rgb = hx.RED; ln.line.width = Pt(1.25); ln.line.dash_style = 4
        hx.text(slide, tx + 0.03, yy, 0.6, 0.18, [[('dnes', {'size': 7, 'bold': True, 'font': hx.HEAD, 'color': hx.RED})]])
        # legenda
        lx = GX; ly = 6.95
        for lab, col in [('k udělání', COL['todo']), ('probíhá', hx.AMBER), ('hotovo', hx.GREEN), ('projekt', hx.INK)]:
            hx.rect(slide, lx, ly + 0.05, 0.22, 0.12, col, radius=0.03); hx.text(slide, lx + 0.27, ly, 1.0, 0.22, [[(lab, {'size': 8, 'color': hx.MUTED})]], anchor='m'); lx += 1.15
        hx.rect(slide, lx, ly + 0.05, 0.22, 0.12, hx.WHITE, radius=0.03, line=hx.RED); hx.text(slide, lx + 0.27, ly, 1.0, 0.22, [[('po termínu', {'size': 8, 'color': hx.MUTED})]], anchor='m'); lx += 1.15
        hx.text(slide, lx, ly, 2.2, 0.22, [[('→ návaznost · ◆ milník', {'size': 8, 'color': hx.MUTED})]], anchor='m')
        if hidden_done: hx.text(slide, lx + 2.3, ly, 4, 0.22, [[('skryto %d nejstarších hotových kroků' % hidden_done, {'size': 8, 'italic': True, 'color': hx.MUTED})]], anchor='m')
    gantt_page(s2, pages[0], True); hx.page(s2, page0 + 1)
    for i, pr in enumerate(pages[1:], page0 + 2):
        sx = hx.content_slide(prs, p.get('title', '') + ' — harmonogram (pokračování)', tag='Project Charter'); gantt_page(sx, pr, False); hx.page(sx, i)

    return 2 + max(0, len(pages) - 1)

if __name__ == '__main__':
    snap, pid, out = sys.argv[1], sys.argv[2], sys.argv[3]; init(snap)
    prs = hx.deck(); n = charter_slides(prs, pid, 1); prs.save(out); print(out, 'snímků', n)
