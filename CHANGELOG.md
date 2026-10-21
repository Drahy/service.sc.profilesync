# Changelog

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
