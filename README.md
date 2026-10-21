# SC Profile Sync

Share Stream Cinema viewing history and selected preferences through the existing account's **private Kra storage**. Each Kodi device keeps a local database and a durable offline checkpoint. Separate versioned cloud files avoid one device overwriting another device's upload.

The service synchronizes Last seen, watched/unwatched states, episode/movie resume positions, the last played episode, per-title language choices, selected Stream Cinema and Up Next preferences, subtitle preferences and portable Amber appearance settings. Explicit deletions are retained so a stale client cannot restore a cleared resume position.

Passwords, access tokens, cached stream URLs, navigation checkpoints, HDR/decoder settings, audio output, speed tests and network limits stay local. The service uses the account already configured in Stream Cinema. It never controls playback, and imports are deferred during playback. Network failures leave changes queued locally.

## Installation

Install the matching repaired Stream Cinema build, its small local cache bridge, Amber and required dependencies on each device, then install this service. Keep a separate device identity for each installation; do not copy the service's `device.json` or `state.json` between devices. The approved shared profile is seeded once from the merged existing histories and preferences.

The service starts after Kodi initializes and synchronizes in the background. Running the addon requests another background sync. Disabling its setting pauses synchronization. Status is recorded in the addon's local `status.json`, without credentials or media URLs.

While Kodi runs, local changes are captured every two seconds and cloud changes are polled about every twenty seconds. Failed connections back off to three minutes, retaining pending local changes. Each device connects directly to Kra; no notebook server is needed. Addon settings are read through fresh Kodi handles so another script's changes are visible. Settings absent from an installed addon version are retained in the cloud without being written to that version.

The Last seen integration opens a show's last shared season and selects its exact last watched episode, without starting playback. The show's context menu retains an All seasons action. History resolves saved IDs through current detail routes, preserving recent-first order and paging older entries instead of depending on the unavailable legacy history endpoint. Local crash recovery also recognizes the catalog's opaque playback aliases through their stable item IDs. Navigation URLs and device-specific browser stacks are not uploaded.

Kra must allow private-file access for the configured account. Availability after a subscription expires has not been established. This addon does not turn a clean Kodi installation into an account-based restore by itself: install the recovery bundle and sign in to the same Kra account first. The cloud then restores supported preferences and viewing state.

The initial setup also copies the approved Amber source and menu configuration. Continuous appearance synchronization covers portable skin preferences; local artwork paths, generated skin code and platform-specific shortcut paths are excluded.

## Development

Run `python -m pytest -q tests`. Tests use isolated SQLite databases and a fake cloud backend. Live cloud tests use only separate synthetic private files and remove them after readback. Never include private deployment backups, account settings or real viewing histories in this repository.

## Unreleased

- Share a private cross-device playback profile and viewing history, with offline queues, conflict-aware imports and preserved device-specific playback settings. Last seen opens the last shared season and selects the exact episode for manual playback.

No release has been published.
