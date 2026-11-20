#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║           Filester.gg Video-Downloader                       ║
║                                                              ║
║  Automatischer Massen-Download von Videos aus Filester.gg-   ║
║  Ordnern mit Fortschrittsanzeige, Wiederaufnahme und         ║
║  umfassender Fehlerbehandlung.                               ║
╚══════════════════════════════════════════════════════════════╝

Verwendung:
    python main.py                          # Interaktiver Modus
    python main.py <URL>                    # Direkte URL-Eingabe
    python main.py <URL> -o ./mein_ordner   # Eigenes Zielverzeichnis
    python main.py <URL> --all              # Alle Dateien (nicht nur Videos)
    python main.py <URL> --token MEIN_TOKEN # Mit API Access Token
    python main.py <URL> --login            # Mit Benutzername/Passwort
"""

import argparse
import getpass
import os
import sys
from pathlib import Path
from typing import Optional

from colorama import init as colorama_init

# UTF-8-Ausgabe unter Windows sicherstellen
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

from config import DEFAULT_OUTPUT_DIR
from scraper import FilesterScraper
from downloader import VideoDownloader
from utils import (
    setup_logging,
    sanitize_filename,
    print_header,
    print_success,
    print_error,
    print_warning,
    print_info,
    print_separator,
    print_summary,
)


def parse_arguments() -> argparse.Namespace:
    """Verarbeitet Kommandozeilen-Argumente."""
    parser = argparse.ArgumentParser(
        description="🎬 Filester.gg Video-Downloader",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Beispiele:
  python main.py
  python main.py https://filester.gg/f/abc123
  python main.py https://filester.gg/f/abc123 --token DEIN_API_KEY
  python main.py https://filester.gg/f/abc123 -o ./videos
        """,
    )
    parser.add_argument(
        "url",
        nargs="?",
        help="Filester.gg-Link zum Ordner mit den Videos",
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help=f"Zielverzeichnis für Downloads (Standard: ./{DEFAULT_OUTPUT_DIR}/<ordnername>)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Alle Dateien herunterladen, nicht nur Videos",
    )
    parser.add_argument(
        "-t", "--token",
        type=str,
        default=None,
        help="API Access Token / Key direkt übergeben",
    )
    parser.add_argument(
        "--login",
        action="store_true",
        help="Statt API Key mit Benutzername/Passwort anmelden",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Nur die gefundenen Dateien anzeigen, ohne herunterzuladen",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Ausführliche Ausgabe (Debug-Modus)",
    )
    return parser.parse_args()


def get_url_interactively() -> str:
    """Fordert den Benutzer auf, eine URL einzugeben."""
    print_separator()
    print_info("Bitte gib den Filester.gg-Link ein:")
    print()
    url = input("  URL: ").strip()
    print()
    return url


def prompt_for_token() -> Optional[str]:
    """
    Fragt den Benutzer nach dem API Key / Token.
    Wird sichtbar im Terminal angezeigt.

    Returns:
        Eingegebener Token oder None.
    """
    print_separator()
    print_info("Bitte gib deinen Filester.gg API Key ein:")
    print_info("(Einfach Enter drücken, falls du ohne API Key fortfahren möchtest)")
    print()
    token = input("  API Key: ").strip()
    print()
    return token if token else None


def perform_login(scraper: FilesterScraper) -> bool:
    """
    Führt den Anmeldevorgang mit Benutzername/Passwort interaktiv durch.

    Args:
        scraper: FilesterScraper-Instanz.

    Returns:
        True bei erfolgreicher Anmeldung.
    """
    print_separator()
    print_info("Anmeldung bei Filester.gg (Benutzername/Passwort)")
    print()

    username = input("  E-Mail/Benutzername: ").strip()
    password = getpass.getpass("  Passwort: ")
    print()

    return scraper.login(username, password)


def display_files(files, video_only: bool):
    """
    Zeigt die gefundenen Dateien übersichtlich an.

    Args:
        files: Liste der gefundenen Dateien.
        video_only: Ob nur Videos angezeigt werden.
    """
    file_type = "Videos" if video_only else "Dateien"
    print_separator()
    print_info(f"Gefundene {file_type}: {len(files)}")
    print()

    for i, f in enumerate(files, 1):
        size_str = ""
        if f.file_size:
            from utils import format_size
            size_str = f" ({format_size(f.file_size)})"
        type_str = f" [{f.file_type}]" if f.file_type else ""

        print(f"    {i:3d}. {f.filename}{type_str}{size_str}")

    print()


def main():
    """Hauptfunktion des Filester.gg Video-Downloaders."""

    # Farbausgabe initialisieren
    colorama_init(autoreset=True)

    # Header ausgeben
    print_header()

    # Argumente verarbeiten
    args = parse_arguments()

    # ── 1. Authentifizierung / API Key ──
    # Wird jedes Mal beim Starten abgefragt (sofern nicht per -t/--token übergeben)
    token = args.token.strip() if args.token else None

    if not token and not args.login:
        token = prompt_for_token()

    scraper = FilesterScraper()

    if token:
        if scraper.authenticate_with_token(token):
            print_success("API Key erfolgreich authentifiziert.")
        else:
            print_warning("API Key gesetzt (Prüfung fehlgeschlagen, wird für Downloads verwendet).")
        print()
    elif args.login:
        if not perform_login(scraper):
            print_error("Anmeldung fehlgeschlagen. Versuche trotzdem fortzufahren...")
            print()
    else:
        print_info("Fahre ohne API Key fort.")
        print()

    # ── 2. URL ermitteln ──
    url = args.url
    if not url:
        url = get_url_interactively()

    if not url:
        print_error("Keine URL angegeben. Programm wird beendet.")
        sys.exit(1)

    # URL validieren
    if not FilesterScraper.validate_url(url):
        print_error(
            "Ungültige URL. Bitte eine gültige Filester.gg-URL angeben.\n"
            "  Beispiel: https://filester.gg/f/a4cbcda65255feb2"
        )
        sys.exit(1)

    print_success(f"URL erkannt: {url}")

    # Seite analysieren
    print_separator()
    print_info("Analysiere Seite...")
    print()

    video_only = not args.all
    folder = scraper.scrape_folder(url, video_only=video_only)

    # Falls es sich um ein einzelnes Video mit übergeordnetem Ordner handelt
    if folder.is_single_file and folder.parent_folder_url:
        print_separator()
        print_info(f"Einzelnes Video erkannt: {folder.folder_name}")
        print_info(
            f"Dieses Video gehört zum Ordner: '{folder.parent_folder_name}' "
            f"({folder.parent_folder_url})"
        )
        print()
        choice = input(
            "  Was möchtest du tun?\n"
            "    [1] Nur dieses einzelne Video herunterladen\n"
            "    [2] Den GESAMTEN Ordner herunterladen (alle Videos)\n"
            "  Auswahl [1/2] (Standard: 1): "
        ).strip()
        print()

        if choice == "2":
            print_info(f"Analysiere übergeordneten Ordner: {folder.parent_folder_url} ...")
            folder = scraper.scrape_folder(folder.parent_folder_url, video_only=video_only)

    if not folder.files:
        file_type = "Videos" if video_only else "Dateien"
        print_warning(
            f"Keine {file_type} auf dieser Seite gefunden.\n\n"
            "  Mögliche Ursachen:\n"
            "    • Der Link ist ungültig oder abgelaufen\n"
            "    • Die Seite erfordert einen gültigen API Key\n"
            "    • Versuche --all, um auch Nicht-Video-Dateien zu sehen"
        )
        sys.exit(0)

    # Gefundene Dateien anzeigen
    display_files(folder.files, video_only)

    # Dry-Run: nur anzeigen
    if args.dry_run:
        print_info("Trockenlauf (--dry-run): Keine Dateien heruntergeladen.")
        sys.exit(0)

    # Bestätigung einholen
    answer = input("  Download starten? [J/n]: ").strip().lower()
    if answer in ('n', 'nein', 'no'):
        print_info("Download abgebrochen.")
        sys.exit(0)

    # Ausgabeverzeichnis festlegen
    if args.output:
        output_dir = Path(args.output)
    else:
        folder_name = sanitize_filename(
            folder.folder_name or folder.folder_id
        )
        output_dir = Path(DEFAULT_OUTPUT_DIR) / folder_name

    # Logging einrichten
    log_dir = output_dir / ".logs"
    logger = setup_logging(log_dir)

    # Download starten
    print()
    print_separator()
    print_info(f"Zielverzeichnis: {output_dir.resolve()}")
    print()

    downloader = VideoDownloader(
        session=scraper.session,
        output_dir=output_dir,
        url_resolver=scraper.resolve_download_url,
    )

    try:
        stats = downloader.download_all(folder.files)
    except KeyboardInterrupt:
        print_warning("\n\nDownload durch Benutzer abgebrochen (Strg+C).")
        stats = downloader.stats

    # Zusammenfassung ausgeben
    print_summary(
        total=stats["total"],
        success=stats["success"],
        failed=stats["failed"],
        skipped=stats["skipped"],
        errors=stats["errors"],
    )

    # Exit-Code
    if stats["failed"] > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
