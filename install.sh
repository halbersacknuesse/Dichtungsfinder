#!/usr/bin/env bash
# Dichtungsfinder für den aktuellen Benutzer installieren (Fedora/Linux, ohne root).
set -euo pipefail
ZIEL="${XDG_DATA_HOME:-$HOME/.local/share}/dichtungsfinder"
QUELLE="$(cd "$(dirname "$0")" && pwd)"

echo "Installiere nach $ZIEL …"
mkdir -p "$ZIEL"
[ -d "$ZIEL/venv" ] || python3 -m venv "$ZIEL/venv"
"$ZIEL/venv/bin/pip" install -q --upgrade pip
"$ZIEL/venv/bin/pip" install -q -r "$QUELLE/requirements.txt"

rm -rfv "$ZIEL/app"; mkdir -p "$ZIEL/app"
cp -r "$QUELLE/dichtungsfinder" "$ZIEL/app/"

mkdir -p "$HOME/.local/bin"
cat > "$HOME/.local/bin/dichtungsfinder" <<LAUNCHER
#!/usr/bin/env bash
PYTHONPATH="$ZIEL/app" exec "$ZIEL/venv/bin/python" -m dichtungsfinder "\$@"
LAUNCHER
chmod +x "$HOME/.local/bin/dichtungsfinder"

mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/dichtungsfinder.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Dichtungsfinder
Comment=Dichtung per Foto im Herstellerkatalog finden
Exec=$HOME/.local/bin/dichtungsfinder %f
Icon=edit-find
Terminal=false
Categories=Graphics;Utility;
MimeType=image/heic;image/heif;image/jpeg;image/png;image/webp;
DESKTOP
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

echo "Fertig. Start über das Anwendungsmenü (Dichtungsfinder) oder im Terminal mit: dichtungsfinder"
