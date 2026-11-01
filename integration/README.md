# Stream Cinema integration

These small patches apply to the reviewed local Stream Cinema 2.6.7.1+k19 build. They preserve the separate Stop, resume-completion, subtitle and quality-selection repairs already present in that build.

- Apply `storage.patch` and `lists.patch` within `resources/lib/common` with `git apply -p0`.
- Copy `resources/lib/sc_bridge.py` from this repository to SC's `resources/lib/common/profile_sync.py`.
- Apply `last-seen-browse.patch` from the SC addon root with `git apply`.
- Copy `resources/lib/sc_browse.py` to SC's `resources/lib/common/resume_browse.py`.
- Apply `last-viewed-playback.patch` and copy `sc_last_viewed.py` to SC's
  `resources/lib/common/last_viewed.py`. Copy `sc_last_seen.py` to
  `resources/lib/common/last_seen.py` and apply `last_seen_timing_patch.py`
  against the addon root with a backup directory. This moves Last Seen and the
  episode last-played timestamp to ten seconds of actual playback; pauses,
  buffering, failed starts and seek jumps do not count. Completed-episode
  pointers, bookmarks and play counts remain independent.
- Apply `menu-performance.patch` from the SC addon root to prepare plugin items without GUI locks.

The bridges perform local cache invalidation, safe SQLite merging and exact episode selection. They contain no cloud requests or playback commands. The profile service performs cloud operations independently and defers imports during playback.

For the latest episode-return behavior, apply `episode-return.patch` after the base patches, copy `sc_navigation.py` to SC's `resources/lib/services/navigation.py`, and copy `sc_episode_return.py` to `resources/lib/common/episode_return.py`. Check and apply the patch with `git apply --check --ignore-space-change` followed by `git apply --ignore-space-change` so compatible copies with CRLF line endings are supported. These integration files are maintained separately from the service package; restart Kodi after installing them.

This integration opens the last available shared Last seen season and selects its most recently played episode after at least ten seconds of actual playback, including an unfinished episode, after startup, a fresh entry into Stream Cinema, wake from sleep or selecting the show in Last Seen. It falls back to SC's completed-episode pointer when no playback timestamp exists and never starts playback. A separate durable episode checkpoint survives browsing the main menu and provides an offline fallback. Native wake callbacks queue local navigation; an interpreter suspension also rearms recovery. Normal Back navigation within Stream Cinema still reaches its menus, actions/widgets retain their original routes, and an existing player or a different addon's screen is not interrupted. A service restart within the same Kodi process does not by itself change the screen. Updating SC Profile Sync alone does not replace these Stream Cinema files.

For 0.1.5, recopy the updated `sc_bridge.py` as `profile_sync.py`: repeated readers now share one independent merge snapshot for the same cached data object and reuse a Home-window handle. Revision checks still run on every read, so remote updates remain immediately visible. Loads and committed saves replace the snapshot; nested unsaved edits still merge with current remote data.

Keep the locally patched Stream Cinema and helper on manual updates. Reapply these patches to a reviewed future build before enabling it. The current Up Next base is the official [v1.3.0 tag](https://github.com/im85288/service.upnext/tree/v1.3.0), commit `a7cadd1b0f706c41335323da30f2079e09d4f3a9`. Earlier Stop, Back, wake and credits fixes are already in that release and need no separate local copies. The companion patch also includes the maintainer's merged [file-handoff timing fix](https://github.com/im85288/service.upnext/pull/353) from upstream `2a5403c`, alongside the playback-controls contribution in PR #350. SC Profile Sync does not install or update Up Next.

Manual update protection prevents unattended replacement, not a manual reinstall.
Before updating either addon, back up its installed code and review the new
version against every applicable integration; preflight the patches and keep a
rollback copy. Do not copy old addon files over a different version or assume
that a profile-sync update automatically reinstalls these integrations. Addon
settings, account credentials and viewing databases are not part of code backups.

The shared Up Next preferences retain compact mode (`simpleMode=0`), allow Back to hide the popup while playback continues (`stopAfterClose=false`), and disable early credits autoplay (`autoPlayCreditsTime=0`). Manual selection of the next episode remains available. Per-addon update policies stay local to each device.

## Playback controls alongside Up Next

Apply `upnext-playback-controls.patch` to the compatible official Up Next 1.3.0 addon root after checking it with `git apply --check --ignore-space-change`. Enable **Use OK/Select for playback controls** under Up Next's Interface settings. The change is proposed upstream in [PR #350](https://github.com/im85288/service.upnext/pull/350).

Initial OK/Select opens Kodi's native playback controls while Up Next stays visible. An arrow first enters the existing Next/Close buttons; Up returns to playback-control focus. If Kodi hides the popup while the OSD is open, closing the controls restores it; when the option is enabled, focus returns to the neutral target. A dedicated OSD action also restores the popup when the option is disabled. Playback and its countdown pause together, and normal episode-end advancement remains active without selecting Next. Stop and Back retain their existing meaning; Still Watching still requires its normal confirmation. The option defaults to off and must be enabled explicitly on each device.

This setting is currently local to each device and is not in SC Profile Sync 0.1.5's released preference allowlist. Keep the reviewed patch while it is pending upstream; an Up Next reinstall/update can replace it. The provider-side five-second resume choice below remains independent of this patch.

## Bounded resume choice for continuous playback

Apply `continuous-resume.patch` from the Stream Cinema addon root, copy `sc_continuous_resume.py` to `resources/lib/common/continuous_resume.py`, and copy the contents of `skins/` to `resources/skins/`. Check the patch first with `git apply --check --ignore-space-change`; apply with `git apply --ignore-space-change`, then restart Kodi. The patch adds English, Czech and Slovak strings. It is a separate provider integration; the official Up Next package remains unchanged.

When Up Next requests an episode with a valid saved position, Stream Cinema offers **Play from beginning**, **Resume from the saved time**, and **Cancel**. Five seconds after the choice becomes visible, inactivity selects the beginning. Arrow navigation pauses that deadline; Back, Stop and Cancel abandon the transition. Episodes without an unfinished position start immediately. Ordinary manual playback retains Kodi's existing resume behavior, and the choice never clears a saved position or changes when Up Next offers the following episode.

The notification callback only marks the playback request. The plugin resolver owns the cancellable dialog, so the service callback remains free to handle shutdown. Kodi's `PlayMedia(...,noresume)` bypasses its earlier resume menu; an explicit resume choice is returned through the resolved item's video resume point. These companion files must be reapplied to a reviewed future Stream Cinema update; SC Profile Sync's released ZIP does not install them.

For the integration and navigation tests, set `SC_STORAGE_CANDIDATE` to the patched SC `resources/lib/common` directory, then run `pytest -q tests`.

## Proxy sessions and wake recovery

The reviewed Android and Windows SC Helper 1.21 cores expire a session 30 minutes after its last lookup. Sending the stream body does not refresh that timestamp, so cleanup can remove a session during playback and a later range/reopen can return a local 404.

Apply `sc-helper-stream-leases.patch` to the already repaired helper addon root, and copy `sc_head_cache.py`, `sc_stream_leases.py`, `sc_wake_streams.py` and `sc_cancel_reads.py` there as `head_cache.py`, `session_leases.py`, `wake_streams.py` and `cancel_reads.py`. Check the patch first with `git apply --check --ignore-space-change`, then apply with `git apply --ignore-space-change`. Both service entry points install cached HEADs, active-stream leases, wake recovery and Stop cancellation in that order. Restart the helper when playback is stopped. The integration supports the reviewed Android and Windows 1.21 cores, including their different internal method names and shutdown hooks; review future helper versions before reapplying it.

Each active request holds its session until it exits, including overlapping ranges. The final release refreshes normal idle expiry. For a known handle that expired while idle, the helper resolves the original item again with Stream Cinema's current account session, replaces the stale session behind the same local address and preserves the requested byte range. The lookup retains at most 128 item identifiers in memory and stores no account token; it has no timer thread, polling or permanent cache. Stop can interrupt both GET and HEAD while refresh is pending. Unknown handles and failed resolves still return 404 without changing account credentials.

Recovery requires a working Stream Cinema account session, network access and an item registered by this helper process before sleep. If a resolve fails while Stream Cinema or Profile Sync is refreshing the account token, it briefly waits for the changed token and retries once. It cannot recover handles created before this integration was activated or after the helper itself has restarted and changed port; an expired login requires normal Stream Cinema reauthentication. It does not handle unrelated upstream stream errors. The companion integration must be reapplied to a reviewed helper update and is not included in the released profile-sync ZIP.

Isolated tests on both reviewed platform cores cover active-session retention and local 404 recovery for GET ranges and cached HEAD, including cancellation during a pending refresh. They use a loopback fixture and fake account tokens, without changing viewing history or contacting the provider.

## Optional Amber shutdown guards

The [Amber patch](amber-shutdown.patch) contains the companion changes tested with Amber 3.99.02 on Kodi 21.3. It avoids empty search resets and prevents unload hooks from scheduling deferred skin-setting saves after the profile service has begun stopping. Normal navigation retains its existing behavior; the guard is ignored while SC Profile Sync is disabled. Shutdown skips the final Home focus/background writes and retains their previously stored values. This does not affect Stream Cinema's separate season/episode navigation checkpoints.

Apply it to a backed-up compatible Amber checkout with `git apply --check` followed by `git apply`, or review and apply the corresponding XML edits in the installed skin. Restart Kodi after updating both the skin and SC Profile Sync 0.1.4 or newer. The service itself does not patch skin files, change update policies or replace Kodi binaries. A later skin reinstall/update may replace those XML edits; retain the reviewed patch or use a skin version that includes it.

## Optional disabled-view optimization

`amber-disabled-views.patch` skips construction of alternate video layouts that Amber's existing `Hide.*View` preferences disable. List remains loaded as the default/fallback. Default preferences still load every layout; the patch does not silently select a restricted set. Reenter the media window or restart Kodi after changing enabled views. These appearance preferences are shared by profile synchronization, so selecting only List also changes the enabled-view choice on the other devices.

For transient connectivity errors during automatic episode return, install
`sc_navigation.py` and apply `sc_navigation_retry_patch.transform` to
`resources/lib/streamcinema.py`. The retry is limited to the saved folder and
stops on playback or navigation; ordinary browsing errors remain visible.

## Webshare Stop and matched-episode return

The optional companion uses `localproxy.py` to register HTTPS Webshare links
with SC Helper. Apply `patch_webshare_helper.transform` to Helper's `service.py`
and copy `sc_webshare_proxy.py` there as `webshare_proxy.py`; restart the helper
when playback is idle. Its opaque sessions and upstream links live in memory,
only accept loopback registrations to the approved Webshare CDN, answer HEAD
from verified file metadata, forward ranges and cancel live reads on Stop.
Active streams retain their session; no link or credential enters profile sync.

Copy `sc_episode_return.py` to SC `resources/lib/common/episode_return.py` and
`sc_navigation.py` to SC `resources/lib/services/navigation.py`. Apply the
companion `patch_webshare_stop.transform` to SC `services/player.py` and
`patch_safe_stop.transform` to the existing per-device `userdata/sc-safe-stop.py`.
A matched companion episode requests a return before Stop cancels playback;
the navigation service waits for playback and the window transition, verifies
the user stayed in that results folder and selects the exact episode. Generic
Webshare files without an SC identity do not invent a catalog or history entry.
Back up and hash-check device preimages and reload only when playback is idle.
Kodi/addon updates can replace these local hooks, which must be reapplied only
against compatible sources. Account settings remain device-local.

When a season search carries an SC show ID, the companion associates the
entered season and episode numbers with that show even if the catalog has no
row for the episode. This does not create a Stream Cinema catalog entry: the
return first opens the season; if its row is missing, it returns to the original
Webshare results and selects the played file when it is still available. A
generic filename search without that identity has no SC history or matched
episode return. Playback of an absent catalog episode remains subject to
provider availability and has not been established by the existing live tests.
