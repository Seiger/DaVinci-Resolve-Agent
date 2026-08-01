# Resolve bridge

`ResolveBridge.py` is the internal script launched through
`Workspace → Scripts → Edit → ResolveBridge` in DaVinci Resolve.

It uses the internal Resolve/Fusion context injected into a menu script, with
the documented `DaVinciResolveScript.scriptapp("Resolve")` entry point as a
fallback. Live Resolve 21 Free testing confirmed that the injected context is
available while a direct module import is not.

The bridge uses only calls documented in the Resolve 21.0.3 local Scripting
README. It records one heartbeat/state snapshot, processes allowlisted commands
already present in the filesystem queue, and exits. M4 write operations require
a successful `.drp` project export and store idempotency receipts.

M7 render discovery uses only documented read methods. Its separate preparation
action adds one fixed MP4/H264 job only after project backup.

M8 can read one job status and start one agent-prepared job through documented
Resolve methods. Before start it verifies the preparation receipt, fixed preset,
codec, output name and output root, creates a project backup, and writes a
durable per-job start record. It cannot start arbitrary or all queued jobs,
stop rendering, delete jobs, change settings, or upload anything.

M9 discovers MP4/H.264 resolutions through documented
`GetRenderResolutions` and permits only fixed 1920x1080 or 3840x2160 YouTube
profiles. Before adding a job, it verifies both the built-in preset and exact
resolution, then applies documented `FormatWidth` and `FormatHeight` settings.

M10 uses the documented `AppendToTimeline([{clipInfo}])` overload for one
bounded video-only or audio-only source range. It verifies the target track
exists and is unlocked, derives absolute `recordFrame` from the timeline start,
creates a backup, and reads actual placement back from documented TimelineItem
methods.

M46 extends the documented render path with one fixed
`audio-only-pcm-wav-v1` profile. The bridge loads the built-in `Audio Only`
preset, attempts the discovered Wave format with its empty codec identifier,
then treats the newly added queue job as authoritative readback. It forces
documented 16-bit/48 kHz
audio settings, disables video export, adds one job, and verifies the exact
queue fields before it can be started. No arbitrary render settings are
accepted from the command.
If the new job is not an audio-only WAV with the fixed settings, the bridge
deletes exactly that newly created job through documented `DeleteRenderJob`
and reports the rejected queue metadata.

M47 begins with the read-only `get_subtitle_environment` action. For one
canonical timeline it enumerates at most 128 subtitle tracks and 10000 items
through documented Timeline methods. It also reports whether the documented
`CreateSubtitlesFromAudio` method and required auto-caption constants are
present, but does not call the method. Surface availability is not treated as
proof that Resolve 21 Free can execute the Studio/AI operation;
`subtitle.auto_caption` therefore remains `unknown` until a confirmed live
write is independently verified.

The separate `create_subtitles_from_audio` action accepts only a canonical
timeline ID and `confirm_create=true`. It requires a project backup and uses a
fixed automatic-language/default-preset policy with 42 characters per line,
single-line captions and zero-frame gap. A `True` API return is insufficient:
the action succeeds only when bounded readback finds newly created subtitle
items. It exposes no model, prompt, language override or arbitrary settings.
Live Resolve 21 Free 21.0.3.7 returned `False` for this documented native call;
the bridge reported `AUTO_CAPTION_UNAVAILABLE` and kept the capability
unverified. M47 therefore applies locally generated SRT through the already
verified `ImportMedia`/`AppendToTimeline` path instead. The dedicated
`append_subtitle_file` action binds the SRT path and asset ID to the preceding
import receipt, records the pre-write timeline end as `append_frame`, and
requires bounded subtitle readback. Resolve places SRT timestamps relative to
that append anchor; the action does not claim playhead-based placement.

The one-shot lifecycle is intentional: persistent polling is not enabled until
live testing proves that it does not block the Resolve UI.

M18 adds a fixed workspace snapshot that composes existing read-only discovery
inside one queued command. It reduces full diagnostics to one menu invocation
without exposing arbitrary batches. Automatic external startup is not claimed
for Resolve 21 Free because the locally installed Resolve documentation
identifies the external Scripting API as a Resolve Studio facility.

M19 uses documented `Timeline.SetClipsLinked` and
`TimelineItem.GetLinkedItems` for an explicitly addressed group of 2 to 16
video/audio items. Every selected track must be unlocked, the project is
backed up before mutation, and the requested pairwise link state is read back
before success is reported.

M20 duplicates one explicitly addressed timeline through documented
`Timeline.DuplicateTimeline`. It rejects name conflicts, exports a project
backup, verifies a distinct ID and project membership, and leaves the current
timeline unchanged.
