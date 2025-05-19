import json

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
    responsiveness_idx_field = sample_schema.get("responsiveness", 2)
    
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
        sample_resp = sample[responsiveness_idx_field]

        relative_time = int(sample_time - global_min_time)
        
        # Replace the stack number with a human-readable call stack string.
        if sample_stack_index is not None and stack_table:
            stack_frames = resolve_stack(sample_stack_index, stack_table, frame_table, string_table, stack_table_schema, frame_table_schema)
            # You can join with an arrow or newline as preferred.
            reversed_stack_array  = list(reversed(stack_frames))
        else:
            reversed_stack_array  = "No stack info"
        
        thread_samples.append({
            "relative_time": relative_time,
            "reversed_stack_array": reversed_stack_array
        })
       
        # print(f"  Sample: Time: {relative_time}, Responsiveness: {sample_resp}")
        # print(f"    Stack: {reversed_stack_array }")
    
    thread_result = {
        "name": thread_name,
        "tid": tid,
        "sample_size": len(thread_samples),
        "samples": thread_samples
    }
    results.append(thread_result)


target_thread_name = "UnityMain"
# gfx_thread = next((thread for thread in results if thread["name"] == target_thread_name), None)

# if gfx_thread is None:
#     print(f"Thread '{target_thread_name}' not found.")
# else:
#     frame_events = []  # List to store relative_time of frame-end events.
#     previous_was_frame_event = False

#     for s in gfx_thread["samples"][0]["reversed_stack_array"]:
#         print(s,sep="\n")
