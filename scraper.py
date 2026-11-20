"""
Filester.gg Video-Downloader – Scraper-Modul.

Analysiert Filester.gg-Seiten und extrahiert Informationen
über die verfügbaren Dateien (insbesondere Videos).
"""

import json
import re
import time
import logging
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin, urlparse, unquote

import requests
from bs4 import BeautifulSoup

from config import (
    USER_AGENT,
    REQUEST_TIMEOUT,
    FILESTER_DOMAINS,
    VIDEO_EXTENSIONS,
    MAX_RETRIES,
    RETRY_BASE_DELAY,
    API_BASE_PATH,
)

logger = logging.getLogger("filester_downloader")


# ─── Datenklassen ────────────────────────────────────────────────────────────

@dataclass
class FileInfo:
    """Repräsentiert eine einzelne Datei auf einer Filester-Seite."""
    filename: str
    download_url: str = ""
    file_size: Optional[int] = None
    file_type: Optional[str] = None
    is_video: bool = False
    slug: Optional[str] = None

    def __post_init__(self):
        """Prüft nach der Initialisierung, ob die Datei ein Video ist."""
        if self.filename:
            ext = '.' + self.filename.rsplit('.', 1)[-1].lower() if '.' in self.filename else ''
            self.is_video = ext in VIDEO_EXTENSIONS
            if not self.file_type and ext:
                self.file_type = ext.lstrip('.')


@dataclass
class FolderInfo:
    """Repräsentiert einen Filester-Ordner mit seinen Dateien."""
    folder_id: str
    folder_name: str = "Unbekannt"
    url: str = ""
    files: list[FileInfo] = field(default_factory=list)
    total_pages: int = 1
    current_page: int = 1
    is_single_file: bool = False
    parent_folder_url: Optional[str] = None
    parent_folder_name: Optional[str] = None


# ─── Scraper-Klasse ─────────────────────────────────────────────────────────

class FilesterScraper:
    """
    Scraper für Filester.gg-Seiten.

    Analysiert Ordner- und Einzelseiten und extrahiert Download-Links für
    alle verfügbaren Dateien, insbesondere Videos.
    """

    def __init__(self, session: Optional[requests.Session] = None,
                 token: Optional[str] = None):
        """
        Initialisiert den Scraper.

        Args:
            session: Optionale requests.Session für authentifizierte Zugriffe.
            token: Optionaler API Access Token für die Authentifizierung.
        """
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                      "image/webp,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        })
        self._token = None

        # Token setzen, falls übergeben
        if token:
            self.authenticate_with_token(token)

    @staticmethod
    def validate_url(url: str) -> bool:
        """
        Prüft, ob eine URL eine gültige Filester-URL ist.

        Args:
            url: Zu prüfende URL.

        Returns:
            True, wenn die URL gültig ist.
        """
        try:
            parsed = urlparse(url)
            host = (parsed.hostname or "").lower()
            is_filester_host = (
                host in FILESTER_DOMAINS
                or host.endswith(".filester.gg")
                or host.endswith(".filester.me")
                or host.endswith(".filester.sh")
            )
            return (
                parsed.scheme in ("http", "https")
                and is_filester_host
                and bool(parsed.path)
            )
        except Exception:
            return False

    @staticmethod
    def extract_slug(url: str) -> Optional[str]:
        """
        Extrahiert den File-Slug aus einer Filester-Download-URL (/d/<slug>).

        Args:
            url: Filester-URL.

        Returns:
            File-Slug oder None.
        """
        match = re.search(r'/d/([a-zA-Z0-9_-]+)', url)
        return match.group(1) if match else None

    @staticmethod
    def extract_folder_id(url: str) -> Optional[str]:
        """
        Extrahiert die Ordner-ID aus einer Filester-URL.

        Args:
            url: Filester-URL.

        Returns:
            Ordner-ID oder None.
        """
        match = re.search(r'/(?:f|folder)/([a-zA-Z0-9_-]+)', url)
        return match.group(1) if match else None

    def _fetch_page(self, url: str, retries: int = MAX_RETRIES) -> Optional[str]:
        """
        Ruft eine Seite ab und gibt den HTML-Inhalt zurück.

        Args:
            url: URL der Seite.
            retries: Anzahl der Wiederholungsversuche.

        Returns:
            HTML-Inhalt oder None bei Fehler.
        """
        for attempt in range(retries):
            try:
                response = self.session.get(url, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                return response.text
            except requests.exceptions.HTTPError as e:
                if response.status_code == 429:
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        f"Rate-Limit erreicht. Warte {delay}s... "
                        f"(Versuch {attempt + 1}/{retries})"
                    )
                    time.sleep(delay)
                else:
                    logger.error(f"HTTP-Fehler beim Abrufen von {url}: {e}")
                    return None
            except requests.exceptions.ConnectionError as e:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    f"Verbindungsfehler. Warte {delay}s... "
                    f"(Versuch {attempt + 1}/{retries})"
                )
                time.sleep(delay)
            except requests.exceptions.Timeout:
                logger.warning(
                    f"Timeout beim Abrufen von {url} "
                    f"(Versuch {attempt + 1}/{retries})"
                )
            except requests.exceptions.RequestException as e:
                logger.error(f"Fehler beim Abrufen von {url}: {e}")
                return None

        logger.error(f"Alle {retries} Versuche fehlgeschlagen für {url}")
        return None

    def _parse_files_from_html(self, html: str, base_url: str) -> list[FileInfo]:
        """
        Extrahiert Datei-Informationen aus dem HTML-Inhalt einer Seite.

        Verwendet mehrere Strategien:
        1. Eingebettete JSON-Daten in <script>-Tags
        2. Download-Links in <a>-Tags
        3. <video>/<source>-Tags
        4. Daten-Attribute auf Elementen

        Args:
            html: HTML-Inhalt der Seite.
            base_url: Basis-URL für relative Links.

        Returns:
            Liste der gefundenen Dateien.
        """
        soup = BeautifulSoup(html, "lxml")
        files = []
        seen_urls = set()
        seen_slugs = set()

        # ── Strategie 0: Filester.gg native .file-item Elemente ──
        files.extend(self._extract_from_file_items(soup, base_url, seen_slugs))

        # ── Strategie 1: Eingebettete JSON-Daten ──
        files.extend(self._extract_from_json(soup, base_url, seen_urls))

        # ── Strategie 2: Download-Links (<a>-Tags) ──
        files.extend(self._extract_from_links(soup, base_url, seen_urls))

        # ── Strategie 3: Video/Source-Tags ──
        files.extend(self._extract_from_video_tags(soup, base_url, seen_urls))

        # ── Strategie 4: Daten-Attribute ──
        files.extend(self._extract_from_data_attrs(soup, base_url, seen_urls))

        logger.debug(f"Insgesamt {len(files)} Dateien auf der Seite gefunden.")
        return files

    def _extract_from_file_items(self, soup: BeautifulSoup, base_url: str,
                                 seen_slugs: set) -> list[FileInfo]:
        """
        Extrahiert Dateien aus den nativen Filester .file-item Divs.
        <div class="file-item" data-type="videos" data-name="..." data-size="..." onclick="window.location.href='/d/<slug>'">
        """
        files = []
        for item in soup.find_all(class_="file-item"):
            onclick = item.get("onclick", "")
            slug_match = re.search(r'/d/([a-zA-Z0-9_-]+)', onclick)
            slug = slug_match.group(1) if slug_match else None

            if not slug or slug in seen_slugs:
                continue
            seen_slugs.add(slug)

            name = item.get("data-name") or f"video_{slug}.mp4"
            data_type = item.get("data-type", "")
            size_str = item.get("data-size")
            file_size = int(size_str) if size_str and size_str.isdigit() else None

            is_video = (
                data_type == "videos"
                or any(name.lower().endswith(ext) for ext in VIDEO_EXTENSIONS)
            )

            files.append(FileInfo(
                filename=name,
                download_url="",  # Wird JIT über resolve_download_url aufgelöst
                file_size=file_size,
                file_type=data_type or "video",
                is_video=is_video,
                slug=slug,
            ))
        return files

    def _extract_from_json(self, soup: BeautifulSoup, base_url: str,
                           seen_urls: set) -> list[FileInfo]:
        """Extrahiert Dateien aus eingebetteten JSON-Strukturen."""
        files = []

        for script in soup.find_all("script"):
            if not script.string:
                continue

            text = script.string

            # Suche nach JSON-ähnlichen Strukturen mit Datei-Informationen
            # Muster 1: Initialisierungsdaten einer SPA (z.B. __NEXT_DATA__,
            #            window.__data, etc.)
            json_patterns = [
                r'(?:window\.__data__|__NEXT_DATA__|window\.__INITIAL_STATE__'
                r'|window\.initialData)\s*=\s*({.+?});',
                r'JSON\.parse\(["\'](.+?)["\']\)',
            ]

            for pattern in json_patterns:
                matches = re.findall(pattern, text, re.DOTALL)
                for match in matches:
                    try:
                        # Versuche JSON zu parsen
                        data = json.loads(match)
                        files.extend(
                            self._extract_files_from_dict(data, base_url, seen_urls)
                        )
                    except (json.JSONDecodeError, TypeError):
                        pass

            # Muster 2: Direkte URL-Muster in Script-Inhalten
            url_matches = re.findall(
                r'(?:src|url|href|download)["\']?\s*[:=]\s*["\']'
                r'(https?://[^"\']+?\.(?:mp4|mkv|avi|mov|webm|flv)[^"\']*)',
                text, re.IGNORECASE
            )
            for url in url_matches:
                url = url.replace('\\/', '/').replace('\\u0026', '&')
                if url not in seen_urls:
                    seen_urls.add(url)
                    filename = self._filename_from_url(url)
                    files.append(FileInfo(
                        filename=filename,
                        download_url=url,
                    ))

        return files

    def _extract_files_from_dict(self, data, base_url: str,
                                 seen_urls: set) -> list[FileInfo]:
        """
        Durchsucht ein verschachteltes Dictionary/Liste rekursiv
        nach Datei-Informationen.
        """
        files = []

        if isinstance(data, dict):
            # Prüfe, ob dieses Dict eine Datei repräsentiert
            url = (
                data.get("download_url") or data.get("url")
                or data.get("src") or data.get("file_url")
                or data.get("direct_link") or data.get("link")
            )
            name = (
                data.get("filename") or data.get("name")
                or data.get("file_name") or data.get("title")
            )
            size = (
                data.get("file_size") or data.get("size")
                or data.get("filesize")
            )

            if url and isinstance(url, str):
                if not url.startswith("http"):
                    url = urljoin(base_url, url)
                if url not in seen_urls:
                    seen_urls.add(url)
                    if not name:
                        name = self._filename_from_url(url)
                    file_size = int(size) if size and str(size).isdigit() else None
                    files.append(FileInfo(
                        filename=name,
                        download_url=url,
                        file_size=file_size,
                    ))

            # Rekursiv in Unter-Strukturen suchen
            for value in data.values():
                if isinstance(value, (dict, list)):
                    files.extend(
                        self._extract_files_from_dict(value, base_url, seen_urls)
                    )

        elif isinstance(data, list):
            for item in data:
                if isinstance(item, (dict, list)):
                    files.extend(
                        self._extract_files_from_dict(item, base_url, seen_urls)
                    )

        return files

    def _extract_from_links(self, soup: BeautifulSoup, base_url: str,
                            seen_urls: set) -> list[FileInfo]:
        """Extrahiert Dateien aus <a>-Tags mit Download-Links."""
        files = []

        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]

            # Relative URLs auflösen
            if not href.startswith("http"):
                href = urljoin(base_url, href)

            # Prüfe auf bekannte Download-Muster
            is_download = False

            # Muster 1: Dateiendung im Link
            parsed = urlparse(href)
            path_lower = unquote(parsed.path).lower()
            if any(path_lower.endswith(ext) for ext in VIDEO_EXTENSIONS):
                is_download = True

            # Muster 2: Download-spezifische URL-Pfade
            if any(kw in path_lower for kw in
                   ['/download', '/dl/', '/get/', '/stream/']):
                is_download = True

            # Muster 3: Download-Attribute auf dem <a>-Tag
            if a_tag.get("download") is not None:
                is_download = True

            # Muster 4: CSS-Klassen, die auf Download hindeuten
            classes = ' '.join(a_tag.get("class", []))
            if any(kw in classes.lower() for kw in
                   ['download', 'dl-btn', 'file-link', 'media-link']):
                is_download = True

            if is_download and href not in seen_urls:
                seen_urls.add(href)
                # Dateiname ermitteln
                filename = (
                    a_tag.get("download")
                    or a_tag.get("title")
                    or self._filename_from_url(href)
                )
                files.append(FileInfo(
                    filename=filename,
                    download_url=href,
                ))

        return files

    def _extract_from_video_tags(self, soup: BeautifulSoup, base_url: str,
                                 seen_urls: set) -> list[FileInfo]:
        """Extrahiert Dateien aus <video>- und <source>-Tags."""
        files = []

        # <video>-Tags mit src-Attribut
        for video in soup.find_all("video"):
            src = video.get("src")
            if src:
                if not src.startswith("http"):
                    src = urljoin(base_url, src)
                if src not in seen_urls:
                    seen_urls.add(src)
                    files.append(FileInfo(
                        filename=self._filename_from_url(src),
                        download_url=src,
                    ))

            # <source>-Tags innerhalb von <video>
            for source in video.find_all("source"):
                src = source.get("src")
                if src:
                    if not src.startswith("http"):
                        src = urljoin(base_url, src)
                    if src not in seen_urls:
                        seen_urls.add(src)
                        files.append(FileInfo(
                            filename=self._filename_from_url(src),
                            download_url=src,
                        ))

        return files

    def _extract_from_data_attrs(self, soup: BeautifulSoup, base_url: str,
                                 seen_urls: set) -> list[FileInfo]:
        """Extrahiert Dateien aus data-*-Attributen auf HTML-Elementen."""
        files = []

        # Suche nach Elementen mit relevanten data-Attributen
        data_attr_patterns = [
            'data-src', 'data-url', 'data-download', 'data-file',
            'data-video', 'data-href', 'data-media-url',
        ]

        for attr in data_attr_patterns:
            for elem in soup.find_all(attrs={attr: True}):
                url = elem[attr]
                if not url.startswith("http"):
                    url = urljoin(base_url, url)

                # Nur URLs mit Video-Endungen oder Download-Pfaden
                path_lower = unquote(urlparse(url).path).lower()
                is_video = (
                    any(path_lower.endswith(ext) for ext in VIDEO_EXTENSIONS)
                    or any(kw in path_lower for kw in
                           ['/download', '/dl/', '/get/'])
                )

                if is_video and url not in seen_urls:
                    seen_urls.add(url)
                    filename = (
                        elem.get("data-filename")
                        or elem.get("data-name")
                        or elem.get("title")
                        or self._filename_from_url(url)
                    )
                    files.append(FileInfo(
                        filename=filename,
                        download_url=url,
                    ))

        return files

    def _detect_pagination(self, soup: BeautifulSoup,
                           base_url: str) -> list[str]:
        """
        Erkennt Paginierung und gibt alle Seiten-URLs zurück.

        Args:
            soup: Geparstes HTML der ersten Seite.
            base_url: Basis-URL.

        Returns:
            Liste aller Seiten-URLs (ohne die erste Seite).
        """
        page_urls = []

        # Muster 0: Filester.gg Seitenzahlen-Anzeige (z.B. <span class="page-info">1 / 9</span>)
        page_info = soup.find(class_=re.compile(r'page-info', re.I))
        if page_info and page_info.text:
            m = re.search(r'\d+\s*/\s*(\d+)', page_info.text)
            if m:
                max_page = int(m.group(1))
                clean_base = re.sub(r'[?&]page=\d+', '', base_url).rstrip('?&')
                sep = '&' if '?' in clean_base else '?'
                for p in range(2, max_page + 1):
                    page_urls.append(f"{clean_base}{sep}page={p}")
                return page_urls

        # Muster 1: Paginierungs-Links
        pagination = soup.find_all(
            "a", class_=re.compile(r'page|pagination|pager', re.I)
        )
        # Ergänzung: Suche in nav/ul mit pagination-Klasse
        for nav in soup.find_all(["nav", "ul"],
                                 class_=re.compile(r'pagination', re.I)):
            pagination.extend(nav.find_all("a", href=True))

        seen = {base_url}
        for a in pagination:
            href = a.get("href")
            if href:
                if not href.startswith("http"):
                    href = urljoin(base_url, href)
                if href not in seen:
                    seen.add(href)
                    page_urls.append(href)

        # Muster 2: Seiten-Parameter in der URL (?page=N)
        if not page_urls:
            # Suche nach Hinweisen auf weitere Seiten im HTML
            page_numbers = re.findall(
                r'[?&]page=(\d+)', str(soup)
            )
            if page_numbers:
                max_page = max(int(p) for p in page_numbers)
                parsed = urlparse(base_url)
                for page_num in range(2, max_page + 1):
                    # Seiten-URL konstruieren
                    if '?' in base_url:
                        page_url = re.sub(
                            r'([?&])page=\d+',
                            f'\\1page={page_num}',
                            base_url
                        )
                        if f'page={page_num}' not in page_url:
                            page_url += f'&page={page_num}'
                    else:
                        page_url = f'{base_url}?page={page_num}'

                    if page_url not in seen:
                        seen.add(page_url)
                        page_urls.append(page_url)

        return page_urls

    def resolve_download_url(self, slug: str,
                             base_url: str = "https://filester.gg") -> Optional[str]:
        """
        Ruft über die Filester-API (/v2/api/public/download) die direkte CDN-Download-URL ab.

        Args:
            slug: Der File-Slug (z.B. 'abc123xy').
            base_url: Basis-URL.

        Returns:
            Direkte Download-URL oder None bei Fehler.
        """
        import urllib.parse
        api_url = f"{base_url}/v2/api/public/download"
        for attempt in range(MAX_RETRIES):
            try:
                response = self.session.post(
                    api_url,
                    json={"file_slug": slug},
                    headers={"Content-Type": "application/json"},
                    timeout=REQUEST_TIMEOUT,
                )
                if response.status_code == 200:
                    data = response.json()
                    if data.get("success") and "server" in data and "file" in data:
                        server = data["server"]
                        file_uuid = data["file"]
                        token = urllib.parse.quote(str(data.get("token", "")))
                        name = urllib.parse.quote(str(data.get("name", "")))
                        return f"{server}/v2/{file_uuid}?token={token}&download=true&n={name}"
                    elif "error" in data:
                        logger.error(
                            f"API-Fehler für Slug {slug}: "
                            f"{data.get('message') or data.get('error')}"
                        )
                        return None
                elif response.status_code == 429:
                    time.sleep(RETRY_BASE_DELAY * (attempt + 1))
                else:
                    logger.error(
                        f"HTTP-Fehler {response.status_code} beim Abrufen "
                        f"des Download-Tokens für {slug}"
                    )
            except requests.exceptions.RequestException as e:
                logger.warning(
                    f"Netzwerkfehler beim Abrufen des Tokens für {slug}: {e}"
                )
                time.sleep(RETRY_BASE_DELAY)

        return None

    def scrape_single_file(self, url: str) -> FolderInfo:
        """
        Analysiert eine einzelne Filester-Dateiseite (/d/<slug>).

        Args:
            url: URL der Dateiseite (z.B. https://filester.gg/d/abc123xy).

        Returns:
            FolderInfo mit der einzelnen Datei und ggf. übergeordnetem Ordner.
        """
        slug = self.extract_slug(url)
        if not slug:
            logger.error("Kein Slug in der URL gefunden.")
            return FolderInfo(folder_id="unknown", url=url)

        logger.info(f"Analysiere Video-Seite: {url}")
        html = self._fetch_page(url)

        filename = None
        parent_folder_url = None
        parent_folder_name = None

        if html:
            soup = BeautifulSoup(html, "lxml")
            # window.fileName = "..."
            name_m = re.search(r'window\.fileName\s*=\s*["\']([^"\']+)["\']', html)
            if name_m:
                filename = name_m.group(1)
            elif soup.title and soup.title.string:
                title = soup.title.string.strip()
                if ' | ' in title:
                    filename = title.split(' | ')[0].strip()
                elif ' - ' in title:
                    filename = title.split(' - ')[0].strip()
                else:
                    filename = title

            # Übergeordneten Ordner ermitteln
            parent_link = soup.find(
                "a", href=lambda h: h and ("/f/" in h or "/folder/" in h)
            )
            if parent_link:
                parent_folder_url = urljoin(url, parent_link["href"])
                parent_folder_name = (
                    parent_link.get_text().strip() or "Übergeordneter Ordner"
                )

        # Download-URL über API auflösen
        download_url = self.resolve_download_url(slug)
        if not filename and download_url:
            filename = self._filename_from_url(download_url)
        if not filename:
            filename = f"video_{slug}.mp4"

        file_info = FileInfo(
            filename=filename,
            download_url=download_url or "",
            slug=slug,
        )

        return FolderInfo(
            folder_id=slug,
            folder_name=filename,
            url=url,
            files=[file_info],
            is_single_file=True,
            parent_folder_url=parent_folder_url,
            parent_folder_name=parent_folder_name,
        )

    @staticmethod
    def _filename_from_url(url: str) -> str:
        """Extrahiert einen Dateinamen aus einer URL."""
        parsed = urlparse(url)
        path = unquote(parsed.path)
        filename = path.rsplit('/', 1)[-1] if '/' in path else path

        # Fallback, falls kein sinnvoller Name extrahiert werden kann
        if not filename or filename == '/':
            filename = f"video_{hash(url) % 100000:05d}.mp4"

        return filename

    def scrape_folder(self, url: str,
                      video_only: bool = True) -> FolderInfo:
        """
        Analysiert eine Filester-Ordnerseite und extrahiert alle Dateien.

        Args:
            url: URL des Filester-Ordners oder einer einzelnen Datei.
            video_only: Wenn True, werden nur Videos zurückgegeben.

        Returns:
            FolderInfo mit allen gefundenen Dateien.
        """
        # Falls es sich um eine Einzelseite (/d/<slug>) handelt:
        if self.extract_slug(url):
            return self.scrape_single_file(url)

        folder_id = self.extract_folder_id(url) or "unknown"
        folder = FolderInfo(folder_id=folder_id, url=url)

        logger.info(f"Analysiere Seite: {url}")

        # Erste Seite abrufen
        html = self._fetch_page(url)
        if not html:
            logger.error("Konnte die Seite nicht abrufen.")
            return folder

        soup = BeautifulSoup(html, "lxml")

        # Ordnername extrahieren
        title_tag = soup.find("title")
        if title_tag and title_tag.string:
            folder.folder_name = title_tag.string.strip()
            # Häufig: "Ordnername - Filester" → nur den Ordnernamen nehmen
            if ' - ' in folder.folder_name:
                folder.folder_name = folder.folder_name.split(' - ')[0].strip()
            elif ' | ' in folder.folder_name:
                folder.folder_name = folder.folder_name.split(' | ')[0].strip()

        # Dateien von der ersten Seite extrahieren
        files = self._parse_files_from_html(html, url)
        folder.files.extend(files)
        logger.info(f"Seite 1: {len(files)} Dateien gefunden")

        # Paginierung prüfen und weitere Seiten abrufen
        additional_pages = self._detect_pagination(soup, url)
        if additional_pages:
            folder.total_pages = len(additional_pages) + 1
            logger.info(
                f"Paginierung erkannt: {folder.total_pages} Seiten insgesamt"
            )

            for i, page_url in enumerate(additional_pages, start=2):
                folder.current_page = i
                logger.info(f"Lade Seite {i}/{folder.total_pages}...")

                page_html = self._fetch_page(page_url)
                if page_html:
                    page_files = self._parse_files_from_html(page_html, page_url)
                    folder.files.extend(page_files)
                    logger.info(f"Seite {i}: {len(page_files)} Dateien gefunden")
                else:
                    logger.warning(f"Konnte Seite {i} nicht laden.")

                # Kurze Pause zwischen den Seiten
                time.sleep(1)

        # Nur Videos filtern, falls gewünscht
        if video_only:
            all_count = len(folder.files)
            folder.files = [f for f in folder.files if f.is_video]
            logger.info(
                f"Filter: {len(folder.files)} Videos von "
                f"{all_count} Dateien insgesamt"
            )

        return folder

    def authenticate_with_token(self, token: str,
                                base_url: str = "https://filester.gg") -> bool:
        """
        Authentifiziert per API Access Token.

        Setzt den Token als Bearer-Token im Authorization-Header und
        als Cookie für die Session.

        Args:
            token: API Access Token von Filester.gg.
            base_url: Basis-URL der Filester-Instanz.

        Returns:
            True bei erfolgreicher Konfiguration.
        """
        token = token.strip()
        if not token:
            logger.error("Leerer Token übergeben.")
            return False

        self._token = token

        # Bearer Token im Authorization-Header setzen
        self.session.headers["Authorization"] = f"Bearer {token}"

        # Token auch als Cookie setzen
        domain = urlparse(base_url).hostname or "filester.gg"
        self.session.cookies.set("token", token, domain=domain)
        self.session.cookies.set("access_token", token, domain=domain)
        self.session.cookies.set("api_token", token, domain=domain)

        return True

    def login(self, username: str, password: str,
              base_url: str = "https://filester.gg") -> bool:
        """
        Meldet sich bei Filester.gg an (falls erforderlich).

        Args:
            username: Benutzername oder E-Mail.
            password: Passwort.
            base_url: Basis-URL der Filester-Instanz.

        Returns:
            True bei erfolgreicher Anmeldung.
        """
        login_url = f"{base_url}/login"
        logger.info("Versuche Anmeldung bei Filester...")

        try:
            # Zuerst die Login-Seite laden (CSRF-Token etc.)
            login_page = self.session.get(login_url, timeout=REQUEST_TIMEOUT)
            login_page.raise_for_status()

            soup = BeautifulSoup(login_page.text, "lxml")

            # CSRF-Token suchen
            csrf_token = None
            csrf_input = soup.find("input", {"name": re.compile(
                r'csrf|_token|authenticity_token', re.I
            )})
            if csrf_input:
                csrf_token = csrf_input.get("value")

            # Login-Daten zusammenstellen
            login_data = {
                "email": username,
                "password": password,
            }
            if csrf_token:
                # Den tatsächlichen Feldnamen verwenden
                token_name = csrf_input["name"]
                login_data[token_name] = csrf_token

            # Login durchführen
            response = self.session.post(
                login_url,
                data=login_data,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
            )

            # Prüfe ob Login erfolgreich war
            if response.status_code == 200 and '/login' not in response.url:
                logger.info("Anmeldung erfolgreich!")
                return True
            else:
                logger.error(
                    "Anmeldung fehlgeschlagen. Bitte Zugangsdaten prüfen."
                )
                return False

        except requests.exceptions.RequestException as e:
            logger.error(f"Fehler bei der Anmeldung: {e}")
            return False
