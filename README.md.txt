================================================================================
                      FILESTER.GG VIDEO DOWNLOADER
================================================================================

[NOTE: This project was created and structured with the assistance of AI.]

--------------------------------------------------------------------------------
1. FEATURES (WHAT CAN THIS SCRIPT DO?)
--------------------------------------------------------------------------------
- BULK DOWNLOAD: Automatically downloads all videos from any Filester album/folder
  (supports massive folders with 200+ videos across multiple pages).
- SINGLE OR FULL ALBUM: Paste a single video link (/d/...) or a folder link (/f/...).
  For single videos, it automatically detects the parent album and asks if you
  want to download just that video or the entire collection.
- ORIGINAL QUALITY: Downloads directly from CDN servers without re-encoding.
- LIVE PROGRESS: Real-time progress bar showing download speed, ETA, and size.
- RESUME SUPPORT: Automatically resumes interrupted downloads without re-downloading.
- JUST-IN-TIME TOKENS: Fetches fresh download tokens per file right before downloading
  so long multi-hour downloads never expire.
- SECURE AUTHENTICATION: Supports Filester.gg API Access Tokens.

--------------------------------------------------------------------------------
2. REQUIREMENTS
--------------------------------------------------------------------------------
- Python 3.10 or newer (https://www.python.org/)
- Your personal Filester API Key (found in your Filester profile under API settings)
- Required packages installed via:
  pip install -r requirements.txt

--------------------------------------------------------------------------------
3. QUICK START (HOW TO RUN)
--------------------------------------------------------------------------------
1. Open your terminal in this folder and install dependencies:
   pip install -r requirements.txt

2. Start the script:
   python main.py

3. Follow the 2 prompts on screen:
   - Paste your API Key (visible as you type/paste)
   - Paste your Filester link (e.g., https://filester.gg/f/<folder_id>)

4. Press Enter to start downloading! All files save into the "downloads/" folder.

* Optional: Pass link and token directly in one line:
  python main.py <URL> -t <YOUR_API_KEY>

--------------------------------------------------------------------------------
4. LEGAL & GIT NOTICE
--------------------------------------------------------------------------------
- Only download content you have permission to access.
- Never commit your private API keys or downloaded videos to a public repository.
  A .gitignore file is included to keep your repository clean.
================================================================================
