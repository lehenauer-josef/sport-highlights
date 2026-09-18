# N8N Python (Pyodide) Code node — "Run Once for Each Item"
#
# Input : each item provides the pre-fetched YouTube search results plus the
#         home/away team names, e.g.
#           {
#             "home_team": "Holy Cross",
#             "away_team": "Lehigh",
#             "videos": [
#               {"videoId": "...", "url": "...", "title": "...",
#                "duration": "14:40", "views": 41, "channel": "..."},
#               ...
#             ]
#           }
#         Adjust the *_FIELD names below to match your incoming JSON keys.
# Output: the original item merged with the best highlight found:
#         highlight_video_id, highlight_url, highlight_title, highlight_channel,
#         highlight_views, highlight_duration_seconds, highlight_score,
#         highlight_valid, highlight_reason
#
# No imports are used — N8N's Pyodide sandbox disallows all stdlib modules.

MIN_DURATION_S = 120
MAX_DURATION_S = 1800
BETTER_MATCH_MIN_SCORE = 130

# A true highlight reel usually clusters in this band; used for graduated scoring
IDEAL_DURATION_MIN_S = 300
IDEAL_DURATION_MAX_S = 1200

BAD_TERMS = [
    "pregame", "pre-game", "postgame", "post-game", "preview", "recap",
    "full game", "highlights recap", "game recap", "breakdown", "analysis",
    "midweek", "top plays", "top 10", "top 25", "top 5", "player of the game",
    "player of the week", "uniform", "pregame show", "postgame show", "halftime",
    "half time", "half-time", "quarterback highlights", "qb highlights",
    "reaction to", "touchdown highlights", "td highlights", "scoring highlights",
    "soccer", "men's soccer", "women's soccer", "lacrosse", "basketball",
    "sim highlights", "college football 25", "cfb 25", "cinematic",
]
SOFT_BAD_TERMS = ["condensed game", "in-game highlights"]
GOOD_TERMS = ["highlights", "highlight"]

PREFERRED_CHANNEL_TERMS = [
    "espn", "wheel", "sec", "sec network", "big ten", "pac-12", "pac 12", "pac12",
    "acc network", "acc digital", "big 12", "big12", "cfb on fox", "fox college",
    "fox sports", "cbs sports",
    "longhorn network", "big ten network", "pac-12 network", "accn", "duong tung",
    "fcs fans", "fcsfans", "ncaa championship", "flocollege", "flo college",
    "flohighlights", "flo highlights", "hbcu go", "maction", "get some mac",
    "american conference", "conference usa", "cusa", "big sky", "sun belt conference", "sun belt",
    "mountainwestconf", "mountain west", "shaquille bryant", "thu tau", "matt h",
    "college championship", "amplified",
]
NATIONAL_CHANNEL_TERMS = [
    "espn", "cfb on fox", "fox college", "fox sports", "cbs sports", "cbs",
]
NATIONAL_CHANNEL_DURATION_BONUS = 25
LOCAL_ESPN_TRUSTED_CHANNELS = ["espn", "espn college football", "espn cfb"]
LOCAL_ESPN_CHANNEL_PENALTY = 20
BAD_CHANNEL_TERMS = ["bluebloods", "hbcu original"]

TEAM_ALIASES = {
    "mississippi state": ["miss state", "mississippi st", "miss st"],
    "mississippi": ["ole miss"],
    "louisiana monroe": ["ulm", "ul monroe", "ula monroe"],
    "ul monroe": ["ulm", "louisiana monroe", "ula monroe"],
    "appalachian state": ["app state", "app st"],
    "connecticut": ["uconn"],
    "central florida": ["ucf"],
    "south florida": ["usf"],
    "alabama birmingham": ["uab"],
    "texas san antonio": ["utsa"],
    "texas el paso": ["utep"],
    "florida international": ["fiu"],
    "florida atlantic": ["fau"],
    "louisiana state": ["lsu"],
    "brigham young": ["byu"],
    "texas christian": ["tcu"],
    "southern methodist": ["smu"],
    "southern california": ["usc"],
    "nevada las vegas": ["unlv"],
    "western kentucky": ["wku", "western ky"],
    "southern mississippi": ["southern miss"],
    "hawaii": ["hawai i"],
    "miami oh": ["miami ohio", "miami redhawks"],
    "north carolina state": ["nc state", "n c state"],
    "middle tennessee": ["mtsu", "middle tenn"],
    "east carolina": ["ecu"],
    "penn state": ["penn st"],
    "ohio state": ["ohio st"],
    "michigan state": ["mich state", "mich st"],
    "louisiana": ["louisiana lafayette", "ul lafayette", "ull"],
    "kentucky": [],
    "pittsburgh": ["pitt"],
    "massachusetts": ["umass"],
    "texas am": ["texas a m"],
    "florida state": ["fsu"],
    "georgia tech": ["georgia institute of technology"],
    "virginia tech": ["va tech"],
    "western michigan": ["western mich"],
    "eastern michigan": ["eastern mich"],
    "central michigan": ["central mich"],
    "northern illinois": ["niu"],
    "ball state": ["ball st"],
    "kent state": ["kent st"],
    "bowling green": ["bgsu", "bowling green state"],
    "buffalo": ["ub"],
    "colorado state": ["colorado st"],
    "san jose state": ["san jose st", "sjsu"],
    "new mexico state": ["nmsu", "new mexico st", "nm state"],
    "utah state": ["utah st", "usu"],
    "boise state": ["boise st"],
    "fresno state": ["fresno st"],
    "arizona state": ["asu"],
    "michigan": [],
    "south dakota state": ["south dakota st", "sdsu"],
    "north dakota state": ["north dakota st", "ndsu"],
    "south dakota": ["south dak"],
    "north dakota": ["north dak"],
    "stephen f austin": ["sfa", "stephen f  austin"],
    "prairie view a m": ["prairie view am", "pvamu"],
    "south carolina state": ["sc state", "s carolina state"],
    "jackson state": ["jack state"],
    "tarleton state": ["tarleton st"],
    "sacramento state": ["sac state", "sacramento st"],
    "southeastern louisiana": ["se louisiana"],
    "eastern washington": ["eastern wash"],
    "western illinois": ["western ill"],
    "northern iowa": ["uni"],
    "james madison": ["jmu"],
    "kennesaw state": ["kennesaw st", "kennesaw"],
    "jacksonville state": ["jacksonville st", "jax state"],
    "incarnate word": ["uiw"],
    "louisiana tech": ["la tech"],
}

# Common Latin diacritics -> ASCII (unicodedata is unavailable in the sandbox)
ACCENT_MAP = {
    "á": "a", "à": "a", "â": "a", "ä": "a", "ã": "a", "å": "a", "ā": "a",
    "é": "e", "è": "e", "ê": "e", "ë": "e", "ē": "e",
    "í": "i", "ì": "i", "î": "i", "ï": "i", "ī": "i",
    "ó": "o", "ò": "o", "ô": "o", "ö": "o", "õ": "o", "ø": "o", "ō": "o",
    "ú": "u", "ù": "u", "û": "u", "ü": "u", "ū": "u",
    "ñ": "n", "ç": "c", "ý": "y", "ÿ": "y",
}


def html_unescape(text):
    if not text:
        return text or ""
    named = {
        "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"',
        "&#39;": "'", "&#039;": "'", "&apos;": "'", "&nbsp;": " ",
    }
    for key, val in named.items():
        text = text.replace(key, val)
    result = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "&" and i + 2 < n and text[i + 1] == "#":
            j = i + 2
            hexmode = False
            if j < n and text[j] in ("x", "X"):
                hexmode = True
                j += 1
            k = j
            while k < n and text[k] != ";":
                k += 1
            num = text[j:k]
            try:
                code = int(num, 16) if hexmode else int(num)
                result.append(chr(code))
                i = k + 1
                continue
            except (ValueError, OverflowError):
                pass
        result.append(text[i])
        i += 1
    return "".join(result)


def log10(x):
    """Base-10 log without the math module; good enough for view scoring."""
    if x <= 0:
        return 0.0
    result = 0.0
    while x >= 10:
        x /= 10.0
        result += 1.0
    while x < 1:
        x *= 10.0
        result -= 1.0
    frac = 0.0
    weight = 0.5
    for _ in range(20):
        x = x * x
        if x >= 10:
            x /= 10.0
            frac += weight
        weight /= 2.0
    return result + frac


def normalize_text(text):
    text = html_unescape(text or "")
    out = []
    for ch in text:
        low = ch.lower()
        low = ACCENT_MAP.get(low, low)
        if ("a" <= low <= "z") or ("0" <= low <= "9"):
            out.append(low)
        else:
            out.append(" ")
    return " ".join("".join(out).split())


def get_team_variants(name, mascot=None):
    norm = normalize_text(name)
    variants = {norm}
    for canonical, aliases in TEAM_ALIASES.items():
        if norm == canonical or norm in aliases:
            variants.add(canonical)
            variants.update(aliases)
    if isinstance(mascot, list):
        mascot = mascot[0] if mascot else None
    if mascot:
        variants.add(normalize_text(mascot))
    return variants


def title_matches_teams(title, home, away, home_mascot=None, away_mascot=None):
    title_norm = normalize_text(title)
    if not home or not away:
        return False
    home_variants = get_team_variants(home, home_mascot)
    away_variants = get_team_variants(away, away_mascot)
    home_match = any(v in title_norm for v in home_variants)
    away_match = any(v in title_norm for v in away_variants)
    return home_match and away_match


def channel_is_preferred(channel):
    if not channel:
        return False
    if channel_is_local_espn(channel):
        return False
    low = channel.lower()
    return any(term in low for term in PREFERRED_CHANNEL_TERMS)


def channel_is_national(channel):
    if not channel:
        return False
    if channel_is_local_espn(channel):
        return False
    low = channel.lower()
    return any(term in low for term in NATIONAL_CHANNEL_TERMS)


def channel_is_local_espn(channel):
    if not channel:
        return False
    low = channel.lower().strip()
    if low in LOCAL_ESPN_TRUSTED_CHANNELS:
        return False
    return low.startswith("espn ")


def title_has_highlight_term(title):
    lower = (title or "").lower()
    return any(term in lower for term in GOOD_TERMS)


def channel_is_bad(channel):
    if not channel:
        return False
    low = channel.lower()
    return any(term in low for term in BAD_CHANNEL_TERMS)


def title_is_bad(title, channel=None):
    lower = (title or "").lower()
    if channel_is_bad(channel):
        return True
    if "full game" in lower and "highlight" in lower:
        lower = lower.replace("full game", "")
    if any(term in lower for term in BAD_TERMS):
        return True
    preferred = channel_is_preferred(channel)
    if not preferred and any(term in lower for term in SOFT_BAD_TERMS):
        return True
    if any(term in lower for term in GOOD_TERMS):
        return False
    if preferred:
        return False
    return True


def duration_is_valid(duration_seconds):
    if duration_seconds is None:
        return None
    return MIN_DURATION_S <= duration_seconds <= MAX_DURATION_S


def duration_score(duration_seconds):
    """Graduated duration score: peak reels score highest, condensed/short taper down."""
    if duration_seconds is None:
        return 0
    if duration_seconds < MIN_DURATION_S or duration_seconds > MAX_DURATION_S:
        return -40
    if IDEAL_DURATION_MIN_S <= duration_seconds <= IDEAL_DURATION_MAX_S:
        return 25
    if duration_seconds < IDEAL_DURATION_MIN_S:
        return 12
    return 15


def parse_duration(value):
    """Parse a 'H:MM:SS' or 'MM:SS' YouTube duration string into seconds."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    parts = str(value).strip().split(":")
    if not parts or not all(p.isdigit() for p in parts):
        return None
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + int(part)
    return seconds


def parse_view_count(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).lower().replace("views", "").replace(",", "").strip()
    if not text:
        return None
    num = ""
    idx = 0
    for ch in text:
        if ch.isdigit() or ch == ".":
            num += ch
            idx += 1
        else:
            break
    if not num:
        return None
    try:
        number = float(num)
    except ValueError:
        return None
    suffix = text[idx:idx + 1]
    multiplier = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000, "t": 1_000_000_000_000}.get(suffix, 1)
    return int(number * multiplier)


def candidate_score(item, home, away, home_mascot=None, away_mascot=None):
    score = 0
    title = item.get("title") or ""
    channel = item.get("channel") or ""
    views = item.get("views") or 0
    duration = item.get("duration_seconds")
    if title_matches_teams(title, home, away, home_mascot, away_mascot):
        score += 100
    if not title_is_bad(title, channel):
        score += 30
    if channel_is_preferred(channel):
        score += 25
    if views:
        score += min(30, int(log10(views + 1) * 10))
    score += duration_score(duration)
    if (channel_is_national(channel)
            and title_has_highlight_term(title)
            and duration is not None
            and duration > IDEAL_DURATION_MIN_S):
        score += NATIONAL_CHANNEL_DURATION_BONUS
    if channel_is_local_espn(channel):
        score -= LOCAL_ESPN_CHANNEL_PENALTY
    return score


def find_best_video(home, away, videos, home_mascot=None, away_mascot=None):
    seen = set()
    shortlist = []
    for raw in videos or []:
        vid = raw.get("videoId") or raw.get("video_id")
        title = raw.get("title") or ""
        channel = raw.get("channel") or ""
        if not vid or vid in seen:
            continue
        seen.add(vid)
        if title_is_bad(title, channel):
            continue
        if not title_matches_teams(title, home, away, home_mascot, away_mascot):
            continue
        item = {
            "video_id": vid,
            "url": raw.get("url") or f"https://www.youtube.com/watch?v={vid}",
            "title": title,
            "channel": channel,
            "views": parse_view_count(raw.get("views")),
            "duration_seconds": parse_duration(raw.get("duration")),
        }
        item["score"] = candidate_score(item, home, away, home_mascot, away_mascot)
        shortlist.append(item)
    shortlist.sort(key=lambda x: x["score"], reverse=True)
    best = shortlist[0] if shortlist else None
    if (best
            and best["score"] >= BETTER_MATCH_MIN_SCORE
            and duration_is_valid(best.get("duration_seconds")) is not False):
        return best
    return None

# N8N Pyodide entry point. In the n8n node the body below is pasted directly
# (n8n wraps it in a function so the top-level `return` is valid); wrapping it
# here keeps the exact logic while letting the importer `import` this module.
def n8n_entry(_item):
    home = _item["json"]["game"]["homeTeam"]
    away = _item["json"]["game"]["awayTeam"]
    videos = _item["json"]["videos"]
    home_mascot = _item["json"]["homeTeam"].get("mascot")
    away_mascot = _item["json"]["awayTeam"].get("mascot")

    best = find_best_video(home, away, videos, home_mascot, away_mascot)

    if best:
        result = {
            "highlight_video_id": best["video_id"],
            "highlight_url": best["url"],
            "highlight_title": best["title"],
            "highlight_channel": best.get("channel"),
            "highlight_views": best.get("views"),
            "highlight_duration_seconds": best.get("duration_seconds"),
            "highlight_score": best["score"],
            "highlight_valid": True,
            "highlight_reason": None,
        }
    else:
        result = {
            "highlight_video_id": None,
            "highlight_url": None,
            "highlight_title": None,
            "highlight_channel": None,
            "highlight_views": None,
            "highlight_duration_seconds": None,
            "highlight_score": None,
            "highlight_valid": False,
            "highlight_reason": "no matching highlight found",
        }

    return {**result}
