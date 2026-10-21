import ast
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
from types import ModuleType, SimpleNamespace
from urllib.parse import urlencode

import pytest


from resources.lib import sc_browse

SOURCE = os.environ.get("SC_STORAGE_CANDIDATE")
pytestmark = pytest.mark.skipif(not SOURCE, reason="Set SC_STORAGE_CANDIDATE to the patched SC common directory")
RUN = Path(SOURCE or ".").parent
ADDON_ID = "plugin.video.stream-cinema"


def uri(route, **args):
    values = dict(args, url=route)
    return "plugin://" + ADDON_ID + "/?" + urlencode({k: str(v).encode().hex() for k, v in values.items()})


class NativeList:
    """Native Kodi controls expose selection messages, not Python vecItems."""

    def __init__(self):
        self.selected = None

    def isVisible(self):
        return True

    def selectItem(self, index):
        self.selected = index

    def size(self):
        raise AssertionError("Native ControlList.size() has no Kodi media items")


@pytest.fixture
def environment(tmp_path, monkeypatch):
    context = SimpleNamespace(
        window=10025,
        folder=uri("/Catalogue/123/36"),
        key=uri("/Play/123/36/8"),
        current="9",
        items=["..", uri("/Play/123/36/7"), uri("/Play/123/36/8")],
        modal=False,
        updating=False,
        commands=[],
        now=0,
        pid=10,
        focused=55,
    )
    context.properties = {}
    control = NativeList()
    window = SimpleNamespace(
        getFocusId=lambda: 55,
        getControl=lambda number: control,
        setFocusId=lambda number: setattr(context, "focused", number),
        getProperty=lambda key: context.properties.get(key, ""),
        clearProperty=lambda key: context.properties.pop(key, None),
    )

    def label(name):
        if name == "Container.FolderPath":
            return context.folder
        if name == "ListItem.FileNameAndPath":
            return context.key
        if name.endswith(".CurrentItem"):
            return context.current
        if name.endswith((".NumAllItems", ".NumItems")):
            return str(len(context.items))
        match = re.search(r"ListItemAbsolute\((\d+)\)", name)
        if match:
            index = int(match.group(1))
            return context.items[index] if index < len(context.items) else ""
        return ""

    xbmc = ModuleType("xbmc")
    xbmc.getInfoLabel = label
    xbmc.getCondVisibility = lambda name: {
        "System.HasModalDialog": context.modal,
        "Container.IsUpdating": context.updating,
    }.get(name, False)
    xbmc.executebuiltin = context.commands.append
    gui = ModuleType("xbmcgui")
    gui.getCurrentWindowId = lambda: context.window
    gui.Window = lambda identifier: window
    vfs = ModuleType("xbmcvfs")
    vfs.translatePath = lambda path: path
    constants = ModuleType("resources.lib.constants")
    constants.ADDON_ID = ADDON_ID
    constants.ADDON = SimpleNamespace(getAddonInfo=lambda name: str(tmp_path))
    common = ModuleType("resources.lib.common")
    common.resume_browse = sc_browse
    monkeypatch.setitem(sys.modules, "resources.lib.common", common)
    logger = ModuleType("resources.lib.common.logger")
    logger.debug = lambda *args: None
    for name, value in [
        ("xbmc", xbmc),
        ("xbmcgui", gui),
        ("xbmcvfs", vfs),
        ("resources.lib.constants", constants),
        ("resources.lib.common.logger", logger),
    ]:
        monkeypatch.setitem(sys.modules, name, value)
    spec = importlib.util.spec_from_file_location("navigation_under_test", RUN / "services/navigation.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.os = SimpleNamespace(
        getpid=lambda: context.pid,
        makedirs=module.os.makedirs,
        path=module.os.path,
        fsync=module.os.fsync,
        replace=module.os.replace,
    )
    module.time = SimpleNamespace(monotonic=lambda: context.now, time=lambda: context.now)
    monitor = SimpleNamespace(is_DPMS=False, is_screensaver=False, abortRequested=lambda: True)
    player = SimpleNamespace(is_my_plugin=False, isPlayback=lambda: False, item={}, my_id=None)

    def make():
        return module.NavigationRecovery(monitor, player)

    return SimpleNamespace(
        module=module,
        context=context,
        control=control,
        monitor=monitor,
        player=player,
        make=make,
        state_file=tmp_path / "navigation-state.json",
    )


def interrupted_session(env):
    worker = env.make()
    worker.capture()
    env.context.pid += 1
    env.context.window = 10000
    env.context.folder = ""
    worker = env.make()
    assert worker.pending
    env.context.now += 4
    return worker


def test_captures_exact_folder_and_item_durably(environment):
    env = environment
    worker = env.make()
    worker.capture()
    saved = json.loads(env.state_file.read_text())
    assert saved["checkpoint"]["item"] == "/Play/123/36/8"
    assert saved["checkpoint"]["folder"] == env.module.canonical_uri(env.context.folder)
    assert saved["checkpoint"]["active"]
    assert not Path(str(env.state_file) + ".tmp").exists()


def test_unchanged_selection_does_not_rewrite_file(environment, monkeypatch):
    worker = environment.make()
    worker.capture()
    monkeypatch.setattr(worker, "_save", lambda: pytest.fail("Unchanged selection rewritten"))
    worker.capture()


def test_capture_clears_recovery_when_leaving_addon(environment):
    env = environment
    worker = env.make()
    worker.capture()
    env.context.window = 10000
    env.context.folder = ""
    worker.capture()
    assert worker.state["checkpoint"]["active"] is False


def test_sleep_keeps_last_context(environment):
    env = environment
    worker = env.make()
    worker.capture()
    env.monitor.is_DPMS = True
    env.context.window = 10000
    worker.capture()
    assert worker.state["checkpoint"]["active"] is True


def test_same_process_service_restart_does_not_steal_ui(environment):
    worker = environment.make()
    worker.capture()
    assert environment.make().pending is False


def test_normal_shutdown_prevents_automatic_restore(environment):
    env = environment
    worker = env.make()
    worker.capture()
    worker.run()
    env.context.pid += 1
    assert env.make().pending is False


def test_failed_recovery_does_not_create_crash_loop(environment):
    env = environment
    worker = interrupted_session(env)
    worker.restore()
    assert worker.state["session"]["restoring"] is True
    env.context.pid += 1
    assert env.make().pending is False


def test_crash_restores_identity_after_rows_move_without_playing(environment):
    env = environment
    worker = interrupted_session(env)
    worker.restore()
    assert len(env.context.commands) == 1
    assert env.context.commands[0].startswith("ActivateWindow(videos,")
    assert "navigation_restore=31" in env.context.commands[0]
    assert not any("PlayMedia" in command for command in env.context.commands)
    env.context.window = 10025
    env.context.folder = env.module.restoring_uri(worker.state["checkpoint"]["folder"])
    env.context.items.insert(1, uri("/Play/123/36/0"))
    worker.restore()
    assert env.control.selected == 3
    assert worker.pending is False


def test_restore_waits_for_native_items(environment):
    env = environment
    worker = interrupted_session(env)
    worker.restore()
    env.context.window = 10025
    env.context.folder = env.module.restoring_uri(worker.state["checkpoint"]["folder"])
    env.context.items = []
    worker.restore()
    assert worker.pending
    env.context.items = [uri("/Play/123/36/8")]
    worker.restore()
    assert env.control.selected == 0
    assert not worker.pending


def test_restore_waits_through_initial_root_window(environment):
    env = environment
    worker = interrupted_session(env)
    worker.restore()
    env.context.window = 10025
    env.context.folder = uri("/")
    worker.restore()
    assert worker.pending
    assert len(env.context.commands) == 1


def test_missing_item_does_not_select_a_different_episode(environment):
    env = environment
    worker = interrupted_session(env)
    worker.restore()
    env.context.window = 10025
    env.context.folder = worker.state["checkpoint"]["folder"]
    env.context.items = [uri("/Play/123/36/9")]
    worker.restore()
    assert env.control.selected is None
    assert not worker.pending


@pytest.mark.parametrize(
    "window,folder,playing", [(10004, "", False), (10025, uri("/Other/456"), False), (12005, "", True)]
)
def test_restore_respects_user_activity(environment, window, folder, playing):
    env = environment
    worker = interrupted_session(env)
    env.context.window, env.context.folder = window, folder
    env.player.isPlayback = lambda: playing
    worker.restore()
    assert not worker.pending
    assert env.context.commands == []


def test_restore_waits_for_dialogs_and_times_out(environment):
    env = environment
    worker = interrupted_session(env)
    env.context.modal = True
    worker.restore()
    assert worker.pending and not env.context.commands
    env.context.now += 100
    worker.restore()
    assert not worker.pending


def test_restore_expires_after_directory_timeout(environment):
    env = environment
    worker = interrupted_session(env)
    worker.restore()
    env.context.now += 100
    worker.restore()
    assert not worker.pending


def test_own_playback_tracks_episode_changes(environment):
    env = environment
    worker = env.make()
    worker.capture()
    env.context.window, env.context.folder = 12005, ""
    env.player.is_my_plugin = True
    env.player.isPlayback = lambda: True
    env.player.my_id = 123
    env.player.item = {"info": {"season": 36, "episode": 9}}
    worker.capture()
    assert worker.state["checkpoint"]["item"] == "/Play/123/36/9"
    assert worker.state["checkpoint"]["active"]
    env.player.item["info"].update(season=37, episode=1)
    worker.capture()
    assert worker.state["checkpoint"]["item"] == "/Play/123/37/1"
    assert env.module.route_args(worker.state["checkpoint"]["folder"])["url"] == "/Catalogue/123/37"


def test_corrupt_state_does_not_prevent_addon_startup(environment):
    env = environment
    env.state_file.write_text("{broken")
    assert env.make().pending is False


@pytest.mark.parametrize(
    "folder",
    [
        "https://example.com/video",
        "plugin://other.addon/?url=2f",
        uri("/Play/123/36/8"),
        uri("/", action="cmd"),
        uri("/", action="play_url"),
    ],
)
def test_actionable_or_foreign_folder_is_not_restored(environment, folder):
    assert environment.module.safe_folder(folder) == ""


def test_restore_marker_does_not_contaminate_normal_folder(environment):
    module = environment.module
    original = uri("/Catalogue/123/36", title="Some show")
    restored = module.restoring_uri(original)
    assert module.route_args(restored)["navigation_restore"] == "1"
    assert module.canonical_uri(restored) == module.canonical_uri(original)


@pytest.mark.parametrize("restore,enabled,expected", [(True, True, False), (False, True, True), (False, False, False)])
def test_existing_autoplay_is_only_suppressed_for_recovery(restore, enabled, expected):
    tree = ast.parse((RUN / "streamcinema.py").read_text(encoding="utf-8"))
    conditions = [
        node.test
        for node in ast.walk(tree)
        if isinstance(node, ast.If) and "navigation_restore" in ast.unparse(node.test)
    ]
    assert len(conditions) == 1
    scope = {
        "get_setting_as_bool": lambda name: enabled,
        "self": SimpleNamespace(args={"navigation_restore": "1"} if restore else {}),
    }
    assert eval(compile(ast.Expression(conditions[0]), "<autoplay-condition>", "eval"), scope) is expected


def test_last_seen_focus_uses_exact_episode_and_preserves_parent_offset(environment):
    env = environment
    worker = env.make()
    env.context.folder = uri("/FGet/123/36", resume_episode="8")
    request = dict(route="/FGet/123/36", item="/Play/123/36/8", expires=15)
    env.context.properties[sc_browse.FOCUS_PROPERTY] = json.dumps(request)
    assert worker.focus_requested()
    assert env.control.selected == 2
    assert not env.context.commands
    assert sc_browse.FOCUS_PROPERTY not in env.context.properties


def test_focus_never_navigates_to_another_folder_or_starts_playback(environment):
    env = environment
    worker = env.make()
    request = dict(route="/FGet/123/36", item="/Play/123/36/8", expires=15)
    env.context.properties[sc_browse.FOCUS_PROPERTY] = json.dumps(request)
    assert not worker.focus_requested()
    assert env.control.selected is None
    env.context.now = 16
    assert not worker.focus_requested()
    assert not env.context.commands
    assert sc_browse.FOCUS_PROPERTY not in env.context.properties


def test_focus_request_cannot_interrupt_video(environment):
    env = environment
    worker = env.make()
    env.player.isPlayback = lambda: True
    env.context.properties[sc_browse.FOCUS_PROPERTY] = json.dumps(
        dict(route="/FGet/123/36", item="/Play/123/36/8", expires=15)
    )
    assert not worker.focus_requested()
    assert env.control.selected is None
    assert not env.context.commands


def test_catalog_playback_alias_uses_the_stable_history_id(environment):
    uri_alias = uri("/Play/m_example/36/8", id="123")
    assert environment.module.item_key(uri_alias) == "/Play/123/36/8"


def test_last_seen_focus_recognizes_catalog_alias_and_parent_offset(environment):
    env = environment
    worker = env.make()
    env.context.folder = uri("/FGet/123/36", resume_episode="8")
    env.context.items[2] = uri("/Play/m_example/36/8", id="123")
    env.context.properties[sc_browse.FOCUS_PROPERTY] = json.dumps(
        dict(route="/FGet/123/36", item="/Play/123/36/8", expires=15)
    )
    assert worker.focus_requested()
    assert env.control.selected == 2
    assert not env.context.commands
