"""Dichtungsfinder – Desktop-Oberfläche (PySide6)."""
import os, sys, json, traceback, multiprocessing
import numpy as np, cv2, pymupdf
from PySide6.QtCore import Qt, QThread, Signal, QSettings, QStandardPaths, QSize
from PySide6.QtGui import QImage, QPixmap, QAction, QKeySequence, QGuiApplication
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QLabel, QPushButton, QComboBox,
                               QDoubleSpinBox, QSpinBox, QFileDialog, QMessageBox, QProgressDialog,
                               QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout, QScrollArea, QFrame,
                               QDialog, QSplitter, QSizePolicy, QTextBrowser)

from . import foto, suche, indexer

APP = 'Dichtungsfinder'
BILDTYPEN = 'Bilder (*.heic *.heif *.jpg *.jpeg *.png *.webp *.tif *.tiff)'


def datenordner():
    """~/.local/share/dichtungsfinder/katalog – hier liegt der Index (und dessen Vorgänger)."""
    basis = os.environ.get('XDG_DATA_HOME') or os.path.expanduser('~/.local/share')
    d = os.path.join(basis, 'dichtungsfinder', 'katalog')
    os.makedirs(d, exist_ok=True)
    return d

def index_pfad():
    return os.path.join(datenordner(), 'index.npz')

def np_zu_pixmap(img):
    img = np.ascontiguousarray(img)
    if img.ndim == 2:
        q = QImage(img.data, img.shape[1], img.shape[0], img.strides[0], QImage.Format_Grayscale8)
    else:
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        q = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format_RGB888)
    return QPixmap.fromImage(q.copy())


# ---------- Bildaufbereitung ------------------------------------------------------------

PAPIER = (250, 250, 248); RASTER_FEIN = (228, 226, 224); RASTER_GROB = (196, 194, 192)
PROFIL = (20, 20, 20); MUSTER = (40, 40, 220)   # BGR: Muster in Rot

def vergleichsbild(kat, treffer, sil_foto, kante=230):
    """Katalogprofil wie im Katalog (Millimeterraster, Hohlkammern) + Umriss des Musters in Rot,
    in Lage des Katalogs gedreht und im echten Maßstab."""
    P = suche.PX
    kat_sil = kat.sil(treffer['idx']) > 127
    muster, _ = suche.foto_in_katalog_lage(sil_foto, treffer['drehung'], treffer['gespiegelt'])
    # Schwerpunkte übereinanderlegen
    ky, kx = np.nonzero(suche.fill_outer(kat.sil(treffer['idx']))); my, mx = np.nonzero(muster)
    dx, dy = kx.mean() - mx.mean(), ky.mean() - my.mean()
    xs = np.concatenate([kx, mx + dx]); ys = np.concatenate([ky, my + dy])
    x0, y0 = xs.min() - 2*P, ys.min() - 2*P
    breite, hoehe = xs.max() - x0 + 2*P, ys.max() - y0 + 2*P
    seite = max(breite, hoehe, 20 * P)                 # mindestens 20 mm Bildausschnitt
    x0 -= (seite - breite) / 2; y0 -= (seite - hoehe) / 2
    s = kante / seite                                   # px Anzeige pro px Silhouette
    img = np.full((kante, kante, 3), PAPIER, np.uint8)
    mm = s * P
    gx0 = -(x0 % P) * s; gy0 = -(y0 % P) * s
    kx_mm = int(np.floor(x0 / P)); ky_mm = int(np.floor(y0 / P))
    for k in range(int(seite / P) + 2):
        c = RASTER_GROB if (kx_mm + k) % 5 == 0 else RASTER_FEIN
        x = int(round(gx0 + k * mm)); cv2.line(img, (x, 0), (x, kante), c, 1)
        c = RASTER_GROB if (ky_mm + k) % 5 == 0 else RASTER_FEIN
        y = int(round(gy0 + k * mm)); cv2.line(img, (0, y), (kante, y), c, 1)
    M = np.float32([[s, 0, -x0 * s], [0, s, -y0 * s]])
    k_img = cv2.warpAffine(kat_sil.astype(np.float32), M, (kante, kante), flags=cv2.INTER_AREA)
    img[k_img > 0.5] = PROFIL
    M2 = np.float32([[s, 0, (dx - x0) * s], [0, s, (dy - y0) * s]])
    m_img = (cv2.warpAffine(muster.astype(np.float32), M2, (kante, kante), flags=cv2.INTER_LINEAR) > 0.5).astype(np.uint8)
    cnts, _ = cv2.findContours(m_img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    cv2.drawContours(img, cnts, -1, MUSTER, 2, lineType=cv2.LINE_AA)
    return img

def fotovorschau(ph, rand=0.6):
    img = ph['img'].copy(); x, y, w, h = ph['bbox']
    cnts, _ = cv2.findContours(ph['mask'], cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    cv2.drawContours(img, cnts, -1, MUSTER, max(2, img.shape[0] // 400), lineType=cv2.LINE_AA)
    m = int(max(w, h) * rand)
    return img[max(0, y - m):y + h + m, max(0, x - m):x + w + m]


# ---------- Hintergrundarbeiten -----------------------------------------------------------

class SuchThread(QThread):
    fertig = Signal(object, object)       # ph, treffer
    fehler = Signal(str)

    def __init__(self, kat, pfad, kaestchen, rubrik, top, ph=None):
        super().__init__(); self.a = (kat, pfad, kaestchen, rubrik, top, ph)

    def run(self):
        kat, pfad, kaestchen, rubrik, top, ph = self.a
        try:
            if ph is None:
                ph = foto.photo_silhouette(pfad, kaestchen_mm=kaestchen, px_per_mm_out=suche.PX)
            treffer = []
            if kat is not None:
                fl = suche.fill_outer(ph['sil']).sum() / suche.PX**2
                treffer = kat.suche(ph['sil'], fl, rubrik=rubrik, top=top)
            self.fertig.emit(ph, treffer)
        except ValueError as e:
            self.fehler.emit(str(e))
        except Exception:
            self.fehler.emit('Das Foto konnte nicht ausgewertet werden.\n\n' + traceback.format_exc(limit=3))


class IndexThread(QThread):
    fortschritt = Signal(int, int)
    fertig = Signal(object)
    fehler = Signal(str)

    def __init__(self, pdf, ziel):
        super().__init__(); self.pdf, self.ziel, self._stop = pdf, ziel, False

    def stop(self): self._stop = True

    def run(self):
        try:
            res = indexer.index_pdf(self.pdf, fortschritt=lambda k, n: self.fortschritt.emit(k, n),
                                    abbruch=lambda: self._stop)
            if res is None:
                self.fertig.emit(None); return
            eintraege, fehler, n = res
            if not eintraege:
                self.fehler.emit('In dieser PDF wurden keine Profilzeichnungen mit Artikelnummer gefunden. '
                                 'Der bisherige Katalog bleibt unverändert.'); return
            alt = None
            if os.path.exists(self.ziel):
                try: alt = suche.Katalog(self.ziel).meta
                except Exception: pass
            info = indexer.speichern(eintraege, self.ziel, self.pdf, n, fehler)
            neu_meta = [{k: v for k, v in e.items() if k != 'sil'} for e in eintraege]
            neu, weg = indexer.vergleich(alt, neu_meta) if alt is not None else (None, None)
            self.fertig.emit(dict(info=info, neu=neu, weg=weg))
        except Exception:
            self.fehler.emit(traceback.format_exc(limit=4))


# ---------- Katalogseite ------------------------------------------------------------------

class SeitenDialog(QDialog):
    def __init__(self, parent, pdf, treffer):
        super().__init__(parent)
        self.setWindowTitle(f"{treffer['artikel']} – Katalogseite {treffer['seite']}")
        self.pdf, self.t, self.zoom = pdf, treffer, 2.0
        self.bild = QLabel(alignment=Qt.AlignCenter)
        sc = QScrollArea(); sc.setWidget(self.bild); sc.setWidgetResizable(True)
        plus = QPushButton('Vergrößern'); minus = QPushButton('Verkleinern')
        kopie = QPushButton('Artikelnummer kopieren')
        plus.clicked.connect(lambda: self._zoom(1.25)); minus.clicked.connect(lambda: self._zoom(0.8))
        kopie.clicked.connect(lambda: QGuiApplication.clipboard().setText(treffer['artikel']))
        leiste = QHBoxLayout(); leiste.addWidget(minus); leiste.addWidget(plus); leiste.addStretch(); leiste.addWidget(kopie)
        lay = QVBoxLayout(self); lay.addLayout(leiste); lay.addWidget(sc)
        self.resize(900, 1000); self._zeichnen()
        self.sc = sc

    def _zoom(self, f):
        self.zoom = min(6, max(0.8, self.zoom * f)); self._zeichnen()

    def _zeichnen(self):
        doc = pymupdf.open(self.pdf)
        page = doc[self.t['pdf_index']]
        pix = page.get_pixmap(matrix=pymupdf.Matrix(self.zoom, self.zoom), alpha=False)
        img = np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w, 3)[..., ::-1].copy()
        x0, y0, x1, y1 = [v * self.zoom for v in self.t['bbox']]
        r = int(14 * self.zoom)
        cv2.rectangle(img, (int(x0) - r, int(y0) - r), (int(x1) + r, int(y1) + r), (40, 40, 220), max(2, int(self.zoom)))
        self.bild.setPixmap(np_zu_pixmap(img))
        if hasattr(self, 'sc'):
            self.sc.ensureVisible(int((x0 + x1) / 2), int((y0 + y1) / 2), 300, 300)

    def showEvent(self, e):
        super().showEvent(e)
        x0, y0, x1, y1 = [v * self.zoom for v in self.t['bbox']]
        self.sc.ensureVisible(int((x0 + x1) / 2), int((y0 + y1) / 2), 300, 300)


# ---------- Trefferkarte -------------------------------------------------------------------

class Trefferkarte(QFrame):
    def __init__(self, fenster, rang, treffer, bild):
        super().__init__()
        self.setFrameShape(QFrame.StyledPanel); self.fenster, self.t = fenster, treffer
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip('Doppelklick zeigt die Katalogseite')
        b = QLabel(); b.setPixmap(np_zu_pixmap(bild)); b.setAlignment(Qt.AlignCenter)
        titel = QLabel(f"<b>{rang}. {treffer['artikel']}</b>")
        prozent = int(round(treffer['score'] * 100))
        details = QLabel(f"Seite {treffer['seite']} · Übereinstimmung {prozent} %<br>"
                         f"<span style='color:#666'>{treffer['breite_mm']:.1f} × {treffer['hoehe_mm']:.1f} mm · "
                         f"{(treffer.get('rubrik') or [''])[-1]}</span>")
        details.setWordWrap(True)
        seite = QPushButton('Seite ansehen'); seite.clicked.connect(self._seite)
        kopie = QPushButton('Nummer kopieren')
        kopie.clicked.connect(lambda: (QGuiApplication.clipboard().setText(treffer['artikel']),
                                       fenster.statusBar().showMessage(f"{treffer['artikel']} kopiert", 3000)))
        knoepfe = QHBoxLayout(); knoepfe.addWidget(seite); knoepfe.addWidget(kopie)
        lay = QVBoxLayout(self); lay.addWidget(b); lay.addWidget(titel); lay.addWidget(details); lay.addLayout(knoepfe)
        self.setFixedWidth(bild.shape[1] + 24)

    def mouseDoubleClickEvent(self, e): self._seite()

    def _seite(self): self.fenster.seite_zeigen(self.t)


# ---------- Hauptfenster -------------------------------------------------------------------

class Hauptfenster(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP); self.setAcceptDrops(True)
        self.ein = QSettings(APP, APP)
        self.kat, self.ph, self.fotopfad, self.thread = None, None, None, None

        # linke Spalte: Muster
        self.foto = QLabel('Foto einer Musterdichtung hierher ziehen\noder über „Foto öffnen …“ laden.')
        self.foto.setAlignment(Qt.AlignCenter); self.foto.setMinimumSize(300, 300)
        self.foto.setFrameShape(QFrame.StyledPanel); self.foto.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.masse = QLabel(''); self.masse.setWordWrap(True)
        self.rubrik = QComboBox(); self.rubrik.setMinimumWidth(260)
        self.kaestchen = QDoubleSpinBox(suffix=' mm', decimals=1, minimum=1, maximum=20, singleStep=0.5)
        self.kaestchen.setValue(float(self.ein.value('kaestchen', 5.0)))
        self.anzahl = QSpinBox(minimum=3, maximum=40); self.anzahl.setValue(int(self.ein.value('anzahl', 12)))
        oeffnen = QPushButton('Foto öffnen …'); oeffnen.clicked.connect(self.foto_oeffnen)
        self.suchen_knopf = QPushButton('Suchen'); self.suchen_knopf.setDefault(True)
        self.suchen_knopf.clicked.connect(lambda: self.suchen(neu_auswerten=False))
        form = QFormLayout()
        form.addRow('Rubrik', self.rubrik); form.addRow('Kästchengröße', self.kaestchen); form.addRow('Anzahl Treffer', self.anzahl)
        links = QVBoxLayout(); links.addWidget(oeffnen); links.addWidget(self.foto, 1); links.addWidget(self.masse)
        links.addLayout(form); links.addWidget(self.suchen_knopf)
        lw = QWidget(); lw.setLayout(links); lw.setMinimumWidth(340)

        # rechte Seite: Treffer
        self.raster = QGridLayout(); self.raster.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        rw = QWidget(); rw.setLayout(self.raster)
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True); self.scroll.setWidget(rw)
        self.leer = QLabel(); self.leer.setAlignment(Qt.AlignCenter); self.leer.setWordWrap(True)
        rechts = QVBoxLayout(); rechts.addWidget(self.leer); rechts.addWidget(self.scroll, 1)
        rwid = QWidget(); rwid.setLayout(rechts)

        sp = QSplitter(); sp.addWidget(lw); sp.addWidget(rwid); sp.setStretchFactor(1, 1)
        self.setCentralWidget(sp)

        m = self.menuBar().addMenu('&Datei')
        a = QAction('Foto öffnen …', self, shortcut=QKeySequence.Open); a.triggered.connect(self.foto_oeffnen); m.addAction(a)
        m.addSeparator()
        a = QAction('Katalog einlesen …', self); a.triggered.connect(self.katalog_einlesen); m.addAction(a)
        a = QAction('Katalog-Informationen', self); a.triggered.connect(self.katalog_info); m.addAction(a)
        m.addSeparator()
        a = QAction('Beenden', self, shortcut=QKeySequence.Quit); a.triggered.connect(self.close); m.addAction(a)
        self.rubrik.currentIndexChanged.connect(lambda _: self.suchen(neu_auswerten=False) if self.ph else None)
        self.kaestchen.editingFinished.connect(lambda: self.suchen(neu_auswerten=True) if self.fotopfad else None)

        geo = self.ein.value('geometrie')
        if geo: self.restoreGeometry(geo)
        else: self.resize(1400, 900)
        self.katalog_laden()

    # --- Katalog ---
    def katalog_laden(self):
        p = index_pfad()
        self.kat = None
        if os.path.exists(p):
            try:
                self.kat = suche.Katalog(p)
            except Exception as e:
                QMessageBox.warning(self, 'Katalog', f'Der gespeicherte Katalog-Index ist nicht lesbar ({e}).\n\n'
                                    'Bitte über Datei → Katalog einlesen … neu einlesen.')
        self.rubrik.blockSignals(True); self.rubrik.clear(); self.rubrik.addItem('Alle Rubriken', None)
        if self.kat:
            for r in self.kat.rubriken():
                self.rubrik.addItem('    ' * (len(r) - 1) + r[-1], r)
            gemerkt = self.ein.value('rubrik')
            if gemerkt:
                i = self.rubrik.findText(gemerkt)
                if i >= 0: self.rubrik.setCurrentIndex(i)
        self.rubrik.blockSignals(False)
        self._status_katalog(); self._leer_text()

    def _status_katalog(self):
        if not self.kat:
            self.statusBar().showMessage('Noch kein Katalog eingelesen.'); return
        i = self.kat.info
        txt = f"Katalog: {i.get('pdf_name', '?')} · {len(self.kat.meta)} Profile · eingelesen am {i.get('erstellt', '?')[:10]}"
        pdf = self.pdf_pfad()
        if pdf and os.path.exists(pdf) and (os.path.getsize(pdf) != i.get('pdf_groesse')
                                            or abs(os.path.getmtime(pdf) - i.get('pdf_mtime', 0)) > 2):
            txt += ' · Die Katalogdatei wurde seitdem geändert. Über Datei → Katalog einlesen neu einlesen.'
        self.statusBar().showMessage(txt)

    def pdf_pfad(self):
        return self.ein.value('pdf_pfad') or (self.kat.info.get('pdf') if self.kat else None)

    def katalog_einlesen(self):
        start = os.path.dirname(self.pdf_pfad() or '') or os.path.expanduser('~')
        pdf, _ = QFileDialog.getOpenFileName(self, 'Katalog-PDF auswählen', start, 'PDF (*.pdf)')
        if not pdf: return
        self.fortschritt = QProgressDialog('Katalog wird eingelesen …', 'Abbrechen', 0, 100, self)
        self.fortschritt.setWindowTitle('Katalog einlesen'); self.fortschritt.setWindowModality(Qt.WindowModal)
        self.fortschritt.setMinimumDuration(0); self.fortschritt.setValue(0)
        self.ithread = IndexThread(pdf, index_pfad())
        self.fortschritt.canceled.connect(self.ithread.stop)
        self.ithread.fortschritt.connect(lambda k, n: (self.fortschritt.setMaximum(n), self.fortschritt.setValue(k),
                                                       self.fortschritt.setLabelText(f'Seite {k} von {n} ausgewertet …')))
        self.ithread.fertig.connect(lambda r: self._index_fertig(r, pdf))
        self.ithread.fehler.connect(lambda t: (self.fortschritt.close(), QMessageBox.warning(self, 'Katalog einlesen', t)))
        self.ithread.start()

    def _index_fertig(self, r, pdf):
        self.fortschritt.close()
        if r is None:
            self.statusBar().showMessage('Einlesen abgebrochen, der bisherige Katalog bleibt aktiv.', 6000); return
        self.ein.setValue('pdf_pfad', pdf)
        self.katalog_laden()
        info = r['info']
        txt = f"{info['profile']} Profile aus {info['seiten']} Seiten eingelesen."
        if r['neu'] is not None:
            txt += f"\n\nNeu hinzugekommen: {len(r['neu'])}\nEntfallen: {len(r['weg'])}"
            if r['neu']: txt += '\n\nNeu: ' + ', '.join(r['neu'][:40]) + (' …' if len(r['neu']) > 40 else '')
            if r['weg']: txt += '\n\nEntfallen: ' + ', '.join(r['weg'][:40]) + (' …' if len(r['weg']) > 40 else '')
        if info['fehler']:
            txt += f"\n\n{len(info['fehler'])} Seiten konnten nicht ausgewertet werden (Details unter Katalog-Informationen)."
        QMessageBox.information(self, 'Katalog eingelesen', txt)
        if self.ph: self.suchen(neu_auswerten=False)

    def katalog_info(self):
        if not self.kat:
            QMessageBox.information(self, 'Katalog', 'Noch kein Katalog eingelesen. Über Datei → Katalog einlesen die PDF auswählen.'); return
        i = self.kat.info
        from collections import Counter
        c = Counter(' › '.join(m.get('rubrik', [])) or '(ohne Rubrik)' for m in self.kat.meta)
        zeilen = ''.join(f'<tr><td>{k}</td><td align=right>{v}</td></tr>' for k, v in sorted(c.items()))
        fehler = ''.join(f'<li>{f}</li>' for f in i.get('fehler', []))
        html = (f"<p><b>{i.get('pdf_name')}</b><br>{i.get('pdf')}<br>{i.get('seiten')} Seiten, {len(self.kat.meta)} Profile,"
                f" eingelesen am {i.get('erstellt', '').replace('T', ' ')}</p><table>{zeilen}</table>"
                + (f'<p>Nicht auswertbar:</p><ul>{fehler}</ul>' if fehler else ''))
        d = QDialog(self); d.setWindowTitle('Katalog-Informationen'); t = QTextBrowser(); t.setHtml(html)
        QVBoxLayout(d).addWidget(t); d.resize(600, 500); d.exec()

    # --- Foto & Suche ---
    def foto_oeffnen(self):
        start = self.ein.value('fotoordner') or os.path.expanduser('~')
        p, _ = QFileDialog.getOpenFileName(self, 'Foto der Musterdichtung', start, BILDTYPEN)
        if p: self.foto_laden(p)

    def foto_laden(self, p):
        self.ein.setValue('fotoordner', os.path.dirname(p))
        self.fotopfad, self.ph = p, None
        self.foto.setText('Foto wird ausgewertet …'); self.masse.setText('')
        self.suchen(neu_auswerten=True)

    def suchen(self, neu_auswerten):
        if not self.fotopfad or (self.thread and self.thread.isRunning()): return
        self.suchen_knopf.setEnabled(False); self.suchen_knopf.setText('Suche läuft …')
        self.thread = SuchThread(self.kat, self.fotopfad, self.kaestchen.value(), self.rubrik.currentData(),
                                 self.anzahl.value(), None if neu_auswerten else self.ph)
        self.thread.fertig.connect(self._ergebnis); self.thread.fehler.connect(self._fehler)
        self.thread.start()

    def _knopf_frei(self):
        self.suchen_knopf.setEnabled(True); self.suchen_knopf.setText('Suchen')

    def _fehler(self, t):
        self._knopf_frei(); self.foto.setText(t); self.masse.setText('')

    def _ergebnis(self, ph, treffer):
        self._knopf_frei(); self.ph = ph
        pm = np_zu_pixmap(fotovorschau(ph))
        self.foto.setPixmap(pm.scaled(self.foto.size() - QSize(8, 8), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.masse.setText(f"Erkannter Umriss (rot): ca. {ph['breite_mm']:.1f} × {ph['hoehe_mm']:.1f} mm "
                           f"bei {self.kaestchen.value():.1f} mm Kästchen.")
        self._treffer_zeigen(treffer)

    def _treffer_zeigen(self, treffer):
        for k in getattr(self, 'karten', []):
            self.raster.removeWidget(k); k.deleteLater()
        self.karten = []
        self._leer_text(treffer)
        self.karten = [Trefferkarte(self, n + 1, t, vergleichsbild(self.kat, t, self.ph['sil']))
                       for n, t in enumerate(treffer)]
        self._anordnen()

    def _anordnen(self):
        karten = getattr(self, 'karten', [])
        spalten = max(1, (self.scroll.viewport().width() - 10) // 262)
        for n, k in enumerate(karten):
            self.raster.removeWidget(k); self.raster.addWidget(k, n // spalten, n % spalten)

    def _leer_text(self, treffer=None):
        if not self.kat:
            t = 'Noch kein Katalog vorhanden. Über Datei → Katalog einlesen die Katalog-PDF auswählen. Das dauert einmalig ein paar Minuten.'
        elif not self.fotopfad:
            t = 'Foto einer Musterdichtung links hineinziehen. Die ähnlichsten Profile erscheinen hier.'
        elif treffer is not None and not treffer:
            t = 'In dieser Rubrik gibt es keine Profile. Andere Rubrik wählen.'
        elif treffer:
            t = 'Schwarz: Katalogprofil im Maßstab 1:1 auf Millimeterraster. Rot: Umriss des Musters.'
        else:
            t = ''
        self.leer.setText(t)

    def seite_zeigen(self, t):
        pdf = self.pdf_pfad()
        if not pdf or not os.path.exists(pdf):
            QMessageBox.information(self, 'Katalog-PDF nicht gefunden',
                                    'Die Katalog-PDF liegt nicht mehr am gespeicherten Ort. Bitte die Datei auswählen.')
            pdf, _ = QFileDialog.getOpenFileName(self, 'Katalog-PDF auswählen', os.path.expanduser('~'), 'PDF (*.pdf)')
            if not pdf: return
            self.ein.setValue('pdf_pfad', pdf)
        SeitenDialog(self, pdf, t).exec()

    # --- Drag & Drop, Beenden ---
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls(): e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            if u.isLocalFile(): self.foto_laden(u.toLocalFile()); break

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._anordnen()

    def closeEvent(self, e):
        self.ein.setValue('geometrie', self.saveGeometry()); self.ein.setValue('kaestchen', self.kaestchen.value())
        self.ein.setValue('anzahl', self.anzahl.value()); self.ein.setValue('rubrik', self.rubrik.currentText())
        super().closeEvent(e)


def main():
    multiprocessing.set_start_method('spawn', force=True)   # sicher neben Qt-Threads
    app = QApplication(sys.argv); app.setApplicationName(APP); app.setOrganizationName(APP)
    app.setDesktopFileName('dichtungsfinder')
    w = Hauptfenster(); w.show()
    if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]): w.foto_laden(sys.argv[1])
    sys.exit(app.exec())
