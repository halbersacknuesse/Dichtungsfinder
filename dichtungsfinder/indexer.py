"""Katalog-PDF einmalig indexieren: je Profil Artikelnummer, Seite, Rubrik, Maße (mm) und Silhouette.

Läuft parallel über mehrere Prozesse. Das Ergebnis ist eine kleine .npz-Datei; die PDF
wird danach nur noch geöffnet, um eine einzelne Katalogseite anzuzeigen.
"""
import json, os, re, time, datetime
from concurrent.futures import ProcessPoolExecutor, as_completed
import numpy as np, cv2, pymupdf

from . import suche

MM = 72 / 25.4           # PDF-Punkte pro mm (Katalog im Maßstab 1:1)
PX_PER_MM = suche.PX
# Artikelnummern: Buchstabenpräfix, Bindestrich, mindestens eine Ziffer (ADTP-922, AD-007, ADTP-1246-CC ...)
LABEL_RE = re.compile(r'^[A-Z]{1,8}-[A-Z0-9]*\d[A-Z0-9]*(-[A-Z0-9]+)*$')
FORMAT_VERSION = 1


# ---------- Geometrie ----------------------------------------------------------------

def _bez(p0, p1, p2, p3, n=12):
    t = np.linspace(0, 1, n)[:, None]
    p0, p1, p2, p3 = map(np.asarray, (p0, p1, p2, p3))
    return ((1-t)**3)*p0 + 3*((1-t)**2)*t*p1 + 3*(1-t)*t*t*p2 + t**3*p3

def _subpaths(items):
    """Rohpfad (get_cdrawings) in geschlossene Teilpfade zerlegen."""
    polys, cur, last = [], [], None
    for it in items:
        kind = it[0]
        if kind == 're':
            x0, y0, x1, y1 = it[1]
            polys.append(np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])); continue
        if kind == 'qu':
            polys.append(np.array(it[1], dtype=float).reshape(4, 2)[[0, 1, 3, 2]]); continue
        start = np.array(it[1], dtype=float)
        if last is None or np.hypot(*(start - last)) > 0.01:
            if len(cur) > 2: polys.append(np.array(cur))
            cur = [start]
        if kind == 'l':
            end = np.array(it[2], dtype=float); cur.append(end)
        elif kind == 'c':
            pts = _bez(start, it[2], it[3], it[4]); cur.extend(pts[1:]); end = pts[-1]
        last = end
    if len(cur) > 2: polys.append(np.array(cur))
    return polys

def _silhouette(polys, pad_mm=1.0):
    """Teilpfade mit Nonzero-Füllregel (wie im PDF) rastern."""
    allp = np.vstack(polys) / MM
    x0, y0 = allp.min(0) - pad_mm
    x1, y1 = allp.max(0) + pad_mm
    w, h = int(np.ceil((x1-x0)*PX_PER_MM)), int(np.ceil((y1-y0)*PX_PER_MM))
    acc = np.zeros((h, w), np.int16)
    for p in polys:
        q = np.round((p/MM - [x0, y0]) * PX_PER_MM * 16).astype(np.int32)
        area = 0.5 * np.sum(q[:-1, 0]*q[1:, 1] - q[1:, 0]*q[:-1, 1])
        m = np.zeros((h, w), np.uint8); cv2.fillPoly(m, [q], 1, shift=4)
        acc += np.int16(1 if area > 0 else -1) * m
    return np.where(acc != 0, 255, 0).astype(np.uint8)


# ---------- Seitenauswertung --------------------------------------------------------

def _rubrik(page):
    for b in page.get_text('dict')['blocks']:
        for l in b.get('lines', []):
            t = ''.join(sp['text'] for sp in l['spans']).strip()
            if l['bbox'][1] < 45 and '•' in t:
                return [x.strip() for x in t.split('•') if x.strip()]
    return []

def _seitenzahl(words, page):
    """Gedruckte Seitenzahl aus der Fußzeile. Die Kapitelziffern im Register am Seitenrand
    (5 … 20) werden ignoriert; bleiben mehrere Zahlen übrig, gewinnt die größte."""
    h, b = page.rect.height, page.rect.width
    zahlen = [int(w[4]) for w in words
              if w[1] > h - 60 and 30 < w[0] < b - 40 and re.fullmatch(r'\d{1,4}', w[4])]
    return max(zahlen) if zahlen else page.number + 1

def index_seite(page):
    words = page.get_text('words')
    labels = [w for w in words if LABEL_RE.match(w[4])]
    if not labels:
        return []
    rub, pno = _rubrik(page), _seitenzahl(words, page)
    out = []
    for d in page.get_cdrawings():
        f = d.get('fill'); r = d['rect']
        if not f or max(f) > 0.05 or len(d['items']) <= 10:
            continue
        w, h = r[2] - r[0], r[3] - r[1]
        if not (3*MM < max(w, h) < 80*MM):
            continue
        cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
        cand = [l for l in labels if l[1] < cy and l[0] - 5 < cx < l[0] + 140]
        if not cand:
            continue
        lab = min(cand, key=lambda l: cy - l[1])
        polys = _subpaths(d['items'])
        if not polys:
            continue
        sil = _silhouette(polys)
        allp = np.vstack(polys) / MM
        wmm, hmm = (allp.max(0) - allp.min(0)).round(1)
        out.append(dict(artikel=lab[4], seite=pno, pdf_index=page.number, rubrik=rub,
                        breite_mm=float(wmm), hoehe_mm=float(hmm),
                        bbox=[round(v, 1) for v in r],
                        sil=sil))
    return out

def _worker(args):
    path, seiten = args
    doc = pymupdf.open(path)
    res = []
    for i in seiten:
        try:
            res.extend(index_seite(doc[i]))
        except Exception as e:           # eine kaputte Seite soll nicht alles abbrechen
            res.append(dict(fehler=f'Seite {i+1}: {e}'))
    return len(seiten), res


# ---------- Öffentliche Funktionen ----------------------------------------------------

def index_pdf(path, fortschritt=None, abbruch=None, prozesse=None, block=8):
    """fortschritt(erledigt, gesamt) wird regelmäßig aufgerufen; abbruch() -> True bricht ab."""
    n = len(pymupdf.open(path))
    bloecke = [(path, list(range(i, min(i + block, n)))) for i in range(0, n, block)]
    prozesse = prozesse or max(1, (os.cpu_count() or 2) - 1)
    eintraege, fehler, erledigt = [], [], 0
    with ProcessPoolExecutor(max_workers=prozesse) as ex:
        futs = [ex.submit(_worker, b) for b in bloecke]
        for fu in as_completed(futs):
            if abbruch and abbruch():
                for f2 in futs: f2.cancel()
                ex.shutdown(cancel_futures=True)
                return None
            k, res = fu.result()
            erledigt += k
            for e in res:
                (fehler if 'fehler' in e else eintraege).append(e)
            if fortschritt: fortschritt(erledigt, n)
    eintraege.sort(key=lambda e: (e['pdf_index'], e['bbox'][1], e['bbox'][0]))
    return eintraege, fehler, n

def speichern(eintraege, ziel, pdf_pfad, seiten_gesamt, fehler=()):
    """Atomar schreiben; vorhandener Index wird als *_vorher.npz aufbewahrt."""
    grob = np.stack([suche.normalize(suche.fill_outer(e['sil']), 64) for e in eintraege]) if eintraege \
        else np.zeros((0, 64, 64), np.float32)
    meta = [{k: v for k, v in e.items() if k != 'sil'} for e in eintraege]
    info = dict(format=FORMAT_VERSION, pdf=os.path.abspath(pdf_pfad), pdf_name=os.path.basename(pdf_pfad),
                pdf_groesse=os.path.getsize(pdf_pfad), pdf_mtime=os.path.getmtime(pdf_pfad),
                seiten=seiten_gesamt, profile=len(eintraege), fehler=list(fehler)[:50],
                erstellt=datetime.datetime.now().isoformat(timespec='seconds'))
    tmp = ziel + '.tmp.npz'
    np.savez_compressed(tmp, meta=json.dumps(meta), info=json.dumps(info), grob=grob.astype(np.float16),
                        **{f's{i}': e['sil'] for i, e in enumerate(eintraege)})
    if os.path.exists(ziel):
        os.replace(ziel, ziel.replace('.npz', '_vorher.npz'))
    os.replace(tmp, ziel)
    return info

def vergleich(alt_meta, neu_meta):
    """Welche Artikelnummern sind hinzugekommen / entfallen?"""
    a = {m['artikel'] for m in alt_meta}; n = {m['artikel'] for m in neu_meta}
    return sorted(n - a), sorted(a - n)


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='Katalog-PDF indexieren')
    ap.add_argument('pdf'); ap.add_argument('-o', '--out', default='index.npz')
    a = ap.parse_args()
    t = time.time()
    res = index_pdf(a.pdf, fortschritt=lambda k, n: print(f'\r{k}/{n} Seiten', end='', flush=True))
    eintraege, fehler, n = res
    info = speichern(eintraege, a.out, a.pdf, n, fehler)
    print(f"\n{info['profile']} Profile in {time.time()-t:.0f} s, {len(fehler)} Fehler")
