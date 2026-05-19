PROVIDER_ALIASES: dict[str, str] = {
    "Amazon Prime Video with Ads": "Amazon Prime Video",
    "Prime Video": "Amazon Prime Video",
    "Apple TV Amazon Channel": "Apple TV+",
    "Apple TV Channel": "Apple TV+",
    "Apple TV Plus": "Apple TV+",
    "Paramount+ Amazon Channel": "Paramount+",
    "Paramount Plus": "Paramount+",
    "Paramount Plus Apple TV Channel": "Paramount+",
    "Crunchyroll Amazon Channel": "Crunchyroll",
    "Disney Plus": "Disney+",
}

PROVIDER_CLEANUP_SUFFIXES = (
    " with Ads",
    " Amazon Channel",
    " Apple TV Channel",
)

PROVIDER_CATEGORIES: dict[str, str] = {
    "Amazon Prime Video": "subscription",
    "Apple TV+": "subscription",
    "Crunchyroll": "anime",
    "Disney+": "subscription",
    "Netflix": "subscription",
    "Paramount+": "subscription",
    "RAI Play": "free",
}

PROVIDER_BADGE_COLORS: dict[str, str] = {
    "Amazon Prime Video": "prime",
    "Apple TV+": "apple",
    "Crunchyroll": "crunchyroll",
    "Disney+": "disney",
    "Netflix": "netflix",
    "Paramount+": "paramount",
    "RAI Play": "raiplay",
    "RaiPlay": "raiplay",
}
