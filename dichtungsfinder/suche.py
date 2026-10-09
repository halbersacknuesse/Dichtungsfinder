"""Fehlertoleranter Abgleich einer Foto-Silhouette gegen den Katalog-Index.

Gesamtscore = Kontur (Chamfer der Umrisse) + Form (weichgezeichneter Flächenvergleich) + Größe.
Alle Vergleiche sind unabhängig von Drehung und Spiegelung.
"""
import json, numpy as np, cv2

PX = 20                     # px/mm der gespeicherten Silhouetten
GEW_FORM, GEW_GROESSE = 0.75, 0.25
GEW_KONTUR = 0.6
KONTUR_TAU = 6.0
GROESSEN_TOLERANZ = 0.35


def fill_outer(s):
    b = (s > 127).astype(np.uint8) if s.dtype == np.uint8 and s.max() > 1 else (s > 0.5).astype(np.uint8)
    cnts, _ = cv2.findContours(b, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    out = np.zeros_like(b); cv2.drawContours(out, cnts, -1, 1, -1); return out

def normalize(b, n, fill=0.28, blur=0.035):
    b = b.astype(np.float32)
    ys, xs = np.nonzero(b > 0.5); cy, cx = ys.mean(), xs.mean()
    s = fill * n / np.sqrt(b.sum())
    M = np.float32([[s, 0, n/2 - s*cx], [0, s, n/2 - s*cy]])
    out = cv2.warpAffine(b, M, (n, n), flags=cv2.INTER_AREA)
    return cv2.GaussianBlur(out, (0, 0), blur * n) if blur else out

def rotations(img, step):
    n = img.shape[0]; out, keys = [], []
    for mir in (False, True):
        base = np.ascontiguousarray(img[:, ::-1]) if mir else img
        for ang in range(0, 360, step):
            M = cv2.getRotationMatrix2D((n/2, n/2), ang, 1.0)
            out.append(cv2.warpAffine(base, M, (n, n))); keys.append((ang, mir))
    return np.stack(out), keys

def soft_iou(R, c):
    return np.minimum(R, c).sum(axis=(1, 2)) / np.maximum(R, c).sum(axis=(1, 2))

def _kante(b):
    return cv2.morphologyEx((b > 0.5).astype(np.uint8), cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8))

def kontur_score(a, b):
    ea, eb = _kante(a), _kante(b)
    da = cv2.distanceTransform(1 - ea, cv2.DIST_L2, 3); db = cv2.distanceTransform(1 - eb, cv2.DIST_L2, 3)
    d = 0.5 * (da[eb > 0].mean() + db[ea > 0].mean())
    return float(np.exp(-d / KONTUR_TAU))


class Katalog:
    """Geladener Index. Lädt schnell (Grobmerkmale sind vorberechnet), Silhouetten bei Bedarf."""

    def __init__(self, index_path):
        self._z = np.load(index_path)
        self.meta = json.loads(str(self._z['meta']))
        self.info = json.loads(str(self._z['info'])) if 'info' in self._z.files else {}
        self.grob = self._z['grob'].astype(np.float32) if 'grob' in self._z.files else None
        self._sil, self._fein = {}, {}
        if self.grob is None:
            self.grob = np.stack([normalize(self.fuell(i), 64) for i in range(len(self.meta))])
        self.area = None

    def sil(self, i):
        """Originalsilhouette mit Hohlkammern (uint8 0/255)."""
        if i not in self._sil: self._sil[i] = self._z[f's{i}']
        return self._sil[i]

    def fuell(self, i):
        return fill_outer(self.sil(i))

    def flaeche(self, i):
        return self.fuell(i).sum() / PX**2

    def fein(self, i):
        if i not in self._fein: self._fein[i] = normalize(self.fuell(i), 160)
        return self._fein[i]

    def rubriken(self):
        """Rubriken als sortierte Liste von Pfaden, z.B. ('Fenster-Systeme', 'Anschlagdichtungen')."""
        pfade = set()
        for m in self.meta:
            r = m.get('rubrik', [])
            for k in range(1, len(r) + 1): pfade.add(tuple(r[:k]))
        return sorted(pfade)

    def suche(self, sil_foto, flaeche_foto_mm2=None, rubrik=None, top=10, vorauswahl=60, konturpruefung=40):
        """rubrik: Tupel-Präfix (aus rubriken()) oder Teilstring; None = alle."""
        p = fill_outer(sil_foto)
        if isinstance(rubrik, (tuple, list)) and rubrik:
            idx = [i for i, m in enumerate(self.meta) if tuple(m.get('rubrik', [])[:len(rubrik)]) == tuple(rubrik)]
        elif rubrik:
            idx = [i for i, m in enumerate(self.meta) if rubrik.lower() in ' • '.join(m.get('rubrik', [])).lower()]
        else:
            idx = list(range(len(self.meta)))
        if not idx: return []
        Rg, _ = rotations(normalize(p, 64), 10)
        Rg_flat = Rg.reshape(len(Rg), -1)
        grob = np.empty(len(idx))
        for k, i in enumerate(idx):              # Stufe 1: grob über alle Kandidaten
            c = self.grob[i].reshape(-1)
            grob[k] = (np.minimum(Rg_flat, c).sum(1) / np.maximum(Rg_flat, c).sum(1)).max()
        auswahl = [idx[k] for k in np.argsort(-grob)[:vorauswahl]]
        Rf, keys = rotations(normalize(p, 160), 3)  # Stufe 2: fein
        res = []
        for i in auswahl:
            sc = soft_iou(Rf, self.fein(i)); k = int(sc.argmax())
            if flaeche_foto_mm2:
                ratio = self.flaeche(i) / flaeche_foto_mm2
                groesse = float(np.exp(-abs(np.log(ratio)) / GROESSEN_TOLERANZ))
            else:
                ratio, groesse = None, 1.0
            res.append(dict(self.meta[i], idx=i, form=float(sc[k]), groesse=groesse,
                            flaechenverhaeltnis=ratio, drehung=keys[k][0], gespiegelt=keys[k][1],
                            score=GEW_FORM * float(sc[k]) + GEW_GROESSE * groesse))
        res = sorted(res, key=lambda r: -r['score'])[:konturpruefung]
        pn = normalize(p, 160, blur=0); n = 160
        for r in res:                             # Stufe 3: Umriss
            base = np.ascontiguousarray(pn[:, ::-1]) if r['gespiegelt'] else pn
            M = cv2.getRotationMatrix2D((n/2, n/2), r['drehung'], 1.0)
            r['kontur'] = kontur_score(cv2.warpAffine(base, M, (n, n)), normalize(self.fuell(r['idx']), 160, blur=0))
            r['score'] = (1 - GEW_KONTUR) * r['score'] + GEW_KONTUR * r['kontur']
        return sorted(res, key=lambda r: -r['score'])[:top]


def foto_in_katalog_lage(sil_foto, drehung, gespiegelt):
    """Foto-Silhouette (echter Maßstab) so drehen/spiegeln, wie sie zum Katalogprofil passt.
    Rückgabe: gefülltes Bild und Schwerpunkt."""
    b = fill_outer(sil_foto).astype(np.uint8)
    d = int(np.hypot(*b.shape)) + 8
    b = cv2.copyMakeBorder(b, (d - b.shape[0])//2, (d - b.shape[0])//2, (d - b.shape[1])//2, (d - b.shape[1])//2,
                           cv2.BORDER_CONSTANT, 0)
    if gespiegelt: b = np.ascontiguousarray(b[:, ::-1])
    ys, xs = np.nonzero(b); cx, cy = xs.mean(), ys.mean()
    M = cv2.getRotationMatrix2D((cx, cy), drehung, 1.0)
    b = cv2.warpAffine(b, M, (b.shape[1], b.shape[0]), flags=cv2.INTER_NEAREST)
    return b, (cx, cy)
