"""Foto einer Dichtung auf Karopapier -> Silhouette in mm."""
import numpy as np, cv2
from PIL import Image, ImageOps
try:
    from pillow_heif import register_heif_opener; register_heif_opener()
except ImportError:
    pass

def load(path, max_side=2000):
    im = ImageOps.exif_transpose(Image.open(path)).convert('RGB')
    im.thumbnail((max_side, max_side))
    return cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)

def grid_period_px(gray, mask_obj):
    """Kästchengröße in Pixeln per FFT über die Papierfläche."""
    g = gray.astype(float).copy()
    g[mask_obj > 0] = np.median(g)
    res = []
    for axis in (0, 1):
        prof = (255 - g).sum(axis=axis)
        prof = prof - np.convolve(prof, np.ones(101) / 101, mode='same')   # Trend entfernen
        f = np.abs(np.fft.rfft(prof * np.hanning(len(prof))))
        fr = np.fft.rfftfreq(len(prof))
        lo = np.searchsorted(fr, 1 / 400); hi = np.searchsorted(fr, 1 / 15)
        k = lo + np.argmax(f[lo:hi])
        # parabolische Verfeinerung
        a, b, c = f[k-1], f[k], f[k+1]; dk = 0.5 * (a - c) / (a - 2*b + c)
        res.append(1 / ((k + dk) * (fr[1] - fr[0])))
    return float(np.mean(res)), res

def segment(img):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    v = hsv[..., 2]
    # Papierhelligkeit großräumig schätzen (dunkle Objekte per Dilatation wegdrücken),
    # damit Schatten und Helligkeitsverlauf nicht stören
    k = max(31, int(max(v.shape) * 0.12) | 1)
    bg = cv2.GaussianBlur(cv2.dilate(v, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))), (0, 0), k / 3)
    ratio = v.astype(float) / np.maximum(bg, 1)
    # Gummi ist fast schwarz (≈15 % der Papierhelligkeit), Schlagschatten deutlich heller (≈50 %).
    # Hysterese: sichere Kerne (<0.25) wachsen in angrenzende Pixel <0.32 hinein.
    strong = (ratio < 0.25).astype(np.uint8)
    weak = (ratio < 0.32).astype(np.uint8)
    n, lab = cv2.connectedComponents(weak)
    keep = np.unique(lab[strong > 0]); keep = keep[keep > 0]
    m = np.isin(lab, keep).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))   # Rasterlinien weg
    n, lab, st, _ = cv2.connectedComponentsWithStats(m)
    if n <= 1:
        raise ValueError('Im Foto wurde keine dunkle Dichtung gefunden. '
                         'Helle oder graue Dichtungen bitte mit Licht von unten fotografieren.')
    k = 1 + np.argmax(st[1:, cv2.CC_STAT_AREA])
    m = (lab == k).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    filled = np.zeros_like(m); cv2.drawContours(filled, cnts, -1, 255, -1)
    return filled

def photo_silhouette(path, kaestchen_mm=5.0, px_per_mm_out=20):
    img = load(path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    mask = segment(img)
    period, _ = grid_period_px(gray, cv2.dilate(mask, np.ones((61, 61), np.uint8)))
    px_per_mm = period / kaestchen_mm
    x, y, w, h = cv2.boundingRect(mask)
    crop = mask[y:y+h, x:x+w]
    s = px_per_mm_out / px_per_mm
    sil = cv2.resize(crop, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    sil = cv2.copyMakeBorder(sil, 20, 20, 20, 20, cv2.BORDER_CONSTANT, 0)
    return dict(img=img, mask=mask, period_px=period, px_per_mm=px_per_mm,
                breite_mm=w / px_per_mm, hoehe_mm=h / px_per_mm, sil=sil, bbox=(x, y, w, h))
