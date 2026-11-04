# Changelog

## Unreleased — Stream Cinema integration

- **Open Up Next settings from Stream Cinema:** Add shortcuts on the home screen and in Stream Cinema playback settings when Up Next is installed; retain the home shortcut when the catalogue is unavailable.
- **Unify Last Seen on the home screen:** Show the locally synchronized history across categories in one list and open the synchronized series history from the existing Last Watched entry. Preserve each item's category, saved position, removal behavior and episode selection. Reuse previously resolved metadata without automatic expiry, stop repeated requests after a service-wide failure, and pause local history lookups after an HTTP 429 response. Hide unnamed unavailable entries without removing their saved history.
- **Open Webshare during catalogue outages:** Keep a direct Webshare entry on the Stream Cinema home screen even when its catalogue cannot be reached.
- **Protect history when local storage is unavailable:** Suspend profile capture until Stream Cinema's database is available instead of treating a missing database as deletion of every saved item.
- **Keep proxy streams available during playback and wake:** Serve Webshare file metadata locally and cancel its active transfer on Stop. Protect active Android and Windows helper sessions from expiry and refresh a known expired stream using its original item and the current Stream Cinema account session. Preserve range requests, cached metadata, explicit Stop and normal cleanup of unused sessions. Keep a bounded in-memory item lookup without storing credentials; recovery requires the helper to have registered the item before sleep and a working account session. Install the companion helper integration separately; the released SC Profile Sync package remains unchanged.
- **Return to the watched episode on every fresh entry:** Add films and series to Last Seen after ten seconds of actual playback and open the most recently played episode, including an unfinished one, after Kodi startup, a fresh Stream Cinema entry, wake or selection in Last Seen, without starting playback. After Webshare Stop, select the episode in Stream Cinema when available, or return to the selected Webshare file when the episode has no catalogue row. Retry transient connection failures during automatic return without repeated error dialogs, and stop retrying when playback starts or the user leaves the folder. Keep completed-episode state and bookmarks separate, preserve explicit history removal and normal Back navigation, and retain unavailable history entries using locally cached titles or a temporary placeholder. Retry film metadata through its playback detail when its folder response is empty. Install the companion Stream Cinema integration files explicitly; the released SC Profile Sync package remains unchanged.
- **Start sequential episodes from the beginning by default:** For episodes requested by Up Next, offer a saved resume time for five seconds before starting from the beginning. Pause the deadline while navigating the choice and let Back, Stop or Cancel abandon playback. Preserve ordinary manual resume behavior and saved positions. Install the companion Stream Cinema integration separately; the official Up Next package remains unchanged.
- **Use playback controls alongside Up Next:** Provide the optional playback-controls patch for Up Next 1.3.0 together with the maintainer's upstream file-handoff timing fix. Let initial OK/Select open the native OSD, use Up to return from Next/Close to playback-control focus, and restore the popup after Kodi hides it while controls are open, including when a dedicated OSD action is used with the option disabled. Preserve Stop/Back behavior and pause-aware automatic advancement. Enable the new local option explicitly on each device; the released SC Profile Sync package remains unchanged.

## 0.1.5 — 2026-10-21

- **Reopen the last episode folder promptly after Exit:** The updated Stream Cinema integration restores the last local season and selected episode after a normal Kodi exit, including Exit through Home, without starting playback. Reuse merge snapshots and the Home window during profile reads, and prepare directory metadata without GUI locks. Keep active-context crash recovery and shared Last seen history separate; reapply the updated integration files to existing Stream Cinema installations.

## 0.1.4 — 2026-10-21

- **Stop background work before Kodi teardown:** Observe Quit before the startup delay, cancel profile transfers and upload-verification waits between bounded requests, and always stop subtitle monitoring. Drain each thread's pending Kodi callbacks before releasing its monitor to prevent native teardown crashes. Keep unfinished changes queued for the next start, follow Kra sessions refreshed locally by Stream Cinema, and signal compatible Amber windows to avoid deferred settings saves during shutdown.

## 0.1.3 — 2026-10-21

- **Share common preferences durably:** Synchronize interface language, regional formats, subtitle appearance, installed skin/sound resources, browsing and seeking choices, common Stream Cinema options, Up Next activation and synchronization intervals. Request and verify Kodi's native settings save before acknowledging captured or imported core preferences; retain hardware, credentials, paths and security controls locally.
- **Hide subtitles with Czech audio:** Automatically disable subtitle tracks for Czech audio, including forced tracks. For other audio, prefer complete Czech subtitles with English fallback and reject other languages. Respond independently of cloud transfers, cancel pending checks on Stop and preserve a manual subtitle-off choice for the current non-Czech track. Changing visibility keeps the selected subtitle decoder instead of reopening it.

## 0.1.2 — 2026-10-21

- **Share interface sounds:** Synchronize Kodi's interface sound mode and volume while retaining local audio hardware, channel and passthrough settings. When an upgrade adds supported preferences, restore existing cloud values before a device's untouched defaults.

## 0.1.1 — 2026-10-21

- **Install and update through Kodi:** Add a repository installer, versioned addon ZIPs, SHA-256 feed checksums and a reproducible public package builder. Keep dependencies and separately repaired Stream Cinema builds explicit.
- **Quieter profile synchronization:** Check local changes every 15 seconds and cloud changes every 60 seconds by default, with adjustable intervals and queued sync after Stop or wake. Keep callbacks free of database/network work, preserve offline changes and restore cloud preferences before a new device's defaults.

## 0.1.0 — local build

- Share a private cross-device playback profile and viewing history, with offline queues, conflict-aware imports and preserved device-specific playback settings. The matching Stream Cinema integration opens the last shared season and selects its exact episode for manual playback.
