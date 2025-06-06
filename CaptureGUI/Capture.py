import tkinter as tk
import tkinter.ttk as ttk
from tkinter import filedialog, messagebox
import os
import shutil
import subprocess
from datetime import datetime
import zipfile
import json
import concurrent.futures
import sys
import threading
import time

if getattr(sys, 'frozen', False):
    # Running as a PyInstaller bundle
    RUNTIME_DIR = os.path.dirname(sys.executable)
else:
    # Running as a script
    RUNTIME_DIR = os.path.dirname(os.path.abspath(__file__))

BASE_DIR = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
java_path = os.path.join(BASE_DIR, "deps", "jbr", "bin", "java.exe")
manifest_editor_jar = os.path.join(BASE_DIR, "deps", "other", "ManifestEditor-2.0.jar")
zipalign_path = os.path.join(BASE_DIR, "deps", "other", "zipalign.exe")
apksigner_jar = os.path.join(BASE_DIR, "deps", "other", "apksigner.jar")
gecko_script = os.path.join(BASE_DIR, "deps", "extras", "simpleperf", "scripts", "gecko_profile_generator.py")
app_profiler_script = os.path.join(BASE_DIR, "deps", "ndk", "simpleperf", "app_profiler.py")
report_func = os.path.join(BASE_DIR, "deps", "ndk", "simpleperf", "report.py")

# Load config from deps/other/config.json
config_path = os.path.join(BASE_DIR, "deps", "other", "config.json")
with open(config_path, "r", encoding="utf-8") as f:
    config = json.load(f)

keystore_path = os.path.join(BASE_DIR, "deps", "other", config["keystore_file"])
keystore_pass = config["keystore_pass"]
package_name = config["package_name"]

capture_process = None
local_folder = None

# Add frequency selection variable and default
frequency_var = None
# trace_offcpu_var = None

def make_apk_debuggable(apk_path):
    # log_message(f"Making {apk_path} debuggable...", color="cyan")
    # print(f"Making {apk_path} debuggable...")

    # base, ext = os.path.splitext(apk_path)
    # debuggable_apk = f"{base}_debuggable{ext}"
    # aligned_debuggable_apk = f"{base}_aligned_debuggable{ext}"

    # # Construct the commands
    # command1 = (
    #     f'{java_path} -jar {manifest_editor_jar} "{apk_path}" '
    #     f'-o "{debuggable_apk}" -d 1'
    # )
    # command2 = (
    #     f'{zipalign_path} 4 "{debuggable_apk}" "{aligned_debuggable_apk}"'
    # )
    # command3 = (
    #     f'{java_path} -jar {apksigner_jar} sign '
    #     f'--v1-signing-enabled --v2-signing-enabled '
    #     f'--ks {keystore_path} --ks-pass pass:{keystore_pass} '
    #     f'"{aligned_debuggable_apk}"'
    # )

    # try:
    #     subprocess.run(command1, shell=True, check=True)
    #     subprocess.run(command2, shell=True, check=True)
    #     subprocess.run(command3, shell=True, check=True)

    #     if os.path.exists(debuggable_apk):
    #         os.remove(apk_path)
    #         os.remove(debuggable_apk)
    #         log_message(f"Deleted intermediate APK file: {debuggable_apk}", color="green")
    #     log_message("All commands executed successfully!", color="green")
    # except subprocess.CalledProcessError as e:
    #     log_message(f"Error running command: {e}", color="red")
    return True

def start_capture():
    global capture_process
    global local_folder
    if local_folder is None:
        log_message("Please fetch an APK first to create a working folder.", color="red")
        return False
    try:
        duration = duration_entry.get()
        if not duration.isdigit() or int(duration) <= 0:
            log_message("Please enter a valid positive number for duration.", color="red")
            return False
        
        duration = int(duration)
        frequency = frequency_var.get()

        # Command to start simpleperf
        # trace_offcpu = trace_offcpu_var.get()
        # trace_flag = "--trace-offcpu" if trace_offcpu else ""
        record_args = f"-e cpu-clock -f {frequency} --duration {duration} -g".strip()
        cmd = [
            "python",
            app_profiler_script,
            "-p", package_name,
            "-r", record_args
        ]
        # Start the process, capturing output (optional) and allowing termination
        capture_process = subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_CONSOLE, cwd=local_folder)
        log_message(f"Capture started! Running for {duration} seconds at {frequency} Hz...", color="green")
        
        # Start countdown in a separate thread
        def countdown_progress():
            for i in range(duration + 5, 0, -1):
                percent = 100 - int((i / (duration + 5)) * 100)
                log_message(f"Simpleperf Profiling Progress {percent}%")
                time.sleep(1)
            log_message("Simpleperf Profiling Capture Complete")
        threading.Thread(target=countdown_progress, daemon=True).start()
        return True
    except Exception as e:
        log_message(f"Failed to start capture: {e}", color="red")
        return False

def fetch_apk():
    global local_folder
    apk_path = apk_entry.get()
    if not apk_path or not os.path.exists(apk_path):
        messagebox.showerror(f"Error", "Please provide a valid APK path: {apk_path}")
        log_message(f"Error: Please provide a valid APK path: {apk_path}", color="red")
        return
    
    # Define local folder
    timestamp = datetime.now().strftime("%Y%m%d_%H_%M_%S")  # e.g., 20250224_153045
    results_dir = os.path.join(RUNTIME_DIR, "Results")
    os.makedirs(results_dir, exist_ok=True)  # Ensure Results folder exists
    local_folder = os.path.join(results_dir, f"apks_{timestamp}")
    os.makedirs(local_folder, exist_ok=True)  # Create folder if it doesn't exist
    
    # Get the original APK filename and construct local path
    apk_filename = os.path.basename(apk_path)
    local_apk_path = os.path.join(local_folder, apk_filename)
    
    # Copy APK to local folder
    shutil.copy(apk_path, local_apk_path)

    # Check if the APK comes from an "etc" package and pull additional files
    current_folder = os.path.dirname(apk_path)  # e.g., before_shell_etc
    parent_folder = os.path.dirname(current_folder)  # e.g., FFO_OB48_...
    log_message(f"Use apk from {current_folder}", color="cyan")
    
    current_folder = os.path.dirname(apk_path)
    parent_folder = os.path.dirname(current_folder)
    symbol_folder = os.path.join(local_folder, "Symbol")
    
    package_type = None
    if "etc" in apk_filename.lower():
        package_type = "etc"
    elif "astc" in apk_filename.lower():
        package_type = "astc"
    
    if package_type:
        # Handle symbols.zip
        for file in os.listdir(parent_folder):
            if "symbols.zip" in file.lower() and package_type in file.lower():
                src_zip = os.path.join(parent_folder, file)
                os.makedirs(symbol_folder, exist_ok=True)
                with zipfile.ZipFile(src_zip, 'r') as zip_ref:
                    zip_ref.extractall(symbol_folder)
                log_message(f"Unzipped {file} to {symbol_folder}", color="cyan")
        
        # Handle nameTranslation.txt
        others_path = os.path.join(parent_folder, f"others_{package_type}")
        if os.path.exists(others_path):
            name_translation_file = "nameTranslation.txt"
            src_path = os.path.join(others_path, name_translation_file)
            if os.path.exists(src_path):
                shutil.copy(src_path, os.path.join(local_folder, name_translation_file))
                log_message(f"Copied {name_translation_file} to {local_folder}", color="cyan")
    
    if make_apk_debuggable(local_apk_path):
        log_message(f"APK fetched to {local_folder} and made debuggable!", color="green")
        update_folder_dropdown()
        folder_var.set(f"apks_{timestamp}")
        log_message(f"Current Working Folder: {local_folder}", color="cyan")
    else:
        log_message("Failed to make APK debuggable.", color="red")

def start_button_click():
    start_capture()

def post_process_data():
    global local_folder
    if local_folder is None or not os.path.exists(local_folder):
        log_message("No working folder found. Fetch an APK first.", color="red")
        return False
    
    perf_data_path = os.path.join(local_folder, "perf.data")
    if not os.path.exists(perf_data_path):
        log_message("No perf.data found in the working folder.", color="red")
        return False
    
    try:
        # Step 0: Prepare binary_cache arm64 folder
        binary_cache_base = os.path.join(local_folder, "binary_cache", "data", "app")
        if not os.path.exists(binary_cache_base):
            log_message("binary_cache/data/app not found.", color="red")
            return False
        
        # Only include folders that contain the package_name
        intermediate_folders = [f for f in os.listdir(binary_cache_base) if os.path.isdir(os.path.join(binary_cache_base, f)) and package_name in f]
        if not intermediate_folders:
            log_message(f"No {package_name} folder found in binary_cache/data/app.", color="red")
            return False
        
        latest_intermediate = max(intermediate_folders, key=lambda f: os.path.getmtime(os.path.join(binary_cache_base, f)))
        latest_package_name_path = os.path.join(binary_cache_base, latest_intermediate)
        lib_path = os.path.join(latest_package_name_path, "lib")
        
        # Determine architecture (arm64 or armeabi-v7a)
        arm64_path = os.path.join(lib_path, "arm64")
        armeabi_v7a_path = os.path.join(lib_path, "arm")
        
        if os.path.exists(arm64_path):
            target_path = arm64_path
            symbol_path = os.path.join(local_folder, "Symbol", "arm64-v8a")
            arch = "arm64-v8a"
        elif os.path.exists(armeabi_v7a_path):
            target_path = armeabi_v7a_path
            symbol_path = os.path.join(local_folder, "Symbol", "armeabi-v7a")
            arch = "armeabi-v7a"
        else:
            log_message(f"No arm64 or arm folder found in {lib_path}.", color="red")
            return False
        
        if os.path.exists(target_path):
            # Delete libil2cpp.so and libunity.so if they exist
            for lib in ["libil2cpp.so", "libunity.so"]:
                lib_path = os.path.join(target_path, lib)
                if os.path.exists(lib_path):
                    os.remove(lib_path)
                    log_message(f"Deleted {lib_path}", color="yellow")
            
            if not os.path.exists(symbol_path):
                log_message(f"{symbol_path} not found.", color="red")
                return False
            
            # Copy libil2cpp.so.debug as libil2cpp.so
            src_il2cpp = os.path.join(symbol_path, "libil2cpp.so.debug")
            dst_il2cpp = os.path.join(target_path, "libil2cpp.so")
            if os.path.exists(src_il2cpp):
                shutil.copy(src_il2cpp, dst_il2cpp)
                log_message(f"Copied {src_il2cpp} to {dst_il2cpp}", color="yellow")
            else:
                log_message(f"libil2cpp.so.debug not found in Symbol/{arch}.", color="red")
                return False
            
            # Copy libunity.sym.so as libunity.so
            src_unity = os.path.join(symbol_path, "libunity.sym.so")
            dst_unity = os.path.join(target_path, "libunity.so")
            if os.path.exists(src_unity):
                shutil.copy(src_unity, dst_unity)
                log_message(f"Copied {src_unity} to {dst_unity}", color="yellow")
            else:
                log_message(f"libunity.sym.so not found in Symbol/{arch}.", color="red")
                return False

        
        # Step 1: Generate gecko-profile.json
        gecko_cmd = [
            "python",
            gecko_script,
            "-i", "perf.data",
            "--symfs", r".\binary_cache",
            ">", "gecko-profile.json"
        ]
        # Use shell=True to handle redirection
        subprocess.run(" ".join(gecko_cmd), shell=True, cwd=local_folder, check=True)
        log_message("Generated gecko-profile.json", color="cyan")
        
        timestamp = datetime.now().strftime("%Y%m%d_%H_%M_%S")
        result_folder = os.path.join(local_folder, f"result_{timestamp}")
        os.makedirs(result_folder, exist_ok=True)
        
        # Step 2: Translate symbols in gecko-profile.json
        gecko_file_path = os.path.join(local_folder, "gecko-profile.json")
        translation_file_path = os.path.join(local_folder, "nameTranslation.txt")
        translated_gecko_file_path = os.path.join(result_folder, "gecko-profile-translated.json")

        if not os.path.exists(translation_file_path):
            log_message("nameTranslation.txt not found for translation.", color="red")
            return False

        # Load the name translation table
        translation_dict = {}
        with open(translation_file_path, "r", encoding="utf-8") as f:
            for line in f:
                if "⇨" in line:
                    obfuscated, readable = line.strip().split("⇨")
                    translation_dict[obfuscated] = readable

        # Function to translate obfuscated names
        def translate_symbol(symbol):
            words = symbol.split("_")
            translated_words = [translation_dict.get(word, word) for word in words]
            return "_".join(translated_words)

        # Process all threads in parallel with translated symbols
        def process_thread_with_translation(thread):
            string_table = thread.get("stringTable", [])
            updated_strings = [translate_symbol(entry) for entry in string_table]
            thread["stringTable"] = updated_strings

        with open(gecko_file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            with concurrent.futures.ThreadPoolExecutor() as executor:
                executor.map(process_thread_with_translation, data.get("threads", []))

        # Save the updated JSON and delete origin
        with open(translated_gecko_file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        os.remove(gecko_file_path)

        report_func_cmd = [
            "python",
            report_func,
            "-i", "perf.data",
            "-o", f"{os.path.join(result_folder, 'report.txt')}",
            "-n --full-callgraph",
            "--symfs", r".\binary_cache"
        ]
        subprocess.run(" ".join(report_func_cmd), shell=True, cwd=local_folder, check=True)

        log_message(f"Data post-processing completed! Check {result_folder}", color="green")
        # Open the result folder in Windows Explorer
        try:
            os.startfile(result_folder)
        except Exception as e:
            log_message(f"Failed to open result folder: {e}", color="red")
        return True
    except Exception as e:
        log_message(f"Failed to post-process data: {e}", color="red")
        return False

def list_local_folders():
    results_dir = os.path.join(RUNTIME_DIR, "Results")
    if not os.path.exists(results_dir):
        return []
    return sorted([
        f for f in os.listdir(results_dir)
        if os.path.isdir(os.path.join(results_dir, f)) and f.startswith("apks_")
    ], reverse=True)

def update_folder_dropdown():
    folders = list_local_folders()
    folder_var.set(folders[0] if folders else "")
    folder_dropdown['values'] = folders
    if folders:
        folder_dropdown.current(0)
    else:
        folder_dropdown.set("")

def on_folder_select(event=None):
    global local_folder
    selected = folder_var.get()
    if selected:
        results_dir = os.path.join(RUNTIME_DIR, "Results")
        local_folder = os.path.join(results_dir, selected)
        log_message(f"Selected local folder: {local_folder}", color="cyan")

def install_apk_from_local():
    global local_folder
    if not local_folder or not os.path.exists(local_folder):
        log_message("No local folder selected.", color="red")
        return
    # Find the APK file in the local_folder
    apk_files = [f for f in os.listdir(local_folder) if f.endswith(".apk")]
    if not apk_files:
        log_message("No APK file found in the selected local folder.", color="red")
        return
    apk_path = os.path.join(local_folder, apk_files[0])
    log_message(f"Installing APK: {apk_path}", color="cyan")
    try:
        result = subprocess.run(["adb", "install", "-r", apk_path], capture_output=True, text=True)
        if result.returncode == 0:
            log_message("APK installed successfully!", color="green")
        else:
            log_message(f"Failed to install APK: {result.stderr}", color="red")
    except Exception as e:
        log_message(f"Error running adb install: {e}", color="red")
# Create the main window
window = tk.Tk()
frequency_var = tk.StringVar(value="1000")
# trace_offcpu_var = tk.BooleanVar(value=False)
window.title("Simpleperf Capture Tool")
window.geometry("800x600")  # Larger window size
window.configure(bg="#f0f0f0")  # Light gray background for contrast

# Custom font for better readability
font_large = ("Arial", 12, "bold")
font_medium = ("Arial", 10)

step1_label = tk.Label(window, text="Step 1: Either fetch a new APK or reuse a previous local folder.", font=("Arial", 12, "bold"), bg="#f0f0f0", fg="#AA5500")
step1_label.pack(pady=(20, 5))

# APK path input section (compact)
apk_path_frame = tk.Frame(window, bg="#f0f0f0")
apk_path_frame.pack(pady=10)
tk.Label(apk_path_frame, text="APK Path:", font=font_large, bg="#f0f0f0").pack(side=tk.LEFT, padx=(0, 10))
apk_entry = tk.Entry(apk_path_frame, width=40, font=font_medium)
apk_entry.pack(side=tk.LEFT, padx=(0, 10))

def clear_and_browse_apk():
    apk_entry.delete(0, tk.END)
    path = filedialog.askopenfilename()
    if path:
        apk_entry.insert(0, path)

browse_btn = tk.Button(apk_path_frame, text="Browse", font=font_medium, bg="#d3d3d3", command=clear_and_browse_apk)
browse_btn.pack(side=tk.LEFT)
fetch_btn = tk.Button(apk_path_frame, text="Fetch A Debuggable Apk", font=font_large, bg="#4CAF50", fg="white", width=25, height=2, command=fetch_apk)
fetch_btn.pack(side=tk.LEFT, padx=(10, 0))

# Folder selection frame (reuse UI)
folder_frame = tk.Frame(window, bg="#f0f0f0")
folder_frame.pack(pady=10)
tk.Label(folder_frame, text="Use Local", font=font_large, bg="#f0f0f0").pack(side=tk.LEFT, padx=(0, 10))
folder_var = tk.StringVar()
folder_dropdown = ttk.Combobox(folder_frame, textvariable=folder_var, state="readonly", width=30)
folder_dropdown.pack(side=tk.LEFT, padx=(0, 10))
tk.Button(folder_frame, text="Use Local", font=font_medium, bg="#d3d3d3", command=on_folder_select).pack(side=tk.LEFT)

# Add Install APK button after Use Local
install_btn = tk.Button(folder_frame, text="Install APK", font=font_medium, bg="#8BC34A", fg="white", command=install_apk_from_local)
install_btn.pack(side=tk.LEFT, padx=(10, 0))

# Capture duration and Start Capture (compact)
duration_frame = tk.Frame(window, bg="#f0f0f0")
duration_frame.pack(pady=10)
tk.Label(duration_frame, text="Capture Duration (s):", font=font_large, bg="#f0f0f0").pack(side=tk.LEFT, padx=(0, 10))
duration_entry = tk.Entry(duration_frame, width=8, font=font_medium)
duration_entry.insert(0, "10")
duration_entry.pack(side=tk.LEFT, padx=(0, 10))

# Add frequency dropdown
freq_label = tk.Label(duration_frame, text="Frequency:", font=font_large, bg="#f0f0f0")
freq_label.pack(side=tk.LEFT, padx=(10, 5))
freq_dropdown = ttk.Combobox(duration_frame, textvariable=frequency_var, state="readonly", width=6, font=font_medium)
freq_dropdown['values'] = ("1000", "2000", "3000")
freq_dropdown.current(0)
freq_dropdown.pack(side=tk.LEFT, padx=(0, 10))

# Add --trace-offcpu toggle next to frequency
# trace_offcpu_check = tk.Checkbutton(duration_frame, text="offcpu", variable=trace_offcpu_var, font=font_large, bg="#f0f0f0")
# trace_offcpu_check.pack(side=tk.LEFT, padx=(0, 10))

# Start Capture button
start_btn = tk.Button(duration_frame, text="Start Capture", font=font_large, bg="#2196F3", fg="white", width=18, height=2, command=start_button_click)
start_btn.pack(side=tk.LEFT)

# Post Process Data button
post_btn = tk.Button(window, text="Post Process Data", font=font_large, bg="#FFA500", fg="white", width=25, height=2, command=post_process_data)
post_btn.pack(pady=15)

# Console log (scrollable) - stays at the bottom
console_frame = tk.Frame(window)
console_frame.pack(pady=10, fill=tk.BOTH, expand=True)
console_scrollbar = tk.Scrollbar(console_frame)
console_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
console_log = tk.Text(console_frame, height=12, font=("Consolas", 10), bg="#222", fg="#eee", yscrollcommand=console_scrollbar.set, state=tk.DISABLED)
console_log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
console_scrollbar.config(command=console_log.yview)

def log_message(msg, color=None):
    console_log.config(state=tk.NORMAL)
    start_index = console_log.index(tk.END)
    console_log.insert(tk.END, msg + "\n")
    end_index = console_log.index(tk.END)
    if color:
        console_log.tag_add(color, start_index, f"{end_index}-1c")
        console_log.tag_config(color, foreground=color)
    console_log.see(tk.END)
    console_log.config(state=tk.DISABLED)

# At the end of the UI setup, after all widgets are created, call update_folder_dropdown
update_folder_dropdown()
window.mainloop()

