# Changelog

## 0.1.2 — 2026-10-21

- **Share interface sounds:** Synchronize Kodi's interface sound mode and volume while retaining local audio hardware, channel and passthrough settings. When an upgrade adds supported preferences, restore existing cloud values before a device's untouched defaults.

## 0.1.1 — 2026-10-21

- **Install and update through Kodi:** Add a repository installer, versioned addon ZIPs, SHA-256 feed checksums and a reproducible public package builder. Keep dependencies and separately repaired Stream Cinema builds explicit.
- **Quieter profile synchronization:** Check local changes every 15 seconds and cloud changes every 60 seconds by default, with adjustable intervals and queued sync after Stop or wake. Keep callbacks free of database/network work, preserve offline changes and restore cloud preferences before a new device's defaults.

## 0.1.0 — local build

- Share a private cross-device playback profile and viewing history, with offline queues, conflict-aware imports and preserved device-specific playback settings. The matching Stream Cinema integration opens the last shared season and selects its exact episode for manual playback.
