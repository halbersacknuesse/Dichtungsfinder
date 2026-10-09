import sys


def katalog_einlesen_konsole(pdf):
    """dichtungsfinder --katalog-einlesen katalog.pdf  (ohne Oberfläche, z.B. per SSH)"""
    import multiprocessing, os, time
    multiprocessing.set_start_method('spawn', force=True)
    from . import indexer, suche
    from .app import index_pfad
    ziel = index_pfad(); t = time.time()
    eintraege, fehler, n = indexer.index_pdf(pdf, fortschritt=lambda k, g: print(f'\r{k}/{g} Seiten', end='', flush=True))
    alt = suche.Katalog(ziel).meta if os.path.exists(ziel) else None
    info = indexer.speichern(eintraege, ziel, pdf, n, fehler)
    print(f"\n{info['profile']} Profile in {time.time() - t:.0f} s eingelesen, {len(fehler)} Seiten mit Fehlern.")
    if alt is not None:
        neu, weg = indexer.vergleich(alt, [{k: v for k, v in e.items() if k != 'sil'} for e in eintraege])
        print(f'Neu: {len(neu)}  Entfallen: {len(weg)}')


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--katalog-einlesen':
        katalog_einlesen_konsole(sys.argv[2])
    else:
        from .app import main
        main()
