"""
Filester.gg Video-Downloader – Hilfsfunktionen.

Stellt Utility-Funktionen für Dateinamen-Bereinigung, Größenformatierung,
Fortschrittsanzeige und Logging bereit.
"""

import os
import re
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from colorama import Fore, Style

from config import MAX_FILENAME_LENGTH


# ─── Logging ─────────────────────────────────────────────────────────────────

def setup_logging(log_dir: Optional[Path] = None) -> logging.Logger:
    """
    Richtet das Logging-System ein.

    Args:
        log_dir: Verzeichnis für die Log-Datei. Falls None, wird das aktuelle
                 Verzeichnis verwendet.

    Returns:
        Konfigurierter Logger.
    """
    logger = logging.getLogger("filester_downloader")
    logger.setLevel(logging.DEBUG)

    # Konsolen-Handler (nur INFO und höher)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter("%(message)s")
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)

    # Datei-Handler (alles, inkl. DEBUG)
    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = log_dir / f"download_{timestamp}.log"
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)

    return logger


# ─── Dateinamen ──────────────────────────────────────────────────────────────

def sanitize_filename(filename: str) -> str:
    """
    Bereinigt einen Dateinamen, indem ungültige Zeichen entfernt werden.

    Args:
        filename: Ursprünglicher Dateiname.

    Returns:
        Bereinigter, sicherer Dateiname.
    """
    # Ungültige Zeichen für Windows/Linux/macOS entfernen
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', filename)

    # Mehrfache Unterstriche/Leerzeichen zusammenfassen
    filename = re.sub(r'[_\s]+', '_', filename)

    # Führende/abschließende Punkte und Leerzeichen entfernen
    filename = filename.strip('. ')

    # Dateiname kürzen, falls zu lang
    name, ext = os.path.splitext(filename)
    if len(name) > MAX_FILENAME_LENGTH:
        name = name[:MAX_FILENAME_LENGTH]
    filename = name + ext

    # Fallback für leere Dateinamen
    if not filename or filename == ext:
        filename = f"video_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext or '.mp4'}"

    return filename


def get_unique_filepath(directory: Path, filename: str) -> Path:
    """
    Erstellt einen eindeutigen Dateipfad und vermeidet Überschreibungen.
    Falls die Datei bereits existiert, wird eine Nummer angehängt.

    Args:
        directory: Zielverzeichnis.
        filename: Gewünschter Dateiname.

    Returns:
        Eindeutiger Dateipfad.
    """
    filepath = directory / filename
    if not filepath.exists():
        return filepath

    name, ext = os.path.splitext(filename)
    counter = 1
    while True:
        new_filename = f"{name}_{counter}{ext}"
        filepath = directory / new_filename
        if not filepath.exists():
            return filepath
        counter += 1


# ─── Formatierung ────────────────────────────────────────────────────────────

def format_size(size_bytes: int) -> str:
    """
    Formatiert eine Dateigröße in Bytes in eine lesbare Darstellung.

    Args:
        size_bytes: Größe in Bytes.

    Returns:
        Formatierte Größe (z.B. '1.5 GB').
    """
    if size_bytes == 0:
        return "0 B"

    units = ['B', 'KB', 'MB', 'GB', 'TB']
    unit_index = 0
    size = float(size_bytes)

    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1

    if unit_index == 0:
        return f"{int(size)} {units[unit_index]}"
    return f"{size:.2f} {units[unit_index]}"


# ─── Konsolenausgabe ────────────────────────────────────────────────────────

def print_header():
    """Gibt den Programm-Header aus."""
    print(f"\n{Fore.CYAN}{'═' * 60}")
    print(f"  🎬  Filester.gg Video-Downloader")
    print(f"{'═' * 60}{Style.RESET_ALL}\n")


def print_success(message: str):
    """Gibt eine Erfolgsmeldung in Grün aus."""
    print(f"  {Fore.GREEN}✓{Style.RESET_ALL} {message}")


def print_error(message: str):
    """Gibt eine Fehlermeldung in Rot aus."""
    print(f"  {Fore.RED}✗{Style.RESET_ALL} {message}")


def print_warning(message: str):
    """Gibt eine Warnmeldung in Gelb aus."""
    print(f"  {Fore.YELLOW}⚠{Style.RESET_ALL} {message}")


def print_info(message: str):
    """Gibt eine Informationsmeldung in Blau aus."""
    print(f"  {Fore.BLUE}ℹ{Style.RESET_ALL} {message}")


def print_separator():
    """Gibt eine Trennlinie aus."""
    print(f"  {Fore.CYAN}{'─' * 56}{Style.RESET_ALL}")


def print_summary(total: int, success: int, failed: int,
                   skipped: int, errors: list[dict]):
    """
    Gibt eine Zusammenfassung des Download-Vorgangs aus.

    Args:
        total: Gesamtzahl der gefundenen Videos.
        success: Anzahl erfolgreicher Downloads.
        failed: Anzahl fehlgeschlagener Downloads.
        skipped: Anzahl übersprungener Dateien.
        errors: Liste mit Fehlerdetails.
    """
    print(f"\n{Fore.CYAN}{'═' * 60}")
    print(f"  📊  Download-Zusammenfassung")
    print(f"{'═' * 60}{Style.RESET_ALL}\n")

    print(f"  Gefundene Videos:    {total}")
    print(f"  {Fore.GREEN}Erfolgreich:{Style.RESET_ALL}         {success}")

    if skipped > 0:
        print(f"  {Fore.YELLOW}Übersprungen:{Style.RESET_ALL}        {skipped}")

    if failed > 0:
        print(f"  {Fore.RED}Fehlgeschlagen:{Style.RESET_ALL}      {failed}")

    if errors:
        print(f"\n  {Fore.RED}Fehlerprotokoll:{Style.RESET_ALL}")
        print_separator()
        for err in errors:
            print(f"    • {err['filename']}: {err['error']}")

    print(f"\n{Fore.CYAN}{'═' * 60}{Style.RESET_ALL}\n")
