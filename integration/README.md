# Stream Cinema integration

These small patches apply to the reviewed local Stream Cinema 2.6.7.1+k19 build. They preserve the separate Stop, resume-completion, subtitle and quality-selection repairs already present in that build.

- Apply `storage.patch` and `lists.patch` within `resources/lib/common` with `git apply -p0`.
- Copy `resources/lib/sc_bridge.py` from this repository to SC's `resources/lib/common/profile_sync.py`.
- Apply `last-seen-browse.patch` from the SC addon root with `git apply`.
- Copy `resources/lib/sc_browse.py` to SC's `resources/lib/common/resume_browse.py`.

The bridges perform local cache invalidation, safe SQLite merging and exact episode selection. They contain no cloud requests or playback commands. The profile service performs cloud operations independently and defers imports during playback.

Keep the locally patched Stream Cinema and helper on manual updates. Reapply these patches to a reviewed future build before enabling it. Up Next uses the upstream 1.2.1 code, including the accepted replacement-playback fix in upstream commit `42184af3d4d2`; the optional credits-autoplay change in PR 336 is not installed.

For the integration and navigation tests, set `SC_STORAGE_CANDIDATE` to the patched SC `resources/lib/common` directory, then run `pytest -q tests`.

## Optional Amber shutdown guards

The [Amber patch](amber-shutdown.patch) contains the companion changes tested with Amber 3.99.02 on Kodi 21.3. It avoids empty search resets and prevents unload hooks from scheduling deferred skin-setting saves after the profile service has begun stopping. Normal navigation retains its existing behavior; the guard is ignored while SC Profile Sync is disabled. Shutdown skips the final Home focus/background writes and retains their previously stored values. This does not affect Stream Cinema's separate season/episode navigation checkpoints.

Apply it to a backed-up compatible Amber checkout with `git apply --check` followed by `git apply`, or review and apply the corresponding XML edits in the installed skin. Restart Kodi after updating both the skin and SC Profile Sync 0.1.4 or newer. The service itself does not patch skin files, change update policies or replace Kodi binaries. A later skin reinstall/update may replace those XML edits; retain the reviewed patch or use a skin version that includes it.
