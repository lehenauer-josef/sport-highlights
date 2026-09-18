#!/usr/bin/env python3
import argparse
import html
import json
import math
import os
import random
import re
import ssl
import sys
import time
import unicodedata
from datetime import datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, urlencode
from urllib.request import Request, urlopen

AIRTABLE_BASE_ID = "appwv5KrUoIiMXoaM"
AIRTABLE_TABLE_ID = "tblEiBW2TbLaNNips"
AIRTABLE_VIEW = "viwGAHA60Q55XkM3s"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
MIN_DURATION_S = 80   # 1.25 minutes
MAX_DURATION_S = 1800  # 30 minutes
BAD_TERMS = [
    "pregame",
    "pre-game",
    "postgame",
    "post-game",
    "preview",
    "recap",
    "full game",
    "highlights recap",
    "game recap",
    "preview",
    "breakdown",
    "analysis",
    "midweek",
    "top plays",
    "top 10",
    "top 25",
    "top 5",
    "player of the game",
    "player of the week",
    "uniform",
    "pregame show",
    "postgame show",
    "halftime",
    "half time",
    "half-time",
    "quarterback highlights",
    "qb highlights",
    "reaction to",
    "touchdown highlights",
    "td highlights",
    "scoring highlights",
    "soccer",
    "men's soccer",
    "women's soccer",
    "lacrosse",
    "basketball",
    "sim highlights",
    "college football 25",
    "cfb 25",
    "cinematic",
]
# These terms are only bad when the channel is NOT a preferred/official one
SOFT_BAD_TERMS = [
    "condensed game",
    "in-game highlights",
]
GOOD_TERMS = ["highlights", "highlight"]


def parse_duration_seconds(iso_str):
    """Parse ISO 8601 duration string (PT#H#M#S) to total seconds."""
    if not iso_str:
        return None
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso_str)
    if not m:
        return None
    h = int(m.group(1) or 0)
    mins = int(m.group(2) or 0)
    secs = int(m.group(3) or 0)
    return h * 3600 + mins * 60 + secs


def get_airtable_pat():
    env_val = os.environ.get("AIRTABLE_PAT")
    if env_val:
        return env_val.strip()
    path = os.path.join(os.path.dirname(__file__), ".airtable_pat")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    raise SystemExit("Set AIRTABLE_PAT environment variable or create .airtable_pat with the token.")


def airtable_records(pat, view=AIRTABLE_VIEW):
    base_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_ID}"
    headers = {
        "Authorization": f"Bearer {pat}",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }
    params = {"view": view, "pageSize": 100}
    while True:
        query = urlencode(params)
        url = f"{base_url}?{query}"
        req = Request(url, headers=headers)
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            with urlopen(req, timeout=30, context=ctx) as resp:
                raw = resp.read().decode("utf-8")
        except HTTPError as exc:
            raise
        data = json.loads(raw)
        for rec in data.get("records", []):
            yield rec
        offset = data.get("offset")
        if not offset:
            break
        params["offset"] = offset


AIRTABLE_TEAMS_TABLE_ID = "tblvRWbkclZbB9rll"


def load_team_mascots(pat):
    """Populate TEAM_MASCOTS from the Teams table (normalized name -> normalized mascot)."""
    base_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TEAMS_TABLE_ID}"
    headers = {"Authorization": f"Bearer {pat}", "User-Agent": USER_AGENT}
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    params = {"pageSize": 100}
    while True:
        url = f"{base_url}?{urlencode(params)}"
        req = Request(url, headers=headers)
        with urlopen(req, timeout=30, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        for rec in data.get("records", []):
            f = rec.get("fields", {})
            name = f.get("Name")
            mascot = f.get("Mascot")
            if name and mascot:
                TEAM_MASCOTS[normalize_text(name)] = normalize_text(mascot)
        offset = data.get("offset")
        if not offset:
            break
        params["offset"] = offset


def patch_airtable_records(pat, patches):
    """Write fields back to Airtable (PATCH). patches: list of {id, fields} dicts. Max 10 per request."""
    base_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_ID}"
    headers = {
        "Authorization": f"Bearer {pat}",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    for i in range(0, len(patches), 10):
        batch = patches[i : i + 10]
        body = json.dumps({"records": batch}).encode("utf-8")
        req = Request(base_url, data=body, headers=headers, method="PATCH")
        for attempt in range(3):
            try:
                with urlopen(req, timeout=30, context=ctx) as resp:
                    resp.read()
                break
            except HTTPError as exc:
                if exc.code == 429 and attempt < 2:
                    time.sleep(2 ** attempt + 1)
                    continue
                raise
        time.sleep(0.25)  # stay under Airtable's 5 req/sec limit


def parse_game_teams(fields):
    home = None
    away = None
    if "Home Team Name" in fields and "Away Team Name" in fields:
        home = fields["Home Team Name"]
        away = fields["Away Team Name"]
    elif "Home Team" in fields and "Away Team" in fields:
        home = fields["Home Team"]
        away = fields["Away Team"]
    elif "Teams" in fields:
        teams = fields["Teams"]
        if isinstance(teams, list) and len(teams) >= 2:
            home, away = teams[0], teams[1]
        elif isinstance(teams, str):
            if " vs " in teams:
                left, right = teams.split(" vs ", 1)
                home, away = left.strip(), right.strip()
            elif " vs. " in teams:
                left, right = teams.split(" vs. ", 1)
                home, away = left.strip(), right.strip()
    if isinstance(home, list):
        home = home[0] if home else None
    if isinstance(away, list):
        away = away[0] if away else None
    return home, away


def parse_game_date(fields):
    candidate = fields.get("Date") or fields.get("Game Date") or fields.get("date")
    if not candidate:
        return None
    if isinstance(candidate, list):
        candidate = candidate[0]
    if isinstance(candidate, str):
        if candidate.endswith("Z"):
            candidate = candidate[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            pass
    return None


def normalize_text(text):
    # decode HTML entities (e.g. Hawai&#39;i → Hawai'i) before stripping punctuation
    text = html.unescape(text or "")
    # strip diacritics (e.g. San José → San Jose) so accented team names match titles
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    # collapse to alphanumeric + spaces, then collapse multiple spaces
    text = re.sub(r"[^A-Za-z0-9 ]+", " ", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip().lower()


# Maps canonical normalized team name → list of normalized aliases (and vice-versa).
# Both directions are resolved at runtime via get_team_variants().
TEAM_ALIASES: dict[str, list[str]] = {
    "mississippi state":  ["miss state", "mississippi st", "miss st"],
    "mississippi":        ["ole miss"],
    "louisiana monroe":   ["ulm", "ul monroe", "ula monroe"],
    "ul monroe":          ["ulm", "louisiana monroe", "ula monroe"],
    "appalachian state":  ["app state", "app st"],
    "connecticut":        ["uconn"],
    "central florida":    ["ucf"],
    "south florida":      ["usf"],
    "alabama birmingham": ["uab"],
    "texas san antonio":  ["utsa"],
    "texas el paso":      ["utep"],
    "florida international": ["fiu"],
    "florida atlantic":   ["fau"],
    "louisiana state":    ["lsu"],
    "brigham young":      ["byu"],
    "texas christian":    ["tcu"],
    "southern methodist": ["smu"],
    "southern california": ["usc"],
    "nevada las vegas":   ["unlv"],
    "western kentucky":   ["wku", "western ky"],
    "southern mississippi": ["southern miss"],
    "louisiana monroe":   ["ulm"],
    "hawaii":             ["hawai i"],   # normalize_text strips the apostrophe
    "miami oh":           ["miami ohio", "miami redhawks"],
    "north carolina state": ["nc state", "n c state"],
    "middle tennessee":   ["mtsu", "middle tenn"],
    "east carolina":      ["ecu"],
    "penn state":         ["penn st"],
    "ohio state":         ["ohio st"],
    "michigan state":     ["mich state", "mich st"],
    "louisiana":          ["louisiana lafayette", "ul lafayette", "ull"],
    "kentucky":           [],
    "pittsburgh":         ["pitt"],
    "massachusetts":      ["umass"],
    "texas am":           ["texas a m"],  # normalize strips &
    "florida state":      ["fsu"],
    "georgia tech":       ["georgia institute of technology"],
    "virginia tech":      ["va tech"],
    "western michigan":   ["western mich"],
    "eastern michigan":   ["eastern mich"],
    "central michigan":   ["central mich"],
    "northern illinois":  ["niu"],
    "ball state":         ["ball st"],
    "kent state":         ["kent st"],
    "bowling green":      ["bgsu", "bowling green state"],
    "buffalo":            ["ub"],
    "colorado state":     ["colorado st"],
    "san jose state":     ["san jose st", "sjsu"],
    "new mexico state":   ["nmsu", "new mexico st", "nm state"],
    "utah state":         ["utah st", "usu"],
    "boise state":        ["boise st"],
    "fresno state":       ["fresno st"],
    "arizona state":      ["asu"],
    "michigan":           [],  # avoid "western michigan" false match — no alias needed
    "south dakota state": ["south dakota st", "sdsu"],
    "north dakota state": ["north dakota st", "ndsu"],
    "south dakota":       ["south dak"],
    "north dakota":       ["north dak"],
    "stephen f austin":   ["sfa", "stephen f  austin"],  # normalize strips . and &
    "prairie view a m":   ["prairie view am", "pvamu"],  # normalize strips &
    "south carolina state": ["sc state", "s carolina state"],
    "jackson state":      ["jack state"],
    "tarleton state":     ["tarleton st"],
    "sacramento state":   ["sac state", "sacramento st"],
    "southeastern louisiana": ["se louisiana"],
    "eastern washington": ["eastern wash"],
    "western illinois":   ["western ill"],
    "northern iowa":      ["uni"],
    "james madison":      ["jmu"],
    "kennesaw state":     ["kennesaw st", "kennesaw"],
    "jacksonville state": ["jacksonville st", "jax state"],
    "incarnate word":     ["uiw"],
    "louisiana tech":     ["la tech"],
}


# normalized team name -> normalized mascot; populated at runtime from the Teams table
TEAM_MASCOTS: dict[str, str] = {}


def get_team_variants(name: str) -> set[str]:
    """Return all known name variants for a team (normalized)."""
    norm = normalize_text(name)
    variants: set[str] = {norm}
    for canonical, aliases in TEAM_ALIASES.items():
        if norm == canonical or norm in aliases:
            variants.add(canonical)
            variants.update(aliases)
    mascot = TEAM_MASCOTS.get(norm)
    if mascot:
        variants.add(mascot)
    return variants


def title_matches_teams(title, home, away):
    title_norm = normalize_text(title)
    if not home or not away:
        return False
    home_variants = get_team_variants(home)
    away_variants = get_team_variants(away)
    home_match = any(v in title_norm for v in home_variants)
    away_match = any(v in title_norm for v in away_variants)
    return home_match and away_match


PREFERRED_CHANNEL_RE = re.compile(
    r"(espn|wheel|wheels|sec network|big ten|pac[- ]12|pac12|acc network|acc digital|big 12|big12|fox college|cbs sports|longhorn network|big ten network|pac-12 network|accn|duong tung|fcs fans|fcsfans|ncaa championship|flo ?college|flo ?highlights|hbcu go|maction|get some mac|conference usa|cusa|big sky)",
    re.IGNORECASE,
)

# Channels that only produce cinematic/recap-style videos, not real game highlights
BAD_CHANNEL_RE = re.compile(r"(bluebloods)", re.IGNORECASE)


def title_is_bad(title, channel=None):
    lower = (title or "").lower()
    if channel and BAD_CHANNEL_RE.search(channel):
        return True
    if "full game" in lower and "highlight" in lower:
        lower = lower.replace("full game", "")
    if any(term in lower for term in BAD_TERMS):
        return True
    preferred = channel_is_preferred(channel)
    # Soft-bad terms are only disqualifying for non-preferred channels
    if not preferred and any(term in lower for term in SOFT_BAD_TERMS):
        return True
    if any(term in lower for term in GOOD_TERMS):
        return False
    # Preferred channels with no bad terms are accepted even without "highlights"
    if preferred:
        return False
    return True


def extract_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if "simpleText" in value:
            return value["simpleText"]
        if "runs" in value:
            return "".join(run.get("text", "") for run in value["runs"])
        if "text" in value:
            return value["text"]
    if isinstance(value, list):
        return "".join(extract_text(item) for item in value)
    return ""


def parse_view_count(text):
    text = (text or "").lower().replace("views", "").strip()
    if not text:
        return None
    text = text.replace(",", "").strip()
    match = re.match(r"^([0-9]+(?:\.[0-9]+)?)([kmbt]?)", text)
    if not match:
        return None
    value = float(match.group(1))
    suffix = match.group(2)
    multiplier = {
        "": 1,
        "k": 1_000,
        "m": 1_000_000,
        "b": 1_000_000_000,
        "t": 1_000_000_000_000,
    }.get(suffix, 1)
    return int(value * multiplier)


def channel_is_preferred(channel):
    return bool(channel and PREFERRED_CHANNEL_RE.search(channel))


def fetch_url(url, max_retries=3):
    for attempt in range(1, max_retries + 1):
        req = Request(url, headers={"User-Agent": USER_AGENT})
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            with urlopen(req, timeout=30, context=ctx) as resp:
                return resp.read().decode("utf-8", errors="ignore")
        except HTTPError as exc:
            if exc.code == 429 and attempt < max_retries:
                time.sleep(2 + attempt)
                continue
            raise
        except URLError:
            if attempt < max_retries:
                time.sleep(1 + attempt)
                continue
            raise
    raise ValueError(f"Unable to fetch {url}")


def duration_is_valid(duration_seconds):
    """Return True if duration is within the acceptable highlight range."""
    if duration_seconds is None:
        return None  # unknown — don't penalise
    return MIN_DURATION_S <= duration_seconds <= MAX_DURATION_S


# A true highlight reel usually clusters in this band; used for graduated scoring
IDEAL_DURATION_MIN_S = 240   # 4 minutes
IDEAL_DURATION_MAX_S = 900   # 15 minutes


def duration_score(duration_seconds):
    """Graduated duration score: peak reels score highest, condensed/short taper down."""
    if duration_seconds is None:
        return 0  # unknown — neutral
    if duration_seconds < MIN_DURATION_S or duration_seconds > MAX_DURATION_S:
        return -40
    if IDEAL_DURATION_MIN_S <= duration_seconds <= IDEAL_DURATION_MAX_S:
        return 25
    if duration_seconds < IDEAL_DURATION_MIN_S:
        return 12  # short reel — plausible but less certain
    return 15  # 15–30 min — likely condensed game


# Minimum score a better_match candidate must reach to be surfaced
BETTER_MATCH_MIN_SCORE = 130


def candidate_score(item, home, away):
    score = 0
    title = item.get("title") or ""
    channel = item.get("channel") or ""
    views = item.get("views") or 0
    duration = item.get("duration_seconds")
    if title_matches_teams(title, home, away):
        score += 100
    if not title_is_bad(title, channel):
        score += 30
    if channel_is_preferred(channel):
        score += 25
    if views:
        score += min(30, int(math.log10(views + 1) * 10))
    score += duration_score(duration)
    return score


def fetch_youtube_metadata(video_id):
    url = f"https://www.youtube.com/watch?v={video_id}"
    req = Request(url, headers={"User-Agent": USER_AGENT})
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    # retry on transient errors (429 or network issues)
    last_exc = None
    for attempt in range(4):
        try:
            with urlopen(req, timeout=30, context=ctx) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
            break
        except HTTPError as exc:
            last_exc = exc
            if exc.code == 429 and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            raise ValueError(f"YouTube returned {exc.code} for {video_id}")
        except URLError as exc:
            last_exc = exc
            if attempt < 3:
                time.sleep(2 ** attempt)
                continue
            raise ValueError(f"YouTube fetch failed for {video_id}: {exc}")
    else:
        raise ValueError(f"YouTube fetch failed for {video_id}: {last_exc}")

    title = None
    title_match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if title_match:
        title = title_match.group(1).replace(" - YouTube", "").strip()
    if not title:
        og_title = re.search(r'<meta property="og:title" content="([^"]+)"', html)
        if og_title:
            title = og_title.group(1).strip()
    if not title:
        raise ValueError(f"Could not extract title for {video_id}")

    channel = None
    channel_matches = re.findall(r'<meta itemprop="name" content="([^"]+)"', html)
    if channel_matches:
        channel = channel_matches[-1].strip()
    elif re.search(r'<meta name="author" content="([^"]+)"', html):
        channel = re.search(r'<meta name="author" content="([^"]+)"', html).group(1).strip()

    views = None
    view_match = re.search(r'"viewCount"\s*:\s*"(\d+)"', html)
    if not view_match:
        view_match = re.search(r'itemprop="interactionCount" content="(\d+)"', html)
    if view_match:
        views = int(view_match.group(1))
    else:
        view_text_match = re.search(r'"viewCountText".*?"simpleText"\s*:\s*"([^"]+)"', html, re.DOTALL)
        if view_text_match:
            views = parse_view_count(view_text_match.group(1))
        else:
            view_text_match = re.search(
                r'"viewCountText".*?"accessibilityData"\s*:\s*\{\s*"label"\s*:\s*"([^"]+)"',
                html,
                re.DOTALL,
            )
            if view_text_match:
                views = parse_view_count(view_text_match.group(1))

    # Extract duration
    duration_seconds = None
    dur_match = re.search(r'"lengthSeconds"\s*:\s*"(\d+)"', html)
    if dur_match:
        duration_seconds = int(dur_match.group(1))
    else:
        dur_meta = re.search(r'<meta itemprop="duration" content="([^"]+)"', html)
        if dur_meta:
            duration_seconds = parse_duration_seconds(dur_meta.group(1))

    return {"title": title, "channel": channel, "views": views, "duration_seconds": duration_seconds}


def search_youtube(query, max_results=10):
    url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
    try:
        html = fetch_url(url)
    except (HTTPError, URLError):
        return []
    data_match = re.search(r"ytInitialData\s*=\s*(\{.*?\});", html, re.DOTALL)
    if not data_match:
        return []
    data = json.loads(data_match.group(1))
    items = []

    def walk(obj):
        if isinstance(obj, dict):
            if obj.get("videoRenderer"):
                items.append(obj["videoRenderer"])
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(data)
    results = []
    for video in items:
        vid = video.get("videoId")
        title = extract_text(video.get("title"))
        channel = extract_text(video.get("ownerText")) or extract_text(video.get("longBylineText"))
        view_text = extract_text(video.get("viewCountText")) or extract_text(video.get("shortViewCountText"))
        views = parse_view_count(view_text)
        if vid and title:
            results.append({"video_id": vid, "title": title, "channel": channel, "views": views})
            if len(results) >= max_results:
                break
    return results


def find_better_video(home, away, game_date, current_video_id=None, current_score=0):
    if not home or not away or not game_date:
        return None
    buffer_start = (game_date - timedelta(days=10)).date().isoformat()
    buffer_end = (game_date + timedelta(days=2)).date().isoformat()
    query = f"{home} vs {away} College Football highlights before:{buffer_end} after:{buffer_start}"
    candidates = search_youtube(query, max_results=20)
    seen = set()
    shortlist = []
    for item in candidates:
        if item["video_id"] == current_video_id:
            continue
        if item["video_id"] in seen:
            continue
        seen.add(item["video_id"])
        title = item["title"]
        channel_hint = item.get("channel") or ""
        if title_is_bad(title, channel_hint):
            continue
        if not title_matches_teams(title, home, away):
            continue
        item["score"] = candidate_score(item, home, away)
        shortlist.append(item)
    # Fetch duration for top candidates (up to 5) to refine scores
    shortlist.sort(key=lambda x: x["score"], reverse=True)
    for item in shortlist[:5]:
        try:
            meta = fetch_youtube_metadata(item["video_id"])
            item["duration_seconds"] = meta.get("duration_seconds")
            item["score"] = candidate_score(item, home, away)
            time.sleep(random.uniform(1.0, 2.0))
        except Exception:
            pass
    shortlist.sort(key=lambda x: x["score"], reverse=True)
    best = shortlist[0] if shortlist else None
    if (best
            and best["score"] > current_score
            and best["score"] >= BETTER_MATCH_MIN_SCORE
            and duration_is_valid(best.get("duration_seconds")) is not False):
        return best
    return None


def get_division(fields):
    """Return 'FCS', 'FBS', or 'unknown' based on Conference Type Home Team field."""
    conf = fields.get("Conference Type Home Team") or fields.get("Conference Type Away Team")
    if isinstance(conf, list):
        conf = conf[0] if conf else None
    if isinstance(conf, str):
        conf = conf.strip("[]'\" ")
    if conf:
        return conf.upper()
    return "unknown"


def sample_records(all_records, fcs_per_week, fbs_per_week):
    """Group records by week, then pick up to fcs_per_week FCS and fbs_per_week FBS per week."""
    from collections import defaultdict
    weeks: dict = defaultdict(lambda: {"FCS": [], "FBS": [], "other": []})
    for rec in all_records:
        fields = rec.get("fields", {})
        week = str(fields.get("Week") or "unknown")
        div = get_division(fields)
        if div == "FCS":
            weeks[week]["FCS"].append(rec)
        elif div == "FBS":
            weeks[week]["FBS"].append(rec)
        else:
            weeks[week]["other"].append(rec)

    selected = []
    for week in sorted(weeks.keys()):
        bucket = weeks[week]
        fcs_sample = random.sample(bucket["FCS"], min(fcs_per_week, len(bucket["FCS"])))
        fbs_sample = random.sample(bucket["FBS"], min(fbs_per_week, len(bucket["FBS"])))
        selected.extend(fcs_sample)
        selected.extend(fbs_sample)
        fcs_n = len(fcs_sample)
        fbs_n = len(fbs_sample)
        if fcs_n or fbs_n:
            print(f"  Week {week}: {fcs_n} FCS, {fbs_n} FBS selected", flush=True)
    return selected


def process_record(rec):
    """Validate a single Airtable record and return the result dict."""
    fields = rec.get("fields", {})
    home, away = parse_game_teams(fields)
    game_date = parse_game_date(fields)
    division = get_division(fields)
    highlights = fields.get("Highlights")
    if isinstance(highlights, list):
        highlights = highlights[0] if highlights else None
    video_id = highlights or None
    valid = False
    title = None
    current_channel = None
    current_views = None
    reason = None
    current_duration = None
    if video_id and VIDEO_ID_RE.match(video_id):
        try:
            metadata = fetch_youtube_metadata(video_id)
            title = metadata.get("title")
            current_channel = metadata.get("channel")
            current_views = metadata.get("views")
            current_duration = metadata.get("duration_seconds")
            if title_is_bad(title, current_channel):
                reason = "bad title or not highlight"
            elif not title_matches_teams(title, home, away):
                reason = "teams do not match title"
            elif duration_is_valid(current_duration) is False:
                reason = f"duration out of range: {current_duration}s (must be {MIN_DURATION_S}–{MAX_DURATION_S}s)"
            else:
                valid = True
        except Exception as exc:
            reason = f"fetch error: {exc}"
    else:
        reason = "missing or invalid video id"

    current_score = candidate_score({
        "title": title,
        "channel": current_channel,
        "views": current_views,
        "duration_seconds": current_duration,
    }, home, away) if title else 0

    better = None
    if not valid:
        try:
            better = find_better_video(
                home,
                away,
                game_date,
                current_video_id=video_id,
                current_score=current_score,
            )
        except Exception as exc:
            better = {"error": f"search error: {exc}"}
            if not reason:
                reason = "search error"

    return {
        "record_id": rec.get("id"),
        "division": division,
        "week": fields.get("Week"),
        "team_home": home,
        "team_away": away,
        "game_date": game_date.isoformat() if game_date else None,
        "current_video_id": video_id,
        "current_title": title,
        "current_channel": current_channel,
        "current_views": current_views,
        "current_duration_seconds": current_duration,
        "current_valid": valid,
        "current_reason": reason,
        "better_match": better,
    }


def main():
    parser = argparse.ArgumentParser(description="Validate Airtable college football highlight videos.")
    parser.add_argument("--limit", type=int, default=None, help="Limit total records to process.")
    parser.add_argument("--output", default="highlight_validation_results.json", help="JSON output file name.")
    parser.add_argument("--sample-fcs", type=int, default=None, metavar="N",
                        help="Sample N FCS games per week instead of processing all records.")
    parser.add_argument("--sample-fbs", type=int, default=None, metavar="N",
                        help="Sample N FBS games per week instead of processing all records.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate records but do NOT write results back to Airtable.")
    parser.add_argument("--view", default=AIRTABLE_VIEW,
                        help="Airtable view ID to process (default: the built-in view).")
    args = parser.parse_args()

    pat = get_airtable_pat()
    load_team_mascots(pat)
    out_path = os.path.join(os.path.dirname(__file__), args.output)

    sampling = args.sample_fcs is not None or args.sample_fbs is not None
    fcs_per_week = args.sample_fcs if args.sample_fcs is not None else 0
    fbs_per_week = args.sample_fbs if args.sample_fbs is not None else 0

    if sampling:
        print(f"Fetching all records for sampling ({fcs_per_week} FCS + {fbs_per_week} FBS per week)...", flush=True)
        all_records = list(airtable_records(pat, view=args.view))
        print(f"Total records fetched: {len(all_records)}", flush=True)
        records_to_process = sample_records(all_records, fcs_per_week, fbs_per_week)
        print(f"Selected {len(records_to_process)} records for validation.\n", flush=True)
    else:
        records_to_process = list(airtable_records(pat, view=args.view))

    if args.limit:
        records_to_process = records_to_process[:args.limit]

    if not args.dry_run:
        print("Write-back to Airtable ENABLED (use --dry-run to disable).", flush=True)
    else:
        print("Dry-run mode — Airtable will NOT be updated.", flush=True)

    results = []
    patch_buffer = []

    def flush_patches():
        if not patch_buffer:
            return
        try:
            patch_airtable_records(pat, patch_buffer)
            print(f"[airtable] wrote {len(patch_buffer)} record(s)", flush=True)
        except Exception as exc:
            print(f"[airtable] WARN write error: {exc}", file=sys.stderr, flush=True)
        patch_buffer.clear()

    for rec in records_to_process:
        result = process_record(rec)
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)

        if not args.dry_run:
            has_better = bool(
                result.get("better_match")
                and "error" not in (result.get("better_match") or {})
            )
            patch_buffer.append({
                "id": result["record_id"],
                "fields": {
                    "Highlights Valid": result["current_valid"],
                    "Highlights found": result["better_match"]["video_id"] if has_better else "",
                    "Reason new highlights": result["current_reason"] if has_better else "",
                },
            })
            if len(patch_buffer) >= 10:
                flush_patches()

        time.sleep(random.uniform(1.2, 2.5))

    if not args.dry_run:
        flush_patches()

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nWrote {len(results)} results to {out_path}")


if __name__ == "__main__":
    main()
