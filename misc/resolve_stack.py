import json
import sys
import numpy as np
import re
import matplotlib.pyplot as plt
import tkinter as tk
from tkinter.scrolledtext import ScrolledText

# see PlayerLoopCallbacks.h and Real unity profiler
# TODO: Consider add other markers like director or animation, add more pattern   
PHASE_PRIORITY = [
    "FixedUpdate",   # highest priority
    "Update",
    "LateUpdate",
    "Physics",
    "Render",        # lowest priority among real phases
]

# TODO: Find a more robust way of label phases
# Also note that the phase order is not reliable too, physics may come from Update
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
    "Render": [   # no render because nativeRender
        "PlayerRender",
        "RenderSettings",
        "ForwardShaderRenderLoop",
        "Camera::",
        "ShaderLab::",
        "ImageFilters::",
        "RenderManager::",
        "SkinnedMeshRendererManager::",
        "RendererScene::"
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
    
    # keep the stack short
    match = re.match(r'^([^\(]+)\(', frame_str)
    if match:
        frames.append(match.group(1).strip())
    else :
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
            "stacks": [s["reversed_stack_array"] for s in samples[start_idx:end_idx+1]]
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
    "stacks": [s["reversed_stack_array"] for s in samples[start_idx:]]
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
                    "stacks": first["stacks"] + gap_run["stacks"] + second["stacks"],
                }
                merged_runs.append(merged)
                merge_logs.append(
                    f"Merged Other at {first['end_t']}->{second['start_t']} "
                    f"(gap {gap} ms, dropped phase {gap_run['phase']} : {gap_run['stacks']})"
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
    # Define phase order (lower number = earlier in frame)
    phase_order = {
        "FixedUpdate": 0,
        "Update": 2,
        "LateUpdate": 3,
        "Render": 5,
    }
    
    frame_boundaries = []
    frame_runs = []
    warnings = []
    current_frame_start_idx = 0
    last_phase_order = -1
    last_was_render = False
    
    for idx, run in enumerate(runs):
        phase = run["phase"]
        
        # Skip "Other" and "Physics" phases for sequence detection
        if phase == "Other" or phase == "Physics":
            # If last phase was Render, even "Other" or "Physics" starts a new frame
            if last_was_render and idx > current_frame_start_idx:
                frame_runs.append(runs[current_frame_start_idx:idx])
                frame_boundaries.append(run["start_t"])
                current_frame_start_idx = idx
                last_phase_order = -1
                last_was_render = False
            continue

        phase_num = phase_order.get(phase, 6)
        
        # Check if this phase indicates a new frame
        # New frame if: 
        # 1. We see a phase that should come before the last non-Other phase
        # 2. OR the last phase was Render (Render ends a frame)
        if phase_num < last_phase_order or last_was_render:
            # This is the start of a new frame
            if idx > current_frame_start_idx:
                # Store the previous frame
                frame_runs.append(runs[current_frame_start_idx:idx])
                # Use the start of the new frame as boundary
                frame_boundaries.append(run["start_t"])
            current_frame_start_idx = idx
            last_phase_order = phase_num
            last_was_render = False
        else:
            # Continue in current frame
            last_phase_order = phase_num
        
        # Track if this was a Render phase
        last_was_render = (phase == "Render")
    
    # Don't forget the last frame
    if current_frame_start_idx < len(runs):
        frame_runs.append(runs[current_frame_start_idx:])
    
    # Now we need to ensure we have proper boundaries
    # frame_boundaries currently contains the start times of frames 1, 2, ..., N-1
    # We need to add the start of frame 0 and the end of the last frame
    
    if len(frame_runs) > 0:
        # Insert the start time of the first frame at the beginning
        frame_boundaries.insert(0, frame_runs[0][0]["start_t"])
        # Add the end time of the last frame at the end
        frame_boundaries.append(frame_runs[-1][-1]["end_t"])
    
    # Drop first and last frames as they are often partial
    if len(frame_runs) > 2:
        # Drop first and last frames
        frame_runs = frame_runs[1:-1]
        # For boundaries, we need to keep N+1 boundaries for N frames
        # So we drop the first boundary and the last boundary
        frame_boundaries = frame_boundaries[1:-1]
        print(f"Dropped first and last frames (often partial). Analyzing {len(frame_runs)} complete frames.")
    
    # Calculate frame times from boundaries
    # frame_times[i] = frame_boundaries[i+1] - frame_boundaries[i] = duration of frame_runs[i]
    frame_times = np.diff(frame_boundaries) if len(frame_boundaries) > 1 else np.array([])
    
    # Verify alignment
    if len(frame_times) != len(frame_runs):
        warnings.append(f"Index mismatch: {len(frame_runs)} frames but {len(frame_times)} frame times!")
    
    return frame_runs, frame_times, warnings

# ——— USAGE ———
# after you've built (and maybe merged) `runs`:
frame_runs, frame_times, warns = extract_frame_metrics_with_warnings(runs)
stats = {}
if frame_times.size > 0:
    stats = {
        "avg_ms": np.mean(frame_times),
        "min_ms": np.min(frame_times),
        "max_ms": np.max(frame_times),
    }
print(f"Detected frames: {len(frame_runs)}")
if frame_times.size > 0:
    print(f"Avg frame time: {stats['avg_ms']:.2f} ms  (min {stats['min_ms']:.2f}, max {stats['max_ms']:.2f})")

for w in warns:
    print(w)

x = np.arange(1, len(frame_times) + 1)

fig, ax = plt.subplots()
line, = ax.plot(x, frame_times, marker='o', linestyle='-')
ax.set_xlabel('Frame #')
ax.set_ylabel('Frame Time (ms)')
ax.set_title('Frame Time per Frame')
ax.grid(True)
line.set_picker(5)

annot = ax.annotate(
    "",                            # no text yet
    xy=(0,0),                      # will be updated when clicked
    xytext=(15,15),                # offset the text
    textcoords="offset points",
    bbox=dict(boxstyle="round", fc="w"),
    arrowprops=dict(arrowstyle="->")
)
annot.set_visible(False)
runs_text = fig.text(0.1, -0.15, "", wrap=True, fontsize=10, ha='left', va='top', transform=ax.transAxes)

def show_runs_in_popup(ind):
    runs = frame_runs[ind]
    frame_time = frame_times[ind]
    root = tk.Tk()
    root.title("Frame Details")
    root.geometry("800x600")
    text = ScrolledText(root, wrap=tk.WORD, font=("Consolas", 10))
    text.pack(expand=True, fill='both')
    
    frame_start = runs[0]["start_t"]
    frame_end = runs[-1]["end_t"]
    frame_duration = frame_end - frame_start
    
    # TODO: the self time and real time diff can be huge, consider when main thread is 
    # waitforpresent while gfxthread is compiling shader
    text.insert(tk.END, f"Self time: {frame_duration:.2f} ms, real time {frame_time:.2f} ms \n")
    text.insert(tk.END, f"Frame Start: {frame_start:.2f} ms, End: {frame_end:.2f} ms\n")
    text.insert(tk.END, "-" * 10 + "\n\n")
    
    for i, r in enumerate(runs):
        phase_duration = r['end_t'] - r['start_t'] + 1
        text.insert(tk.END, f"Phase {i+1}: {r['phase']}\t")
        text.insert(tk.END, f"  Duration: {phase_duration:.2f} ms ({r['start_t']:.2f} - {r['end_t']:.2f})\t")
        text.insert(tk.END, f"  Samples: {len(r['stacks'])}\n")
        
        if r['stacks'] and len(r['stacks']) > 0:
            shown_stacks = set()
            for stack in r['stacks']:
                if stack and len(stack) > 0:
                    # Show top 5 frames of the stack
                    stack_preview = " -> ".join(stack[:5])
                    if len(stack) > 5:
                        stack_preview += f" ... (+{len(stack)-5} more)"
                    
                    text.insert(tk.END, f"    {stack_preview}\n")
        
        text.insert(tk.END, "\n")
    
    text.config(state=tk.DISABLED)
    root.mainloop()

def on_pick(event):
    ind = event.ind[0]
    xdata, ydata = line.get_data()
    x0, y0 = xdata[ind], ydata[ind]
    annot.xy = (x0, y0)
    annot.set_text(f"Frame {int(x0)}: {y0:.2f} ms")
    annot.set_visible(True)
    show_runs_in_popup(ind)
    fig.canvas.draw()

fig.canvas.mpl_connect('pick_event', on_pick)
plt.subplots_adjust(bottom=0.3)  # Make space for the text box
plt.show()
