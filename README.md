# Dichtungsfinder

Desktop-Programm für Linux, das zu einem Foto einer Musterdichtung die ähnlichsten Profile in
einem Dichtungskatalog (PDF) heraussucht. Statt eine ganze Katalogrubrik durchzublättern, schaut
man sich nur noch eine Handvoll Kandidaten an, jeweils mit Artikelnummer und Katalogseite.

Das Programm liefert **Vorschläge, keine sichere Erkennung**. Vor einer Bestellung das Profil
immer mit Katalog und Muster abgleichen.

## Wichtig: Der Katalog ist nicht enthalten

Dieses Repository enthält **keinen Katalog** und keine daraus erzeugten Daten. Die Katalog-PDF
musst du selbst beschaffen.

Entwickelt und getestet wurde mit dem Profilkatalog von GfA-Dichtungen (GfA-Sealsystems). Eine
digitale Fassung stellt der Hersteller nach aktuellem Stand **nicht** zum Download bereit. Im Netz
kursieren inoffizielle Kopien unklarer Herkunft. Woher du den Katalog beziehst und ob du ihn so
nutzen darfst, liegt in deiner Verantwortung. Am saubersten ist es, als Kunde beim Hersteller
direkt nach einer digitalen Fassung oder Profildaten zu fragen.

Dieses Projekt steht in keiner Verbindung zum Hersteller. Marken- und Produktnamen gehören ihren
jeweiligen Inhabern.

### Welche Kataloge funktionieren

Der Katalog muss so aufgebaut sein:

- Profilzeichnungen als **Vektorgrafik** (kein Scan), jedes Profil als schwarz gefüllte Fläche,
- im **Maßstab 1:1**,
- die **Artikelnummer als Text** direkt über der Zeichnung (Form `ABC-123`, `ABC-123-XY`),
- optional die Rubrik in der Kopfzeile, getrennt durch `•`
  (z. B. „Fenster-Systeme • Anschlagdichtungen • Schlauchprofile“). Daraus entsteht der Rubrikfilter.

Andere Kataloge mit ähnlichem Aufbau können funktionieren, sind aber nicht getestet.

## Installation (Fedora und andere Linux-Distributionen)

Voraussetzung ist Python 3.10 oder neuer mit `venv` (bei Fedora vorinstalliert).

    ./install.sh

Das Skript legt eine eigene Python-Umgebung unter `~/.local/share/dichtungsfinder/` an, dazu den
Befehl `dichtungsfinder` und einen Eintrag im Anwendungsmenü. Root-Rechte sind nicht nötig.

- **Aktualisieren:** `install.sh` erneut ausführen. Der eingelesene Katalog bleibt erhalten.
- **Entfernen:**

      rm -rfv ~/.local/share/dichtungsfinder ~/.local/bin/dichtungsfinder \
              ~/.local/share/applications/dichtungsfinder.desktop ~/.config/Dichtungsfinder

## Benutzung

1. **Einmalig:** Datei → Katalog einlesen … und die Katalog-PDF auswählen. Das Einlesen nutzt
   alle Prozessorkerne bis auf einen und dauert je nach Rechner einige Minuten. Bei jedem weiteren
   Start wird nur der fertige Index geladen, die PDF wird nicht erneut gelesen.
2. Foto der Musterdichtung ins Fenster ziehen oder über „Foto öffnen …“ laden
   (HEIC/HEIF, JPG, PNG, WebP, TIFF).
3. Links prüfen, ob der rote Umriss die Dichtung richtig erfasst. Bei Bedarf Rubrik oder
   Kästchengröße des Papiers anpassen.
4. Rechts erscheinen die ähnlichsten Profile: schwarz das Katalogprofil 1:1 auf Millimeterraster,
   rot der Umriss des Musters. „Seite ansehen“ zeigt die Katalogseite mit markiertem Profil,
   „Nummer kopieren“ legt die Artikelnummer für die Shopsuche in die Zwischenablage.

**Neuer Katalog:** wieder Datei → Katalog einlesen … Danach zeigt das Programm, welche
Artikelnummern neu hinzugekommen oder entfallen sind. Der vorherige Index bleibt als
`index_vorher.npz` erhalten.

**Ohne Oberfläche** (z. B. per SSH):

    dichtungsfinder --katalog-einlesen katalog.pdf

### Wo die Daten liegen

| Was | Ort |
|---|---|
| Katalog-Index | `~/.local/share/dichtungsfinder/katalog/` |
| Einstellungen (Fensterlage, Pfad zur PDF, letzte Rubrik) | `~/.config/Dichtungsfinder/` |

Alles bleibt lokal. Das Programm stellt keine Netzwerkverbindungen her.

## Fototipps

- Dichtung sauber quer abschneiden, Schnittfläche nach oben auf Karopapier legen (Standard: 5-mm-Kästchen).
- Senkrecht von oben fotografieren, Papier möglichst formatfüllend.
- Graue oder helle Dichtungen auf eine Leuchtplatte legen (Licht von unten). Dann erscheinen sie
  schwarz und werfen keinen Schatten. Ohne Gegenlicht werden sie meist nicht erkannt.
- Transparente Dichtungen werden nicht unterstützt.

## Wie es funktioniert

1. **Einlesen:** Aus jeder Katalogseite werden die Vektorpfade der Profile gelesen, mit der
   nächstgelegenen Artikelnummer verknüpft und als Silhouette im echten Maßstab gespeichert.
2. **Foto:** Die Dichtung wird vom Papier und vom Schlagschatten getrennt, der Maßstab wird
   per Fourier-Analyse aus dem Karoraster bestimmt.
3. **Vergleich:** Form (weichgezeichneter Flächenvergleich), Umriss (Chamfer-Abstand) und
   Größe werden gewichtet kombiniert, unabhängig von Drehung und Spiegelung. Das ist bewusst
   fehlertolerant: Weiches Gummi verformt sich, Kanten werden unsauber erkannt, Lippen fehlen.

## Hinweis zur Entstehung (KI)

Der Code dieses Projekts wurde zum größten Teil von einem KI-Assistenten (Claude von Anthropic)
geschrieben, im Dialog mit dem Maintainer, der Anforderungen, Testdaten und Rückmeldungen aus dem
praktischen Einsatz beigesteuert hat. Getestet wurde mit einem Katalogauszug, echten Fotos und
synthetisch verfälschten Profilen, nicht mit einer formalen Testsuite.

Der Code kann Fehler enthalten. Nutzung auf eigene Verantwortung, siehe Lizenz.

## Lizenz

Der Code steht unter der [MIT-Lizenz](LICENSE).

Die Abhängigkeiten haben eigene Lizenzen und werden von `install.sh` aus PyPI installiert, nicht
mit diesem Repository verteilt:

| Paket | Lizenz |
|---|---|
| [PyMuPDF](https://pymupdf.readthedocs.io) | **AGPL-3.0** (oder kommerzielle Lizenz von Artifex) |
| [PySide6](https://doc.qt.io/qtforpython/) | LGPL-3.0 |
| [OpenCV](https://opencv.org) | Apache-2.0 |
| [NumPy](https://numpy.org) | BSD-3-Clause |
| [Pillow](https://python-pillow.org) | MIT-CMU |
| [pillow-heif](https://github.com/bigcat88/pillow_heif) | BSD-3-Clause (enthält LGPL-Bibliotheken) |

Wer das Programm zusammen mit PyMuPDF weitergibt, etwa als fertiges Paket oder Binary, muss für
diese Gesamtheit die Bedingungen der AGPL-3.0 einhalten.
