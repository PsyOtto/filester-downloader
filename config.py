"""
Konfigurationsdatei für den Filester.gg Video-Downloader.
Hier können globale Einstellungen angepasst werden.
"""

# ─── Netzwerk-Einstellungen ───────────────────────────────────────────────────

# User-Agent Header für HTTP-Anfragen (simuliert einen normalen Browser)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# Timeout für HTTP-Anfragen in Sekunden (Verbindung, Lesen)
REQUEST_TIMEOUT = (15, 60)

# Maximale Anzahl an Wiederholungsversuchen bei fehlgeschlagenen Downloads
MAX_RETRIES = 3

# Wartezeit zwischen Wiederholungsversuchen in Sekunden (verdoppelt sich)
RETRY_BASE_DELAY = 3

# Wartezeit zwischen einzelnen Datei-Downloads in Sekunden
# (verhindert Rate-Limiting durch den Server)
DOWNLOAD_DELAY = 1.5

# Chunk-Größe beim Herunterladen großer Dateien (in Bytes)
# 1 MB Chunks bieten ein gutes Gleichgewicht aus Geschwindigkeit und
# Speicherverbrauch
CHUNK_SIZE = 1024 * 1024  # 1 MB

# ─── Datei-Einstellungen ─────────────────────────────────────────────────────

# Standard-Ausgabeverzeichnis (relativ zum Skript-Verzeichnis)
DEFAULT_OUTPUT_DIR = "downloads"

# Video-Dateiendungen, die als Video erkannt werden
VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm",
    ".m4v", ".mpg", ".mpeg", ".3gp", ".ts", ".vob", ".ogv",
}

# Maximale Länge für Dateinamen (ohne Erweiterung)
MAX_FILENAME_LENGTH = 200

# ─── Filester-spezifische Einstellungen ──────────────────────────────────────

# Bekannte Filester-Domains
FILESTER_DOMAINS = {"filester.gg", "filester.me", "filester.sh"}

# API-Basis-Pfade (werden automatisch an die Domain angehängt)
API_BASE_PATH = "/api/v1"

# ─── Authentifizierung ───────────────────────────────────────────────────────

# API Access Token kann hier fest hinterlegt werden (alternativ zur
# Eingabe über die Konsole oder per --token Argument).
# ACHTUNG: Niemals Token in öffentliche Repositories committen!
# Besser: Umgebungsvariable FILESTER_TOKEN verwenden.
API_TOKEN = None

# Name der Umgebungsvariable für das Token
TOKEN_ENV_VAR = "FILESTER_TOKEN"

# Dateiname für lokale Token-Speicherung (im Skript-Verzeichnis)
TOKEN_FILE = ".filester_token"

# ─── Anzeige-Einstellungen ───────────────────────────────────────────────────

# Fortschrittsbalken-Einstellungen
PROGRESS_BAR_FORMAT = (
    "{l_bar}{bar}| {n_fmt}/{total_fmt} "
    "[{elapsed}<{remaining}, {rate_fmt}]"
)
