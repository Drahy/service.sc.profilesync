# SC Profile Sync

Share Stream Cinema viewing history and selected preferences through the existing account's **private Kra storage**. Each Kodi device keeps its own database and an offline checkpoint. Devices connect directly to Kra; a notebook or home server does not need to remain on.

The service synchronizes Last seen, watched markers, episode/movie resume positions, the last played episode, per-title language choices, common Stream Cinema and Up Next preferences, interface/regional preferences, subtitle appearance, interface sound mode/volume and portable Amber appearance settings. Explicit deletions prevent a stale device from restoring a cleared resume position.

Passwords, tokens, cached stream URLs, navigation checkpoints, HDR/decoder settings, audio output, speed tests and network limits stay local. The service uses the account configured in Stream Cinema. It never starts, stops or seeks a video. Remote profile imports wait until playback stops, and network failures leave changes queued locally. The optional local subtitle policy runs independently of transfers.

## Install and update

Requires Kodi 21 or newer, Stream Cinema `plugin.video.stream-cinema` 2.6.7.1 or newer, Up Next 1.2.1 or newer, and the existing Stream Cinema Kra login. Amber is optional. Stream Cinema Community is a different addon and is not supported by this integration.

1. Download [the repository ZIP](https://github.com/Drahy/service.sc.profilesync/releases/latest/download/repository.drahy.scprofilesync.zip) to your device.
2. In Kodi, temporarily enable **Settings → System → Add-ons → Unknown sources**, then choose **Add-ons → Install from zip file** and select that ZIP. Restore your previous Unknown sources setting afterward.
3. Choose **Install from repository → Drahy's SC Profile Sync Repository → Services → SC Profile Sync**.
4. Sign in to the same Kra account in Stream Cinema on each device. Allow the first synchronization to finish. A new device restores existing cloud preferences before publishing its defaults.

For live Stream Cinema cache refresh and exact Last seen season/episode navigation, use the matching repaired SC build with the [SC integration](integration/README.md). The repository installs and updates **SC Profile Sync only**; it does not replace Stream Cinema, install unrelated skin changes or patch another addon's source automatically. Stream Cinema and Up Next must be available from their own repositories or installed beforehand.

After installation from the repository, Kodi can discover future versions. Enable automatic updates for **SC Profile Sync** if desired. Keep separately patched SC/helper builds on manual updates until their integration has been reviewed. Installing only the standalone service ZIP does not register its update repository.

The standalone service ZIP and SHA-256 checksums are also available under [Releases](https://github.com/Drahy/service.sc.profilesync/releases). Neither ZIP contains credentials or a personal history database.

## Background checks

Local changes are captured every **15 seconds** and cloud updates are polled every **60 seconds** by default. Both intervals are adjustable in the addon's settings. Stop/end-of-playback and wake events queue an earlier sync after a two-second settling delay; manual **Synchronize now** runs without waiting for the periodic timer. Callbacks only queue work and never perform network or database operations themselves.

The lightweight event loop wakes about once a second to check flags. It does not read the viewing database or enumerate preferences on every wake. Periodic snapshot checks drop from 30 to four per minute compared with version 0.1.0; periodic network checks drop from three to one. These counts describe scheduling, not a measured CPU percentage. Network operations also take a fresh snapshot before merging changes.

Failed connections back off to three minutes with the default settings. Device changes made during a transfer are protected by an optimistic import check. Settings absent from an installed addon version are retained in the cloud without being written to that version. Running the addon requests another background sync; disabling its setting pauses synchronization. Credential-free status is recorded in local `status.json`.

## History and restore

The SC integration opens a show's last shared season and selects its exact last watched episode without starting playback. **All seasons** remains available in the context menu. It resolves saved IDs through current detail routes and pages older entries. Local crash recovery recognizes opaque catalogue aliases through stable item IDs. Navigation URLs and browser stacks are not uploaded.

Every installation creates its own identity. **Do not copy `device.json` or `state.json` between devices.** Existing viewing history is merged; a new installation's untouched preference defaults do not replace the existing cloud profile. Later explicit local edits are versioned normally.

Kodi's interface click/notification sound mode and volume are shared. Audio devices, HDMI output, speaker channels and passthrough stay local. Upgrade SC Profile Sync on every device so each version recognizes the same supported preferences. Newly supported preferences restore an existing cloud value before publishing an untouched local value.

Quit and native service-abort requests cancel pending profile work, including upload-verification backoff. Requests use short connection/read timeouts, and an interrupted upload keeps its reserved generation and local changes for the next start. Subtitle monitoring is closed before the service returns, including exceptional shutdown. Compatible Amber windows can use the transient shutdown guard described in the [integration guide](integration/README.md); the service never edits another addon automatically.

## Shared preferences and crash persistence

Common preferences include Kodi interface/audio languages, regional formats, keyboard layouts, subtitle font/size/style/position, skin theme/font, installed skin/sound/subtitle-service selections, file-list and video-library display options, seeking steps, and global update mode. Stream Cinema genre/menu/Skip options, parental-control choices and startup behavior are shared alongside its existing quality/language preferences. Up Next's activation toggle and the profile service's local/cloud intervals are also shared.

Resource selections apply only when that addon is already installed and enabled; synchronization does not install addons or download language packs. Platform-specific settings unavailable on a device are retained without being written there. Up Next logging/demo mode, the profile service's local pause switch and per-addon update rules remain local. Keep protection for patched addons enabled on each device.

The exact allowlists are in [policy.py](resources/lib/policy.py). Hardware-related stream bitrate/HDR/Dolby Vision/channel filters, display/HDR brightness, security controls, account settings and local paths are excluded. Custom widgets/menus, favourites, keymaps and complete addon installations are separate files rather than supported preference fields; retain their local backups.

Before acknowledging a captured or imported core/Amber preference, the service requests Kodi's native settings save and verifies the captured core values in `guisettings.xml`. Unchanged snapshots do not repeat this save. The internal `scprofilesync.internal.settingssaved` skin flag is always false and is never shared. A failed write leaves the change unacknowledged for retry. The atomic offline checkpoint is flushed separately. This protects completed captures/imports against a forced Kodi process termination; it does not promise recovery from a power failure or a change made before the next local capture.

## Subtitle audio rule

**Hide subtitles with Czech audio** is enabled by default and is itself synchronized. It disables all subtitle tracks, including forced tracks, when the current audio is tagged as Czech. For other audio it selects complete Czech subtitles, falls back to English and hides unsupported-language tracks. Switching audio tracks re-evaluates the choice. An explicit subtitle-off choice is retained for the current non-Czech track until a new playback/audio/stream selection.

Player notifications queue work for a separate local event worker; cloud/network delays do not block it. Three bounded rechecks during the first six seconds cover a provider enabling subtitles after its startup callback. Afterward it reacts to stream events without periodic stream scans. Stop clears pending work, and the service creates no additional player. Audio must have a usable language tag; burned-in captions are part of the image and cannot be disabled.

Kra must allow private-file access for the account. Availability after a subscription expires has not been established. A clean Kodi reinstall still requires the addons, the SC integration and the same Kra login. The cloud restores supported preferences and viewing state. Local artwork, complete skin installations, generated widgets and platform-specific shortcut paths require a separate local backup.

## Development and releases

Run `python -m pip install -r requirements-dev.txt`, then `python -m pytest -q tests`. Tests use isolated SQLite databases and a fake cloud backend. Optional SC integration tests require `SC_STORAGE_CANDIDATE` pointing to the matching patched SC `resources/lib/common` directory; they are skipped when that source is absent.

Run `python tools/build_repository.py` to generate deterministic, allowlisted addon ZIPs and the `repo/` update feed. Release procedure:

1. Update the addon version, User-Agent and [changelog](CHANGELOG.md), then run the tests and build script.
2. Commit the source and generated feed together. Preserve existing versioned packages.
3. Tag the commit `v<version>` and publish its service ZIP, repository ZIP, stable `repository.drahy.scprofilesync.zip` alias and checksums as a GitHub release. Never replace a published version with different contents.

The repository uses HTTPS, a SHA-256 feed checksum and versioned package URLs following [Kodi's repository format](https://kodi.wiki/view/Add-on_repositories). Never include private backups, account settings or real viewing histories in Git or release packages. See [CHANGELOG.md](CHANGELOG.md) for released changes.
