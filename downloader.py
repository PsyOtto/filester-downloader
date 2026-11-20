"""
Filester.gg Video-Downloader Download-Modul.

Verantwortlich für das Herunterladen einzelner Dateien mit
Fortschrittsanzeige, Wiederaufnahme und Fehlerbehandlung.
"""

import os
import time
import logging
from pathlib import Path
from typing import Optional, Callable

import requests
from tqdm import tqdm

from config import (
    USER_AGENT,
    REQUEST_TIMEOUT,
    MAX_RETRIES,
    RETRY_BASE_DELAY,
    CHUNK_SIZE,
    DOWNLOAD_DELAY,
    PROGRESS_BAR_FORMAT,
)
from scraper import FileInfo
from utils import (
    sanitize_filename,
    get_unique_filepath,
    format_size,
    print_success,
    print_error,
    print_warning,
    print_info,
)

logger = logging.getLogger("filester_downloader")


class VideoDownloader:
    """
    Downloader für Filester.gg-Videos.

    Unterstützt:
    - Fortschrittsanzeige mit tqdm
    - Wiederaufnahme unterbrochener Downloads (HTTP Range Requests)
    - Automatische Wiederholung bei Fehlern
    - Streaming großer Dateien in Chunks
    """

    def __init__(self, session: requests.Session, output_dir: Path,
                 url_resolver: Optional[Callable[[str], Optional[str]]] = None):
        """
        Initialisiert den Downloader.

        Args:
            session: HTTP-Session (ggf. mit Authentifizierung).
            output_dir: Zielverzeichnis für Downloads.
            url_resolver: Optionale Funktion zum dynamischen Abrufen von Download-URLs via Slug.
        """
        self.session = session
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.url_resolver = url_resolver

        # Statistiken
        self.stats = {
            "total": 0,
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "errors": [],
        }

    def _get_file_info_from_head(self, url: str) -> dict:
        """
        Ermittelt Datei-Metadaten per HEAD-Request.

        Args:
            url: Download-URL.

        Returns:
            Dictionary mit Content-Length, Accept-Ranges und Dateiname.
        """
        info = {
            "content_length": None,
            "accept_ranges": False,
            "filename": None,
        }

        try:
            response = self.session.head(
                url, timeout=REQUEST_TIMEOUT, allow_redirects=True
            )
            response.raise_for_status()

            headers = response.headers

            # Dateigröße
            content_length = headers.get("Content-Length")
            if content_length and content_length.isdigit():
                info["content_length"] = int(content_length)

            # Wiederaufnahme möglich?
            info["accept_ranges"] = (
                headers.get("Accept-Ranges", "").lower() == "bytes"
            )

            # Dateiname aus Content-Disposition
            content_disp = headers.get("Content-Disposition", "")
            if "filename=" in content_disp:
                # filename="video.mp4" oder filename*=UTF-8''video.mp4
                import re
                match = re.search(
                    r'filename\*?=["\']?(?:UTF-8\'\')?([^"\';\s]+)',
                    content_disp,
                    re.IGNORECASE,
                )
                if match:
                    from urllib.parse import unquote
                    info["filename"] = unquote(match.group(1))

        except requests.exceptions.RequestException as e:
            logger.debug(f"HEAD-Request fehlgeschlagen für {url}: {e}")

        return info

    def download_file(self, file_info: FileInfo,
                      index: int = 0, total: int = 0) -> bool:
        """
        Lädt eine einzelne Datei herunter.

        Args:
            file_info: Informationen zur herunterzuladenden Datei.
            index: Aktuelle Nummer in der Download-Liste.
            total: Gesamtanzahl der Downloads.

        Returns:
            True bei erfolgreichem Download.
        """
        prefix = f"[{index}/{total}]" if total > 0 else ""

        # Falls keine Download-URL vorhanden ist, aber ein Slug: JIT auflösen
        if (not file_info.download_url or file_info.download_url.strip() == "") and file_info.slug and self.url_resolver:
            print_info(f"{prefix} Erzeuge Download-Link für: {file_info.filename}")
            resolved_url = self.url_resolver(file_info.slug)
            if not resolved_url:
                print_error(f"{prefix} Konnte keinen Download-Link abrufen: {file_info.filename}")
                return False
            file_info.download_url = resolved_url

        url = file_info.download_url
        if not url:
            print_error(f"{prefix} Keine Download-URL vorhanden: {file_info.filename}")
            return False

        # Dateiname bestimmen und bereinigen
        head_info = self._get_file_info_from_head(url)
        filename = sanitize_filename(
            head_info["filename"] or file_info.filename
        )
        total_size = head_info["content_length"] or file_info.file_size
        can_resume = head_info["accept_ranges"]

        # Ziel-Dateipfad
        filepath = get_unique_filepath(self.output_dir, filename)

        print_info(
            f"{prefix} Starte Download: {filename}"
            + (f" ({format_size(total_size)})" if total_size else "")
        )

        # Wiederaufnahme prüfen
        temp_filepath = filepath.with_suffix(filepath.suffix + ".part")
        downloaded_bytes = 0

        if temp_filepath.exists():
            downloaded_bytes = temp_filepath.stat().st_size
            if total_size and downloaded_bytes >= total_size:
                # Datei ist bereits vollständig
                temp_filepath.rename(filepath)
                print_success(f"{prefix} Bereits vorhanden: {filename}")
                return True
            elif can_resume and downloaded_bytes > 0:
                print_info(
                    f"  Setze Download fort ab {format_size(downloaded_bytes)}"
                )
            else:
                # Neustart, wenn keine Wiederaufnahme möglich
                downloaded_bytes = 0

        # Download mit Wiederholungsversuchen
        for attempt in range(MAX_RETRIES):
            try:
                success = self._download_with_progress(
                    url=url,
                    filepath=filepath,
                    temp_filepath=temp_filepath,
                    total_size=total_size,
                    start_byte=downloaded_bytes if can_resume else 0,
                    prefix=prefix,
                )

                if success:
                    print_success(f"{prefix} Abgeschlossen: {filename}")
                    return True

            except requests.exceptions.ConnectionError:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                print_warning(
                    f"  Verbindung unterbrochen. "
                    f"Wiederholung in {delay}s... "
                    f"(Versuch {attempt + 2}/{MAX_RETRIES})"
                )
                time.sleep(delay)

                # Bereits heruntergeladene Bytes aktualisieren
                if temp_filepath.exists() and can_resume:
                    downloaded_bytes = temp_filepath.stat().st_size

            except requests.exceptions.Timeout:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                print_warning(
                    f"  Timeout. Wiederholung in {delay}s... "
                    f"(Versuch {attempt + 2}/{MAX_RETRIES})"
                )
                time.sleep(delay)

            except requests.exceptions.RequestException as e:
                print_error(f"  Download-Fehler: {e}")
                break

            except KeyboardInterrupt:
                print_warning("\n  Download durch Benutzer abgebrochen.")
                raise

        # Download fehlgeschlagen
        print_error(f"{prefix} Fehlgeschlagen: {filename}")
        return False

    def _download_with_progress(
        self,
        url: str,
        filepath: Path,
        temp_filepath: Path,
        total_size: Optional[int],
        start_byte: int = 0,
        prefix: str = "",
    ) -> bool:
        """
        Führt den eigentlichen Download mit Fortschrittsanzeige durch.

        Args:
            url: Download-URL.
            filepath: Endgültiger Dateipfad.
            temp_filepath: Temporärer Dateipfad während des Downloads.
            total_size: Erwartete Gesamtgröße.
            start_byte: Startposition für Wiederaufnahme.
            prefix: Präfix für die Anzeige.

        Returns:
            True bei erfolgreichem Download.
        """
        headers = {}
        if start_byte > 0:
            headers["Range"] = f"bytes={start_byte}-"

        response = self.session.get(
            url,
            headers=headers,
            stream=True,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()

        # Tatsächliche Größe aus der Antwort ermitteln
        content_length = response.headers.get("Content-Length")
        if content_length and content_length.isdigit():
            remaining_size = int(content_length)
            if total_size is None:
                total_size = remaining_size + start_byte
        else:
            remaining_size = None

        # Datei öffnen (Anhängen oder Neuerstellen)
        mode = "ab" if start_byte > 0 else "wb"

        with open(temp_filepath, mode) as f:
            with tqdm(
                total=total_size,
                initial=start_byte,
                unit='B',
                unit_scale=True,
                unit_divisor=1024,
                desc=f"    ↓",
                bar_format=PROGRESS_BAR_FORMAT,
                leave=True,
                ncols=70,
            ) as progress_bar:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if chunk:
                        bytes_written = f.write(chunk)
                        progress_bar.update(bytes_written)

        # Prüfe ob Download vollständig ist
        actual_size = temp_filepath.stat().st_size
        if total_size and actual_size < total_size:
            logger.warning(
                f"Download unvollständig: {actual_size}/{total_size} Bytes"
            )
            return False

        # Temporäre Datei in endgültige umbenennen
        temp_filepath.rename(filepath)
        return True

    def download_all(self, files: list[FileInfo]) -> dict:
        """
        Lädt alle übergebenen Dateien herunter.

        Args:
            files: Liste der herunterzuladenden Dateien.

        Returns:
            Statistik-Dictionary mit Ergebnissen.
        """
        self.stats["total"] = len(files)

        if not files:
            print_warning("Keine Dateien zum Herunterladen gefunden.")
            return self.stats

        print_info(
            f"Starte Download von {len(files)} Video(s) "
            f"nach: {self.output_dir}"
        )
        print()

        for i, file_info in enumerate(files, start=1):
            try:
                success = self.download_file(file_info, index=i, total=len(files))

                if success:
                    self.stats["success"] += 1
                else:
                    self.stats["failed"] += 1
                    self.stats["errors"].append({
                        "filename": file_info.filename,
                        "url": file_info.download_url,
                        "error": "Download fehlgeschlagen nach "
                                 f"{MAX_RETRIES} Versuchen",
                    })

            except KeyboardInterrupt:
                print_warning(
                    f"\nDownload abgebrochen. {i - 1}/{len(files)} "
                    f"Dateien verarbeitet."
                )
                self.stats["skipped"] = len(files) - i
                break

            except Exception as e:
                self.stats["failed"] += 1
                self.stats["errors"].append({
                    "filename": file_info.filename,
                    "url": file_info.download_url,
                    "error": str(e),
                })
                print_error(f"Unerwarteter Fehler bei {file_info.filename}: {e}")
                logger.exception(f"Fehler beim Download von {file_info.filename}")

            # Pause zwischen Downloads (Rate-Limiting vermeiden)
            if i < len(files):
                time.sleep(DOWNLOAD_DELAY)

        return self.stats
