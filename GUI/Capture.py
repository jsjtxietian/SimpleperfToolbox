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

BASE_DIR = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
java_path = os.path.join(BASE_DIR, "deps", "jbr", "bin", "java.exe")
manifest_editor_jar = os.path.join(BASE_DIR, "deps", "other", "ManifestEditor-2.0.jar")
zipalign_path = os.path.join(BASE_DIR, "deps", "other", "zipalign.exe")
apksigner_jar = os.path.join(BASE_DIR, "deps", "other", "apksigner.jar")
gecko_script = os.path.join(BASE_DIR, "deps", "extras", "simpleperf", "scripts", "gecko_profile_generator.py")
app_profiler_script = os.path.join(BASE_DIR, "deps", "ndk", "simpleperf", "app_profiler.py")

# Load config from deps/other/config.json
config_path = os.path.join(BASE_DIR, "deps", "other", "config.json")
with open(config_path, "r", encoding="utf-8") as f:
    config = json.load(f)

keystore_path = os.path.join(BASE_DIR, "deps", "other", config["keystore_file"])
keystore_pass = config["keystore_pass"]
package_name = config["package_name"]

capture_process = None
local_folder = None

def make_apk_debuggable(apk_path):
    log_message(f"Making {apk_path} debuggable...", color="cyan")
    print(f"Making {apk_path} debuggable...")

    base, ext = os.path.splitext(apk_path)
    debuggable_apk = f"{base}_debuggable{ext}"
    aligned_debuggable_apk = f"{base}_aligned_debuggable{ext}"

    # Construct the commands
    command1 = (
        f'{java_path} -jar {manifest_editor_jar} "{apk_path}" '
        f'-o "{debuggable_apk}" -d 1'
    )
    command2 = (
        f'{zipalign_path} 4 "{debuggable_apk}" "{aligned_debuggable_apk}"'
    )
    command3 = (
        f'{java_path} -jar {apksigner_jar} sign '
        f'--v1-signing-enabled --v2-signing-enabled '
        f'--ks {keystore_path} --ks-pass pass:{keystore_pass} '
        f'"{aligned_debuggable_apk}"'
    )

    try:
        subprocess.run(command1, shell=True, check=True)
        subprocess.run(command2, shell=True, check=True)
        subprocess.run(command3, shell=True, check=True)

        if os.path.exists(debuggable_apk):
            os.remove(apk_path)
            os.remove(debuggable_apk)
            log_message(f"Deleted intermediate APK file: {debuggable_apk}", color="green")
        log_message("All commands executed successfully!", color="green")
    except subprocess.CalledProcessError as e:
        log_message(f"Error running command: {e}", color="red")
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
        # Command to start simpleperf
        cmd = [
            "python",
            app_profiler_script,
            "-p", package_name,
            "-r", f"-e cpu-clock -f 1000 --duration {duration} -g"
        ]
        # Start the process, capturing output (optional) and allowing termination
        capture_process = subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_CONSOLE, cwd=local_folder)
        log_message(f"Capture started! Running for {duration} seconds...", color="green")
        return True
    except Exception as e:
        log_message(f"Failed to start capture: {e}", color="red")
        return False

def fetch_apk():
    global local_folder
    apk_path = apk_entry.get()
    if not apk_path or not os.path.exists(apk_path):
        messagebox.showerror("Error", "Please provide a valid APK path.")
        log_message("Error: Please provide a valid APK path.", color="red")
        return
    
    # Define local folder
    timestamp = datetime.now().strftime("%Y%m%d_%H_%M_%S")  # e.g., 20250224_153045
    results_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Results")
    os.makedirs(results_dir, exist_ok=True)  # Ensure Results folder exists
    local_folder = os.path.join(results_dir, f"apks_{timestamp}")
    os.makedirs(local_folder, exist_ok=True)  # Create folder if it doesn't exist
    
    # Get the original APK filename and construct local path
    apk_filename = os.path.basename(apk_path)
    local_apk_path = os.path.join(local_folder, apk_filename)
    
    # Copy APK to local folder
    shutil.copy(apk_path, local_apk_path)

    # Check if the APK comes from an "etc" package and pull additional files
    parent_folder = os.path.dirname(apk_path)  # e.g., before_shell_etc
    grandparent_folder = os.path.dirname(parent_folder)  # e.g., FFO_OB48_...
    log_message(parent_folder, color="cyan")
    
    parent_folder = os.path.dirname(apk_path)
    grandparent_folder = os.path.dirname(parent_folder)
    symbol_folder = os.path.join(local_folder, "Symbol")
    
    package_type = None
    if "etc" in grandparent_folder.lower():
        package_type = "etc"
    elif "astc" in grandparent_folder.lower():
        package_type = "astc"
    
    if package_type:
        # Handle symbols.zip
        for file in os.listdir(grandparent_folder):
            if "symbols.zip" in file.lower() and package_type in file.lower():
                src_zip = os.path.join(grandparent_folder, file)
                os.makedirs(symbol_folder, exist_ok=True)
                with zipfile.ZipFile(src_zip, 'r') as zip_ref:
                    zip_ref.extractall(symbol_folder)
                log_message(f"Unzipped {file} to {symbol_folder}", color="cyan")
        
        # Handle nameTranslation.txt
        others_path = os.path.join(grandparent_folder, f"others_{package_type}")
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
        
        # Find the most recently modified intermediate folder
        intermediate_folders = [f for f in os.listdir(binary_cache_base) if os.path.isdir(os.path.join(binary_cache_base, f))]
        if not intermediate_folders:
            log_message("No intermediate folder found in binary_cache/data/app.", color="red")
            return False
        
        latest_intermediate = max(intermediate_folders, key=lambda f: os.path.getmtime(os.path.join(binary_cache_base, f)))
        intermediate_path = os.path.join(binary_cache_base, latest_intermediate)
        
        # Find the most recently modified folder under the intermediate folder
        app_folders = [f for f in os.listdir(intermediate_path) if package_name in f]
        if not app_folders:
            log_message(f"No {package_name} folder found in binary_cache.", color="red")
            return False
        
        latest_folder = max(app_folders, key=lambda f: os.path.getmtime(os.path.join(intermediate_path, f)))
        lib_path = os.path.join(intermediate_path, latest_folder, "lib")
        
        # Determine architecture (arm64 or armeabi-v7a)
        arm64_path = os.path.join(lib_path, "arm64")
        armeabi_v7a_path = os.path.join(lib_path, "armeabi-v7a")
        
        if os.path.exists(arm64_path):
            target_path = arm64_path
            symbol_path = os.path.join(local_folder, "Symbol", "arm64-v8a")
            arch = "arm64-v8a"
        elif os.path.exists(armeabi_v7a_path):
            target_path = armeabi_v7a_path
            symbol_path = os.path.join(local_folder, "Symbol", "armeabi-v7a")
            arch = "armeabi-v7a"
        else:
            log_message("No arm64 or armeabi-v7a folder found in lib.", color="red")
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
        
        # Step 2: Translate symbols in gecko-profile.json
        file_path = os.path.join(local_folder, "gecko-profile.json")
        translation_file_path = os.path.join(local_folder, "nameTranslation.txt")
        translated_file_path = os.path.join(local_folder, "gecko-profile-translated.json")

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

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            with concurrent.futures.ThreadPoolExecutor() as executor:
                executor.map(process_thread_with_translation, data.get("threads", []))

        # Save the updated JSON
        with open(translated_file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)

        # Step 3: Zip the translated JSON
        zip_path = os.path.join(local_folder, "gecko-profile-translated.zip")
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zipf.write(translated_file_path, os.path.basename(translated_file_path))

        log_message("Data post-processing completed! Zipped to gecko-profile-translated.zip", color="green")
        return True
    except Exception as e:
        log_message(f"Failed to post-process data: {e}", color="red")
        return False

def list_local_folders():
    results_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Results")
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
        results_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Results")
        local_folder = os.path.join(results_dir, selected)
        log_message(f"Selected local folder: {local_folder}", color="cyan")

# Create the main window
window = tk.Tk()
window.title("Simpleperf Capture Tool")
window.geometry("600x600")  # Larger window size
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
tk.Button(apk_path_frame, text="Browse", font=font_medium, bg="#d3d3d3", command=lambda: apk_entry.insert(0, filedialog.askopenfilename())).pack(side=tk.LEFT)

# Fetch & Make Debuggable button
fetch_btn = tk.Button(window, text="Fetch & Make Debuggable", font=font_large, bg="#4CAF50", fg="white", width=25, height=2, command=fetch_apk)
fetch_btn.pack(pady=10)

# Folder selection frame (reuse UI)
folder_frame = tk.Frame(window, bg="#f0f0f0")
folder_frame.pack(pady=10)
tk.Label(folder_frame, text="Use Local", font=font_large, bg="#f0f0f0").pack(side=tk.LEFT, padx=(0, 10))
folder_var = tk.StringVar()
folder_dropdown = ttk.Combobox(folder_frame, textvariable=folder_var, state="readonly", width=30)
folder_dropdown.pack(side=tk.LEFT, padx=(0, 10))
tk.Button(folder_frame, text="Use Local", font=font_medium, bg="#d3d3d3", command=on_folder_select).pack(side=tk.LEFT)

# Capture duration and Start Capture (compact)
duration_frame = tk.Frame(window, bg="#f0f0f0")
duration_frame.pack(pady=10)
tk.Label(duration_frame, text="Capture Duration (seconds):", font=font_large, bg="#f0f0f0").pack(side=tk.LEFT, padx=(0, 10))
duration_entry = tk.Entry(duration_frame, width=8, font=font_medium)
duration_entry.insert(0, "600")
duration_entry.pack(side=tk.LEFT, padx=(0, 10))
tk.Button(duration_frame, text="Start Capture", font=font_large, bg="#2196F3", fg="white", width=18, height=2, command=start_button_click).pack(side=tk.LEFT)

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
