"""Record an episode playback start without changing completion or resume."""
from datetime import datetime


def remember(movie, season, episode, now=None):
    if season is None or episode is None:
        return False
    try:
        if int(season) < 0 or int(episode) <= 0:
            return False
    except (TypeError, ValueError, OverflowError):
        return False
    instant = (now or datetime.now)()
    movie.set_last_played(instant.strftime('%Y-%m-%d %H:%M:%S'))
    return True
