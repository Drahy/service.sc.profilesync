# Stream Cinema integration

These small patches apply to the reviewed local Stream Cinema 2.6.7.1+k19 build. They preserve the separate Stop, resume-completion, subtitle and quality-selection repairs already present in that build.

- Apply `storage.patch` and `lists.patch` within `resources/lib/common` with `git apply -p0`.
- Copy `resources/lib/sc_bridge.py` from this repository to SC's `resources/lib/common/profile_sync.py`.
- Apply `last-seen-browse.patch` from the SC addon root with `git apply`.
- Copy `resources/lib/sc_browse.py` to SC's `resources/lib/common/resume_browse.py`.
- Apply `menu-performance.patch` from the SC addon root to prepare plugin items without GUI locks.

The bridges perform local cache invalidation, safe SQLite merging and exact episode selection. They contain no cloud requests or playback commands. The profile service performs cloud operations independently and defers imports during playback.

For the latest episode-return behavior, apply `episode-return.patch` after the base patches, copy `sc_navigation.py` to SC's `resources/lib/services/navigation.py`, and copy `sc_episode_return.py` to `resources/lib/common/episode_return.py`. Check and apply the patch with `git apply --check --ignore-space-change` followed by `git apply --ignore-space-change` so compatible copies with CRLF line endings are supported. These integration files are maintained separately from the service package; restart Kodi after installing them.

This integration opens the last available shared Last seen season and selects its exact watched episode after startup, a fresh entry into Stream Cinema, or wake from sleep. It never starts playback. A separate durable episode checkpoint survives browsing the main menu and provides an offline fallback. Native wake callbacks queue local navigation; an interpreter suspension also rearms recovery. Normal Back navigation within Stream Cinema still reaches its menus, actions/widgets retain their original routes, and an existing player or a different addon's screen is not interrupted. A service restart within the same Kodi process does not by itself change the screen. Updating SC Profile Sync alone does not replace these Stream Cinema files.

For 0.1.5, recopy the updated `sc_bridge.py` as `profile_sync.py`: repeated readers now share one independent merge snapshot for the same cached data object and reuse a Home-window handle. Revision checks still run on every read, so remote updates remain immediately visible. Loads and committed saves replace the snapshot; nested unsaved edits still merge with current remote data.

Keep the locally patched Stream Cinema and helper on manual updates. Reapply these patches to a reviewed future build before enabling it. The current Up Next base is the official [v1.3.0 tag](https://github.com/im85288/service.upnext/tree/v1.3.0), commit `a7cadd1b0f706c41335323da30f2079e09d4f3a9`. Earlier Stop, Back, wake and credits fixes are already upstream and need no separate local copies. The optional playback-controls patch below is the only additional Up Next source change. SC Profile Sync does not install or update Up Next.

The shared Up Next preferences retain compact mode (`simpleMode=0`), allow Back to hide the popup while playback continues (`stopAfterClose=false`), and disable early credits autoplay (`autoPlayCreditsTime=0`). Manual selection of the next episode remains available. Per-addon update policies stay local to each device.

## Playback controls alongside Up Next

Apply `upnext-playback-controls.patch` to the compatible official Up Next 1.3.0 addon root after checking it with `git apply --check --ignore-space-change`. Enable **Use OK/Select for playback controls** under Up Next's Interface settings. The change is proposed upstream in [PR #350](https://github.com/im85288/service.upnext/pull/350).

Initial OK/Select opens Kodi's native playback controls while Up Next stays visible. An arrow first enters the existing Next/Close buttons; Up returns to playback-control focus. If Kodi hides the popup while the OSD is open, closing the controls restores it with neutral focus. Playback and its countdown pause together, and normal episode-end advancement remains active without selecting Next. Stop and Back retain their existing meaning; Still Watching still requires its normal confirmation. The option defaults to off and must be enabled explicitly on each device.

This setting is currently local to each device and is not in SC Profile Sync 0.1.5's released preference allowlist. Keep the reviewed patch while it is pending upstream; an Up Next reinstall/update can replace it. The provider-side five-second resume choice below remains independent of this patch.

## Bounded resume choice for continuous playback

Apply `continuous-resume.patch` from the Stream Cinema addon root, copy `sc_continuous_resume.py` to `resources/lib/common/continuous_resume.py`, and copy the contents of `skins/` to `resources/skins/`. Check the patch first with `git apply --check --ignore-space-change`; apply with `git apply --ignore-space-change`, then restart Kodi. The patch adds English, Czech and Slovak strings. It is a separate provider integration; the official Up Next package remains unchanged.

When Up Next requests an episode with a valid saved position, Stream Cinema offers **Play from beginning**, **Resume from the saved time**, and **Cancel**. Five seconds after the choice becomes visible, inactivity selects the beginning. Arrow navigation pauses that deadline; Back, Stop and Cancel abandon the transition. Episodes without an unfinished position start immediately. Ordinary manual playback retains Kodi's existing resume behavior, and the choice never clears a saved position or changes when Up Next offers the following episode.

The notification callback only marks the playback request. The plugin resolver owns the cancellable dialog, so the service callback remains free to handle shutdown. Kodi's `PlayMedia(...,noresume)` bypasses its earlier resume menu; an explicit resume choice is returned through the resolved item's video resume point. These companion files must be reapplied to a reviewed future Stream Cinema update; SC Profile Sync's released ZIP does not install them.

For the integration and navigation tests, set `SC_STORAGE_CANDIDATE` to the patched SC `resources/lib/common` directory, then run `pytest -q tests`.

## Active Android proxy sessions

The reviewed Android SC Helper 1.21 core expires a session 30 minutes after its last lookup. Sending the stream body does not refresh that timestamp, so cleanup can remove a session during playback and a later range/reopen can return a local 404.

Apply `sc-helper-stream-leases.patch` to the already repaired helper addon root and copy `sc_stream_leases.py` there as `session_leases.py`. Check first with `git apply --check --ignore-space-change`, then apply with `git apply --ignore-space-change`. Install it after the existing cached-HEAD and explicit-Stop wrappers in both service entry points. Restart Kodi when playback is stopped. This targets the reviewed Android core with `session.is_expired()` and `session.touch()`; the opaque Windows core exposes a different interface and is outside this patch's compatibility scope.

Each active GET holds its session until the request exits, including overlapping ranges. The final release refreshes normal idle expiry. There is no timer thread, polling or permanent cache, and unknown or idle-expired handles still return 404. Original responses, cached HEAD metadata, explicit Stop and upstream errors keep their existing handling. Existing expired links require a fresh Stream Cinema resolve; this does not revive them or change upstream authentication. The companion integration must be reapplied to a reviewed helper update and is not included in the released profile-sync ZIP.

The isolated Android-core regression uses a loopback fixture and a shortened expiry: the unmodified core loses an active session and returns 404; the wrapper retains it, preserves cached HEAD and explicit Stop, and allows normal idle cleanup after the request finishes.

## Optional Amber shutdown guards

The [Amber patch](amber-shutdown.patch) contains the companion changes tested with Amber 3.99.02 on Kodi 21.3. It avoids empty search resets and prevents unload hooks from scheduling deferred skin-setting saves after the profile service has begun stopping. Normal navigation retains its existing behavior; the guard is ignored while SC Profile Sync is disabled. Shutdown skips the final Home focus/background writes and retains their previously stored values. This does not affect Stream Cinema's separate season/episode navigation checkpoints.

Apply it to a backed-up compatible Amber checkout with `git apply --check` followed by `git apply`, or review and apply the corresponding XML edits in the installed skin. Restart Kodi after updating both the skin and SC Profile Sync 0.1.4 or newer. The service itself does not patch skin files, change update policies or replace Kodi binaries. A later skin reinstall/update may replace those XML edits; retain the reviewed patch or use a skin version that includes it.

## Optional disabled-view optimization

`amber-disabled-views.patch` skips construction of alternate video layouts that Amber's existing `Hide.*View` preferences disable. List remains loaded as the default/fallback. Default preferences still load every layout; the patch does not silently select a restricted set. Reenter the media window or restart Kodi after changing enabled views. These appearance preferences are shared by profile synchronization, so selecting only List also changes the enabled-view choice on the other devices.
