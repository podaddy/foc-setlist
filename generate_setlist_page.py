#!/usr/bin/env python3
"""
Generate a GitHub Pages site with YouTube links for the current setlist.

Reads the latest setlist (from OCR txt or image), matches songs to the
Google Sheet, and generates an HTML page with embedded YouTube videos.

Usage:
    python generate_setlist_page.py [--output docs/index.html] [--dry-run]

Created: 2026-03-11
"""

import sys
import os
import re
import argparse
import logging
from pathlib import Path
from datetime import datetime
from difflib import SequenceMatcher
from typing import Optional

# Local scripts import path
sys.path.insert(0, r'C:\scripts')

from google.gsheets import get_spreadsheet, get_all_values

# Config
DEFAULT_SHEET_ID = '1ecFqD_DrBGVfFMnXdfChMgwkFVE-XS8GWvHU5pAU-OA'
DEFAULT_WORKSHEET = 'song_notes'
SETLIST_FOLDER = Path(r'G:\My Drive\FOC\documents\set lists')
OUTPUT_DIR = Path(__file__).parent / 'docs'

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def get_latest_setlist_txt() -> Optional[Path]:
    """Find the most recent .txt file (OCR output) in setlist folder."""
    txt_files = list(SETLIST_FOLDER.glob('*.txt'))
    if not txt_files:
        return None
    return max(txt_files, key=lambda f: f.stat().st_mtime)


def parse_setlist_txt(txt_path: Path) -> list[str]:
    """Parse song names from OCR txt file."""
    content = txt_path.read_text(encoding='utf-8')
    lines = content.strip().split('\n')
    
    # Skip header lines (date, band name fragments, etc.)
    songs = []
    skip_patterns = [
        r'^\d{4}$',  # Year
        r'^(PRACTICE|GIG|SET\s*LIST)',
        r'^(JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER)',
        r'^(ED|YST|CULT|OYSTER|FRIED)',  # Band name fragments from bad OCR
        r'^\s*$',  # Empty lines
        r'^[A-Z]{1,3}$',  # Single letters / fragments
    ]
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # Skip header-like lines
        skip = False
        for pattern in skip_patterns:
            if re.match(pattern, line, re.IGNORECASE):
                skip = True
                break
        
        if not skip and len(line) > 2:
            songs.append(line)
    
    return songs


def normalize_title(title: str) -> str:
    """Normalize song title for matching."""
    title = title.lower().strip()
    # Remove common prefixes/suffixes
    title = re.sub(r"^(the|a|an)\s+", "", title)
    # Remove punctuation
    title = re.sub(r"[^\w\s]", "", title)
    # Collapse whitespace
    title = re.sub(r"\s+", " ", title)
    return title


def fuzzy_match(needle: str, haystack: str, threshold: float = 0.7) -> bool:
    """Check if two strings are a fuzzy match."""
    return SequenceMatcher(None, normalize_title(needle), normalize_title(haystack)).ratio() >= threshold


def load_song_database(sheet_id: str = DEFAULT_SHEET_ID, worksheet: str = DEFAULT_WORKSHEET) -> dict:
    """Load song data from Google Sheet. Returns {normalized_title: {title, artist, youtube}}."""
    sheet = get_spreadsheet(sheet_id)
    ws = sheet.worksheet(worksheet)
    rows = get_all_values(ws)
    
    if not rows:
        return {}
    
    headers = rows[0]
    title_idx = next((i for i, h in enumerate(headers) if h.lower() == 'title'), 0)
    artist_idx = next((i for i, h in enumerate(headers) if h.lower() == 'artist'), 1)
    youtube_idx = next((i for i, h in enumerate(headers) if h.lower() == 'youtube'), -1)
    
    songs = {}
    for row in rows[1:]:
        if len(row) <= title_idx:
            continue
        title = row[title_idx].strip()
        if not title:
            continue
        
        artist = row[artist_idx].strip() if artist_idx < len(row) else ''
        youtube = row[youtube_idx].strip() if youtube_idx >= 0 and youtube_idx < len(row) else ''
        
        # Skip NULL/empty youtube
        if youtube.upper() == 'NULL':
            youtube = ''
        
        normalized = normalize_title(title)
        songs[normalized] = {
            'title': title,
            'artist': artist,
            'youtube': youtube,
        }
    
    return songs


def match_setlist_to_songs(setlist: list[str], song_db: dict) -> list[dict]:
    """Match setlist entries to song database. Returns list of song dicts."""
    matched = []
    
    for entry in setlist:
        entry_norm = normalize_title(entry)
        
        # Try exact match first
        if entry_norm in song_db:
            song = song_db[entry_norm].copy()
            song['setlist_name'] = entry
            matched.append(song)
            continue
        
        # Try fuzzy match
        best_match = None
        best_score = 0
        for norm_title, song_data in song_db.items():
            score = SequenceMatcher(None, entry_norm, norm_title).ratio()
            if score > best_score and score >= 0.6:
                best_score = score
                best_match = song_data
        
        if best_match:
            song = best_match.copy()
            song['setlist_name'] = entry
            song['match_score'] = best_score
            matched.append(song)
        else:
            # No match - include as-is without youtube
            matched.append({
                'title': entry,
                'setlist_name': entry,
                'artist': '',
                'youtube': '',
                'no_match': True,
            })
    
    return matched


def extract_video_id(youtube_url: str) -> Optional[str]:
    """Extract video ID from YouTube URL."""
    if not youtube_url:
        return None
    
    patterns = [
        r'(?:v=|/v/|youtu\.be/)([a-zA-Z0-9_-]{11})',
        r'^([a-zA-Z0-9_-]{11})$',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, youtube_url)
        if match:
            return match.group(1)
    
    return None


def generate_html(songs: list[dict], setlist_date: str = None) -> str:
    """Generate HTML page with YouTube embeds."""
    
    if not setlist_date:
        setlist_date = datetime.now().strftime('%B %d, %Y')
    
    song_items = []
    for i, song in enumerate(songs, 1):
        title = song.get('title', song.get('setlist_name', 'Unknown'))
        artist = song.get('artist', '')
        youtube = song.get('youtube', '')
        video_id = extract_video_id(youtube)
        
        artist_html = f'<span class="artist">{artist}</span>' if artist else ''
        
        if video_id:
            embed_html = f'''
            <div class="video-container">
                <iframe src="https://www.youtube.com/embed/{video_id}" 
                        frameborder="0" 
                        allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" 
                        allowfullscreen></iframe>
            </div>'''
            link_html = f'<a href="{youtube}" target="_blank" class="yt-link">Open in YouTube ↗</a>'
        else:
            embed_html = '<div class="no-video">No video available</div>'
            link_html = ''
        
        song_items.append(f'''
        <div class="song" id="song-{i}">
            <div class="song-header">
                <span class="song-number">{i}</span>
                <h2>{title}</h2>
                {artist_html}
            </div>
            {embed_html}
            {link_html}
        </div>''')
    
    songs_html = '\n'.join(song_items)
    
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>FOC Setlist - {setlist_date}</title>
    <style>
        :root {{
            --bg: #1a1a2e;
            --card-bg: #16213e;
            --accent: #e94560;
            --text: #eaeaea;
            --text-muted: #a0a0a0;
        }}
        
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.6;
            padding: 20px;
        }}
        
        header {{
            text-align: center;
            padding: 30px 20px;
            margin-bottom: 30px;
        }}
        
        header h1 {{
            font-size: 2rem;
            margin-bottom: 10px;
            color: var(--accent);
        }}
        
        header .date {{
            color: var(--text-muted);
            font-size: 1.1rem;
        }}
        
        .songs {{
            max-width: 800px;
            margin: 0 auto;
        }}
        
        .song {{
            background: var(--card-bg);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 25px;
        }}
        
        .song-header {{
            display: flex;
            align-items: center;
            gap: 15px;
            margin-bottom: 15px;
            flex-wrap: wrap;
        }}
        
        .song-number {{
            background: var(--accent);
            color: white;
            width: 32px;
            height: 32px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: bold;
            font-size: 0.9rem;
            flex-shrink: 0;
        }}
        
        .song-header h2 {{
            font-size: 1.3rem;
            flex-grow: 1;
        }}
        
        .artist {{
            color: var(--text-muted);
            font-size: 0.95rem;
        }}
        
        .video-container {{
            position: relative;
            padding-bottom: 56.25%;
            height: 0;
            overflow: hidden;
            border-radius: 8px;
            margin-bottom: 10px;
        }}
        
        .video-container iframe {{
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
        }}
        
        .no-video {{
            background: #0f0f1a;
            border-radius: 8px;
            padding: 40px 20px;
            text-align: center;
            color: var(--text-muted);
        }}
        
        .yt-link {{
            display: inline-block;
            color: var(--accent);
            text-decoration: none;
            font-size: 0.9rem;
            margin-top: 8px;
        }}
        
        .yt-link:hover {{
            text-decoration: underline;
        }}
        
        footer {{
            text-align: center;
            padding: 40px 20px;
            color: var(--text-muted);
            font-size: 0.85rem;
        }}
        
        footer a {{
            color: var(--accent);
        }}
        
        @media (max-width: 600px) {{
            header h1 {{
                font-size: 1.5rem;
            }}
            
            .song-header h2 {{
                font-size: 1.1rem;
            }}
        }}
    </style>
</head>
<body>
    <header>
        <h1>🦪 Fried Oyster Cult</h1>
        <div class="date">Setlist • {setlist_date}</div>
    </header>
    
    <main class="songs">
        {songs_html}
    </main>
    
    <footer>
        <p>Generated by OysterBot 🦪</p>
        <p>Updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
    </footer>
</body>
</html>'''
    
    return html


def parse_args():
    parser = argparse.ArgumentParser(description='Generate setlist page with YouTube links')
    parser.add_argument('--output', '-o', type=Path, default=OUTPUT_DIR / 'index.html',
                        help='Output HTML file path')
    parser.add_argument('--setlist', '-s', type=Path, default=None,
                        help='Path to setlist txt file (default: latest in setlist folder)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Print output without writing file')
    return parser.parse_args()


def main():
    args = parse_args()
    
    # Find setlist
    if args.setlist:
        setlist_path = args.setlist
    else:
        setlist_path = get_latest_setlist_txt()
    
    if not setlist_path or not setlist_path.exists():
        logger.error(f"No setlist found. Run OCR on a setlist image first.")
        return 1
    
    logger.info(f"Using setlist: {setlist_path.name}")
    
    # Parse setlist
    setlist = parse_setlist_txt(setlist_path)
    logger.info(f"Found {len(setlist)} songs in setlist")
    
    # Load song database
    logger.info("Loading song database from Google Sheet...")
    song_db = load_song_database()
    logger.info(f"Loaded {len(song_db)} songs from database")
    
    # Match songs
    matched_songs = match_setlist_to_songs(setlist, song_db)
    
    # Report matches
    with_video = sum(1 for s in matched_songs if s.get('youtube'))
    no_match = sum(1 for s in matched_songs if s.get('no_match'))
    logger.info(f"Matched: {len(matched_songs) - no_match}/{len(setlist)} songs")
    logger.info(f"With YouTube: {with_video}/{len(matched_songs)}")
    
    # Extract date from filename if possible
    date_match = re.search(r'(\d{4})(\w+)(\d{1,2})', setlist_path.stem, re.IGNORECASE)
    if date_match:
        setlist_date = f"{date_match.group(2).title()} {date_match.group(3)}, {date_match.group(1)}"
    else:
        setlist_date = None
    
    # Generate HTML
    html = generate_html(matched_songs, setlist_date)
    
    if args.dry_run:
        print(html)
        return 0
    
    # Write output
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html, encoding='utf-8')
    logger.info(f"Written to: {args.output}")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
