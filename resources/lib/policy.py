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
    "plugin.show.genre",
    "plugin.show.old.menu",
    "plugin.show.skip.button",
    "parental.control.enabled",
    "parental.control.start",
    "parental.control.end",
    "parental.control.rating",
    "parental.control.lang1",
    "parental.control.lang2",
    "parental.control.dubed",
    "system.autoexec",
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
    "disableNextUp",
}
PROFILE_SETTINGS = {"local_interval", "remote_interval", "hide_subtitles_for_czech_audio"}
KODI_SETTINGS = {
    "locale.language",
    "locale.audiolanguage",
    "locale.subtitlelanguage",
    "locale.charset",
    "locale.keyboardlayouts",
    "locale.activekeyboardlayout",
    "locale.country",
    "locale.shortdateformat",
    "locale.longdateformat",
    "locale.timeformat",
    "locale.use24hourclock",
    "locale.temperatureunit",
    "locale.speedunit",
    "subtitles.align",
    "subtitles.fontname",
    "subtitles.fontsize",
    "subtitles.style",
    "subtitles.languages",
    "subtitles.colorpick",
    "subtitles.opacity",
    "subtitles.bordersize",
    "subtitles.bordercolorpick",
    "subtitles.blur",
    "subtitles.backgroundtype",
    "subtitles.bgcolorpick",
    "subtitles.bgopacity",
    "subtitles.shadowcolor",
    "subtitles.shadowopacity",
    "subtitles.shadowsize",
    "subtitles.marginvertical",
    "subtitles.overridefonts",
    "subtitles.overridestyles",
    "subtitles.charset",
    "subtitles.parsecaptions",
    "subtitles.captionsalign",
    "subtitles.pauseonsearch",
    "subtitles.downloadfirst",
    "subtitles.tv",
    "subtitles.movie",
    "audiooutput.guisoundmode",
    "audiooutput.guisoundvolume",
    "lookandfeel.soundskin",
    "lookandfeel.skin",
    "lookandfeel.skintheme",
    "lookandfeel.skincolors",
    "lookandfeel.font",
    "lookandfeel.enablerssfeeds",
    "lookandfeel.startupaction",
    "lookandfeel.startupwindow",
    "filelists.showparentdiritems",
    "filelists.ignorethewhensorting",
    "filelists.showextensions",
    "filelists.showaddsourcebuttons",
    "filelists.showhidden",
    "videoplayer.seeksteps",
    "videoplayer.seekdelay",
    "videoplayer.preferdefaultflag",
    "videolibrary.showallitems",
    "videolibrary.showunwatchedplots",
    "videolibrary.groupmoviesets",
    "videolibrary.groupsingleitemsets",
    "videolibrary.showvideoversionsasfolder",
    "videolibrary.flattentvshows",
    "videolibrary.showemptytvshows",
    "videolibrary.tvshowsselectfirstunwatcheditem",
    "videolibrary.tvshowsincludeallseasonsandspecials",
    "addons.updatemode",
}


def shared_setting(addon, key):
    if addon == "plugin.video.stream-cinema":
        return key in SC_SETTINGS
    if addon == "service.upnext":
        return key in NEXT_SETTINGS
    if addon == "service.sc.profilesync":
        return key in PROFILE_SETTINGS
    if addon == "kodi":
        return key in KODI_SETTINGS
    if addon == "skin.amber":
        return (
            len(key) <= 100
            and not key.lower().startswith("scprofilesync.internal.")
            and key.replace(".", "").replace("_", "").replace("-", "").isalnum()
            and not any(
                word in key.lower()
                for word in ("password", "token", "path", "directory", "file", "playlist", "custom", "widget")
            )
        )
    return False
