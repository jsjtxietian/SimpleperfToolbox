import json
import sys
import numpy as np
import re

# see PlayerLoopCallbacks.h and Real unity profiler
# add other markers like director or animation, add more pattern   

PHASE_PRIORITY = [
    "Update",
    "LateUpdate",
    "FixedUpdate",   # highest priority
    "Physics",
    "Render",        # lowest priority among real phases
]

RAW_PHASE_PATTERNS = {
    "FixedUpdate": [
        r"CommonUpdate<FixedBehaviourManager>",
    ],
    "Physics": [
        r"PhysicsManager",
    ],
    "Update": [
        r"CommonUpdate<BehaviourManager>",
    ],
    "LateUpdate": [
        r"CommonUpdate<LateBehaviourManager>",
    ],
    "Render": [
        "PlayerRender",
        "RenderSettings",
        "ForwardShaderRenderLoop",
        "Camera::",
        "ShaderLab::",
        "GfxDeviceClient::",
        "GfxDevice::",
        "ImageFilters::",
        "SkinnedMeshRendererManager::"
    ],
}

PHASE_PATTERNS = {
    phase: re.compile(
        r"|".join(re.escape(pat) for pat in pats)
    )
    for phase, pats in RAW_PHASE_PATTERNS.items()
}

def label_sample(frames):
    for phase in PHASE_PRIORITY:
        pat = PHASE_PATTERNS.get(phase)
        if not pat:
            print("CHECK PHASE_PRIORITY AND PHASE_PATTERNS!")
        if any(pat.search(f) for f in frames):
            return phase
    return "Other"


def resolve_stack(stack_index, stack_table_data, frame_table_data, string_table, stack_schema, frame_schema):
    """
    Recursively resolves a stack table entry into a list of frame strings.
    
    stack_index: index into the stack_table_data.
    stack_table_data: list of stack table records.
    frame_table_data: list of frame table records.
    string_table: list of strings used in the profile.
    stack_schema: mapping for the stack table (e.g. {"prefix":0, "frame":1}).
    frame_schema: mapping for the frame table (e.g. {"location":0}).
    
    Returns a list of frame strings from bottom (root) to top.
    """
    if stack_index is None:
        return []
    entry = stack_table_data[stack_index]
    # Using the schema to extract the prefix pointer and frame index.
    prefix_index = entry[ stack_schema.get("prefix", 0) ]
    frame_idx = entry[ stack_schema.get("frame", 1) ]
    
    # Recursively resolve any prefix entries (i.e. the rest of the call stack).
    frames = []
    if prefix_index is not None:
        frames.extend(resolve_stack(prefix_index, stack_table_data, frame_table_data, string_table, stack_schema, frame_schema))
    
    # Now resolve the current frame using the frame table.
    frame_record = frame_table_data[frame_idx]
    location_idx = frame_record[ frame_schema.get("location", 0) ]
    frame_str = string_table[location_idx] if 0 <= location_idx < len(string_table) else "<unknown>"
    frames.append(frame_str)
    
    return frames

# Load the JSON profile
with open(sys.argv[1], "r") as f:
    profile = json.load(f)

global_times = []
for thread in profile.get("threads", []):
    samples = thread.get("samples", {})
    sample_data = samples.get("data", [])
    sample_schema = samples.get("schema", {})
    time_idx = sample_schema.get("time", 1)
    for sample in sample_data:
        global_times.append(sample[time_idx])
global_min_time = min(global_times) if global_times else 0

results = []

# Iterate over each thread
for thread in profile.get("threads", []):
    thread_name = thread.get("name", "Unnamed Thread")
    tid = thread.get("tid", "N/A")
    # print(f"Thread: {thread_name} (TID: {tid})")
    
    # Get the samples and schema for the thread
    samples = thread.get("samples", {})
    sample_data = samples.get("data", [])
    sample_schema = samples.get("schema", {})
    # Determine the field positions in each sample entry.
    stack_idx_field = sample_schema.get("stack", 0)
    time_idx_field = sample_schema.get("time", 1)
    
    # Get stackTable, frameTable, and stringTable data and their schemas
    stack_table = thread.get("stackTable", {}).get("data", [])
    stack_table_schema = thread.get("stackTable", {}).get("schema", {"prefix": 0, "frame": 1})
    frame_table = thread.get("frameTable", {}).get("data", [])
    frame_table_schema = thread.get("frameTable", {}).get("schema", {"location": 0})
    string_table = thread.get("stringTable", [])
    
    thread_samples = []
    for sample in sample_data:
        sample_stack_index = sample[stack_idx_field]
        sample_time = sample[time_idx_field]

        relative_time = float(f"{sample_time - global_min_time:.2f}")
        
        # Replace the stack number with a human-readable call stack string.
        if sample_stack_index is not None and stack_table:
            stack_frames = resolve_stack(sample_stack_index, stack_table, frame_table, string_table, stack_table_schema, frame_table_schema)
            # You can join with an arrow or newline as preferred.
            reversed_stack_array  = list(reversed(stack_frames))
        else:
            reversed_stack_array  = "No stack info"

        phase = label_sample(reversed_stack_array)
        thread_samples.append({
            "relative_time": relative_time,
            "reversed_stack_array": reversed_stack_array,
            "phase": phase
        })
    
    thread_result = {
        "name": thread_name,
        "tid": tid,
        "samples": thread_samples
    }
    results.append(thread_result)

runs = []

main_thread = next((t for t in results if t["name"] == "UnityMain"), None)
samples = main_thread["samples"]
prev_phase = samples[0]["phase"]
start_idx  = 0
for i, s in enumerate(samples[1:], start=1):
    if s["phase"] != prev_phase:
        end_idx = i - 1
        runs.append({
            "phase": prev_phase,
            "start_i": start_idx,
            "end_i": end_idx,
            "start_t": samples[start_idx]["relative_time"],
            "end_t":   samples[end_idx]["relative_time"],
            "stack": samples[start_idx]["reversed_stack_array"]
        })
        prev_phase = s["phase"]
        start_idx  = i
# append the final run
runs.append({
    "phase": prev_phase,
    "start_i": start_idx,
    "end_i": len(samples)-1,
    "start_t": samples[start_idx]["relative_time"],
    "end_t":   samples[-1]["relative_time"],
    "stack": samples[-1]["reversed_stack_array"]
})

# for r in runs:
#     print(r)

def CleanGap(origin_run, merge_thresh, count):
    merged_runs = []
    merge_logs  = []
    i = 0

    while i < len(origin_run):
        cur = origin_run[i]

        # Pattern: Render => Other => Render
        if (cur["phase"] == "Render"
            and i+2 < len(origin_run)
            and origin_run[i+1]["phase"] == "Other"
            and origin_run[i+2]["phase"] == "Render"):

            first = cur
            gap_run = origin_run[i+1]
            second = origin_run[i+2]

            gap = second["start_t"] - first["end_t"]
            if gap < merge_thresh:
                # Build a single merged Render run
                merged = {
                    "phase":   "Render",
                    "start_i": first["start_i"],
                    "end_i":   second["end_i"],
                    "start_t": first["start_t"],
                    "end_t":   second["end_t"],
                }
                merged_runs.append(merged)
                merge_logs.append(
                    f"Merged Other at {first['end_t']}->{second['start_t']} "
                    f"(gap {gap} ms, dropped phase {gap_run['phase']} : {gap_run['stack']})"
                )
                i += 3
                continue

        # otherwise, just keep the current run
        merged_runs.append(cur)
        i += 1
    
    # Optional: print out merge logs
    print(f"========= {count} =========")
    for log in merge_logs:
        print(log)
    print(f"========= {count} over =========")


    return merged_runs

# Do twice to compress more 
# Render => Other => Render => Other
# TODO, make it more flexible, a third of average frame time?
runs = CleanGap(runs, 6, 0)
runs = CleanGap(runs, 6, 1)

for r in runs:
    print(r)

def extract_frame_metrics_with_warnings(runs, min_frame_time = 6):
    """
    Returns: (
      frame_boundaries,  # list of end_t for each detected frame
      frame_count,       # int
      frame_times,       # np.ndarray of deltas
      stats,             # dict with avg_ms, min_ms, max_ms
      warnings           # list of warning strings
    )
    """

    # 1) Walk through runs, using each Render as a frame boundary
    frame_boundaries = []
    warnings = []
    prev_render_idx = None

    for idx, run in enumerate(runs):
        if run["phase"] != "Render":
            continue

        # We have a Render boundary at runs[idx]["end_t"]
        cur_end = run["end_t"]

        if prev_render_idx is not None:
            # Collect all runs between the two Renders
            in_frame = runs[prev_render_idx+1 : idx]

            has_update = any(r["phase"] == "Update" for r in in_frame)
            has_late   = any(r["phase"] == "LateUpdate"  for r in in_frame)

            if not has_update and not has_late:
                warnings.append(
                    f"Frame ending at {cur_end} ms missing: Update or LateUpdate"
                )
            
            if len(frame_boundaries) > 2 and cur_end - frame_boundaries[-1] < min_frame_time:
                print(f"run is too small {cur_end - frame_boundaries[-1]}: before {len(runs[prev_render_idx+1 : idx + 1])}: {runs[prev_render_idx+1 : idx + 1]}")

        # TODO: use the end of Render to determine? or the start time of next frame
        frame_boundaries.append(cur_end)
        prev_render_idx = idx

    # 2) Compute metrics
    frame_count = len(frame_boundaries)
    frame_times = np.diff(frame_boundaries) if frame_count > 1 else np.array([])
    stats = {}
    if frame_times.size > 0:
        stats = {
            "avg_ms": np.mean(frame_times),
            "min_ms": np.min(frame_times),
            "max_ms": np.max(frame_times),
        }

    return frame_boundaries, frame_count, frame_times, stats, warnings

# ——— USAGE ———
# after you've built (and maybe merged) `runs`:
boundaries, count, times, stats, warns = extract_frame_metrics_with_warnings(runs)
print(f"Detected frames: {count}")
if times.size > 0:
    print(f"Avg frame time: {stats['avg_ms']:.2f} ms  (min {stats['min_ms']:.2f}, max {stats['max_ms']:.2f})")

for w in warns:
    print(w)

'''
frame_events = []
samples = None

if True:
    # broken stack
    markers = ["PlayerRender", "Camera::CustomRender"]
    main_thread = next((t for t in results if t["name"] == "UnityMain"), None)
    samples = main_thread["samples"]

    in_marker_run = False
    last_marker_rt = None

    for s in samples:
        rt = s["relative_time"]
        stack = s["reversed_stack_array"] or []
        
        if any(marker in f for marker in markers for f in stack):
            # we're inside a marker run; remember this rt as the latest
            in_marker_run = True
            last_marker_rt = rt
        else:
            # run ended → emit the last marker time
            if in_marker_run:
                frame_events.append(last_marker_rt)
                in_marker_run = False
                last_marker_rt = None

    # if the last sample was in a marker run, emit its last rt too
    if in_marker_run and last_marker_rt is not None:
        frame_events.append(last_marker_rt)
else:
    marker = "eglSwapBuffers"
    gfx_thread = next((t for t in results if t["name"] == "UnityGfxDeviceW"), None)
    samples = gfx_thread["samples"]
    
    in_frame = False
    for s in samples:
        rt = s["relative_time"]
        stack = s["reversed_stack_array"] or []
        # marker hits => new frame boundary
        if any(marker in f for f in stack):
            if not in_frame:
                frame_events.append(rt)
                in_frame = True
        else:
            in_frame = False

num_frames = len(frame_events)
frame_times = [frame_events[i] - frame_events[i-1] for i in range(1, num_frames)]

print(num_frames)
print(numpy.average(frame_times))

threshold_ms = 4
short_intervals = []

for prev, curr in zip(frame_events, frame_events[1:]):
    delta = curr - prev
    if delta < threshold_ms:
        short_intervals.append((prev, curr, delta))

if not short_intervals:
    print("No intervals under", threshold_ms, "ms")
else:
    print(f"{len(short_intervals)} Intervals under {threshold_ms} ms:")
    for start, end, delta in short_intervals:
        print(f"  {delta} ms between {start} ms → {end} ms")

while True:
    user = input("relative_time> ").strip()
    if user.lower() in ("q","quit","exit",""):
        break
    try:
        t = int(user)
    except ValueError:
        print("  ↳ please enter an integer or 'q'")
        continue

    # find a sample at exactly that relative_time
    smp = next((s for s in samples if s["relative_time"] == t), None)
    if not smp:
        print(f"  ↳ no sample at {t} ms")
    else:
        print(f"\nCall stack at {t} ms:")
        for frame in smp["reversed_stack_array"]:
            print("   ", frame)
        print()
'''
