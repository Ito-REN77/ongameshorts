"""A single persistent QWebEngineProfile shared by the band window and the
login window, so a Google/YouTube sign-in made in one carries over to the
other. Cookies and local storage are kept under a project-local folder so
the app stays portable (no registry / global browser-profile writes)."""
import os

from PyQt6.QtWebEngineCore import QWebEngineProfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE_DIR = os.path.join(PROJECT_ROOT, "profile_data")

# A mobile Chrome (Android) UA. YouTube's *desktop* Shorts player enforces
# a hardcoded minimum player size (~315x576) meant for a wide viewport, which
# doesn't fit our narrow band window and requires a pile of CSS overrides to
# work around. Presenting a phone UA instead makes YouTube serve its mobile
# web layout, which is actually built to fit a narrow vertical viewport --
# closer to how this is meant to be watched, and far more robust than
# fighting the desktop layout by hand. Google's mobile sign-in works fine
# under this UA too.
USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
)

_profile = None


def get_profile():
    global _profile
    if _profile is None:
        os.makedirs(PROFILE_DIR, exist_ok=True)
        _profile = QWebEngineProfile("OnGameShortsProfile")
        _profile.setPersistentStoragePath(PROFILE_DIR)
        _profile.setCachePath(os.path.join(PROFILE_DIR, "cache"))
        _profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
        )
        _profile.setHttpUserAgent(USER_AGENT)
    return _profile
