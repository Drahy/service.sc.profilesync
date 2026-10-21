"""Explicitly share preferences while keeping accounts and hardware local."""

SC_SETTINGS = {
    "stream.autoselect",
    "stream.lang1",
    "stream.lang2",
    "stream.max.quality",
    "stream.adv",
    "stream.adv.whitelist.codec",
    "stream.adv.whitelist.group",
    "stream.adv.blacklist.group",
    "stream.adv.whitelist.src",
    "stream.adv.blacklist.src",
    "stream.adv.exclude.3d",
    "stream.autoplay.episode",
    "stream.all",
    "stream.dubed",
    "stream.dubed.titles",
}
NEXT_SETTINGS = {
    "simpleMode",
    "autoPlayMode",
    "autoPlayCreditsTime",
    "stopAfterClose",
    "playedInARow",
    "enablePlaylist",
    "includeWatched",
    "customAutoPlayTime",
    "autoPlaySeasonTime",
    "autoPlayTimeXS",
    "autoPlayTimeS",
    "autoPlayTimeM",
    "autoPlayTimeL",
    "autoPlayTimeXL",
}
KODI_SETTINGS = {"locale.subtitlelanguage", "subtitles.languages", "subtitles.colorpick", "subtitles.opacity"}


def shared_setting(addon, key):
    if addon == "plugin.video.stream-cinema":
        return key in SC_SETTINGS
    if addon == "service.upnext":
        return key in NEXT_SETTINGS
    if addon == "kodi":
        return key in KODI_SETTINGS
    if addon == "skin.amber":
        return (
            len(key) <= 100
            and key.replace(".", "").replace("_", "").replace("-", "").isalnum()
            and not any(
                word in key.lower()
                for word in ("password", "token", "path", "directory", "file", "playlist", "custom", "widget")
            )
        )
    return False
