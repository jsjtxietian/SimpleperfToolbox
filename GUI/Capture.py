import tkinter as tk
from tkinter import filedialog, messagebox
import os
import shutil
import subprocess
import argparse
import signal
from datetime import datetime
import zipfile
import json
import concurrent.futures
import sys

capture_process = None
local_folder = None

BASE_DIR = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))

# adjust these paths if needed
java_path = os.path.join(BASE_DIR, "deps", "jbr", "bin", "java.exe")
manifest_editor_jar = os.path.join(BASE_DIR, "deps", "other", "ManifestEditor-2.0.jar")
zipalign_path = os.path.join(BASE_DIR, "deps", "other", "zipalign.exe")
apksigner_jar = os.path.join(BASE_DIR, "deps", "other", "apksigner.jar")

# Load config from deps/other/config.json
config_path = os.path.join(BASE_DIR, "deps", "other", "config.json")
with open(config_path, "r", encoding="utf-8") as f:
    config = json.load(f)

keystore_path = os.path.join(BASE_DIR, "deps", "other", config["keystore_file"])
keystore_pass = config["keystore_pass"]

gecko_script = os.path.join(BASE_DIR, "deps", "extras", "simpleperf", "scripts", "gecko_profile_generator.py")
app_profiler_script = os.path.join(BASE_DIR, "deps", "ndk", "simpleperf", "app_profiler.py")

package_name = config["package_name"]

def make_apk_debuggable(apk_path):
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
            status_label.config(text=f"Deleted intermediate APK file: {debuggable_apk}", fg="green")

        print("All commands executed successfully!")
    except subprocess.CalledProcessError as e:
        # print("An error occurred while running one of the commands:")
        print(e)

    return True

def start_capture():
    global capture_process
    global local_folder
    if local_folder is None:
        print("Please fetch an APK first to create a working folder.")
        return False
    try:
        duration = duration_entry.get()
        if not duration.isdigit() or int(duration) <= 0:
            print("Please enter a valid positive number for duration.")
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
        status_label.config(text=f"Capture started! Running for {duration} seconds...", fg="green")
        return True
    except Exception as e:
        print(e)
        status_label.config(text=f"Failed to start capture: {e}", fg="red")
        return False

def fetch_apk():
    global local_folder
    apk_path = apk_entry.get()
    if not apk_path or not os.path.exists(apk_path):
        messagebox.showerror("Error", "Please provide a valid APK path.")
        return
    
    # Define local folder
    timestamp = datetime.now().strftime("%Y%m%d_%H_%M_%S")  # e.g., 20250224_153045
    local_folder = f"apks_{timestamp}"
    os.makedirs(local_folder, exist_ok=True)  # Create folder if it doesn't exist
    
    # Get the original APK filename and construct local path
    apk_filename = os.path.basename(apk_path)
    local_apk_path = os.path.join(local_folder, apk_filename)
    
    # Copy APK to local folder
    shutil.copy(apk_path, local_apk_path)

    # Check if the APK comes from an "etc" package and pull additional files
    parent_folder = os.path.dirname(apk_path)  # e.g., before_shell_etc
    grandparent_folder = os.path.dirname(parent_folder)  # e.g., FFO_OB48_...
    print(parent_folder)
    
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
                print(f"Unzipped {file} to {symbol_folder}")
        
        # Handle nameTranslation.txt
        others_path = os.path.join(grandparent_folder, f"others_{package_type}")
        if os.path.exists(others_path):
            name_translation_file = "nameTranslation.txt"
            src_path = os.path.join(others_path, name_translation_file)
            if os.path.exists(src_path):
                shutil.copy(src_path, os.path.join(local_folder, name_translation_file))
                print(f"Copied {name_translation_file} to {local_folder}")
    
    if make_apk_debuggable(local_apk_path):
        status_label.config(text=f"APK fetched to {local_folder} and made debuggable!", fg="green")
    else:
        status_label.config(text="Failed to make APK debuggable.", fg="red")

def start_button_click():
    start_capture()

def post_process_data():
    global local_folder
    if local_folder is None or not os.path.exists(local_folder):
        status_label.config(text="No working folder found. Fetch an APK first.", fg="red")
        return False
    
    perf_data_path = os.path.join(local_folder, "perf.data")
    if not os.path.exists(perf_data_path):
        status_label.config(text="No perf.data found in the working folder.", fg="red")
        return False
    
    try:
        # Step 0: Prepare binary_cache arm64 folder
        binary_cache_base = os.path.join(local_folder, "binary_cache", "data", "app")
        if not os.path.exists(binary_cache_base):
            status_label.config(text="binary_cache\data\app not found.", fg="red")
            return False
        
        # Find the most recently modified intermediate folder
        intermediate_folders = [f for f in os.listdir(binary_cache_base) if os.path.isdir(os.path.join(binary_cache_base, f))]
        if not intermediate_folders:
            status_label.config(text="No intermediate folder found in binary_cache\data\app.", fg="red")
            return False
        
        latest_intermediate = max(intermediate_folders, key=lambda f: os.path.getmtime(os.path.join(binary_cache_base, f)))
        intermediate_path = os.path.join(binary_cache_base, latest_intermediate)
        
        # Find the most recently modified folder under the intermediate folder
        app_folders = [f for f in os.listdir(intermediate_path) if package_name in f]
        if not app_folders:
            status_label.config(text=f"No {package_name} folder found in binary_cache.", fg="red")
            return False
        
        latest_folder = max(app_folders, key=lambda f: os.path.getmtime(os.path.join(intermediate_path, f)))
        lib_path = os.path.join(intermediate_path, latest_folder, "lib")
        
        # Determine architecture (arm64 or armeabi-v7a)
        arm64_path = os.path.join(lib_path, "arm64")
        armeabi_v7a_path = os.path.join(lib_path, "armeabi-v7a")
        
        if os.path.exists(arm64_path):
            target_path = arm64_path
            symbol_path = os.path.join(local_folder, "Symbol", "arm64-v8a")
        elif os.path.exists(armeabi_v7a_path):
            target_path = armeabi_v7a_path
            symbol_path = os.path.join(local_folder, "Symbol", "armeabi-v7a")
        else:
            status_label.config(text="No arm64 or armeabi-v7a folder found in lib.", fg="red")
            return False
        
        if os.path.exists(target_path):
            # Delete libil2cpp.so and libunity.so if they exist
            for lib in ["libil2cpp.so", "libunity.so"]:
                lib_path = os.path.join(target_path, lib)
                if os.path.exists(lib_path):
                    os.remove(lib_path)
                    print(f"Deleted {lib_path}")
            
            if not os.path.exists(symbol_path):
                status_label.config(text=f"{symbol_path} not found.", fg="red")
                return False
            
            # Copy libil2cpp.so.debug as libil2cpp.so
            src_il2cpp = os.path.join(symbol_path, "libil2cpp.so.debug")
            dst_il2cpp = os.path.join(target_path, "libil2cpp.so")
            if os.path.exists(src_il2cpp):
                shutil.copy(src_il2cpp, dst_il2cpp)
                print(f"Copied {src_il2cpp} to {dst_il2cpp}")
            else:
                status_label.config(text=f"libil2cpp.so.debug not found in Symbol\{arch}.", fg="red")
                return False
            
            # Copy libunity.sym.so as libunity.so
            src_unity = os.path.join(symbol_path, "libunity.sym.so")
            dst_unity = os.path.join(target_path, "libunity.so")
            if os.path.exists(src_unity):
                shutil.copy(src_unity, dst_unity)
                print(f"Copied {src_unity} to {dst_unity}")
            else:
                status_label.config(text=f"libunity.sym.so not found in Symbol\{arch}.", fg="red")
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
        
        # Step 2: Translate symbols in gecko-profile.json
        file_path = os.path.join(local_folder, "gecko-profile.json")
        translation_file_path = os.path.join(local_folder, "nameTranslation.txt")
        translated_file_path = os.path.join(local_folder, "gecko-profile-translated.json")

        if not os.path.exists(translation_file_path):
            status_label.config(text="nameTranslation.txt not found for translation.", fg="red")
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

        status_label.config(text="Data post-processing completed! Zipped to gecko-profile-translated.zip", fg="green")
        return True
    except Exception as e:
        status_label.config(text=f"Failed to post-process data: {e}", fg="red")
        return False

# Create the main window
window = tk.Tk()
window.title("Simpleperf Capture Tool")
window.geometry("600x600")  # Larger window size
window.configure(bg="#f0f0f0")  # Light gray background for contrast

# Custom font for better readability
font_large = ("Arial", 12, "bold")
font_medium = ("Arial", 10)

# APK path input section
tk.Label(window, text="APK Path:", font=font_large, bg="#f0f0f0").pack(pady=10)
apk_entry = tk.Entry(window, width=50, font=font_medium)
apk_entry.pack(pady=5)
tk.Button(window, text="Browse", font=font_medium, bg="#d3d3d3", command=lambda: apk_entry.insert(0, filedialog.askopenfilename())).pack(pady=5)


# Status label with larger font and color feedback
status_label = tk.Label(window, text="Ready", font=font_large, bg="#f0f0f0", fg="black")
status_label.pack(pady=30)

# Buttons with distinct colors and sizes
tk.Button(window, text="Fetch & Make Debuggable", font=font_large, bg="#4CAF50", fg="white", width=25, height=2, command=fetch_apk).pack(pady=20)


# Capture duration input section
tk.Label(window, text="Capture Duration (seconds):", font=font_large, bg="#f0f0f0").pack(pady=10)
duration_entry = tk.Entry(window, width=10, font=font_medium)
duration_entry.insert(0, "600")  # Default value of 600 seconds
duration_entry.pack(pady=5)
tk.Button(window, text="Start Capture", font=font_large, bg="#2196F3", fg="white", width=25, height=2, command=start_button_click).pack(pady=20)
# tk.Button(window, text="End Capture", font=font_large, bg="#F44336", fg="white", width=25, height=2, command=end_button_click).pack(pady=20)
tk.Button(window, text="Post Process Data", font=font_large, bg="#FFA500", fg="white", 
          width=25, height=2, command=post_process_data).pack(pady=20)

# Start the GUI
window.mainloop()


# def end_capture():
#     global capture_process
#     if capture_process is not None:
#         try:
#             # Step 1: Signal simpleperf on the device to stop (mimicking app_profiler.py)
#             adb_path = "adb"  # Assumes adb is in PATH; adjust if needed
#             subprocess.run([adb_path, "shell", "pkill", "-l", "2", "simpleperf"], check=False)
            
#             # Step 2: Wait briefly for simpleperf to stop and adb to exit
#             time.sleep(1)
            
#             # Step 3: Check if simpleperf is still running on device
#             result = subprocess.run([adb_path, "shell", "pidof", "simpleperf"], 
#                                   capture_output=True, text=True)
#             if result.stdout.strip():
#                 status_label.config(text="Warning: simpleperf still running on device.", fg="orange")
            
#             # Step 4: Kill the app_profiler.py process and its children
#             parent = psutil.Process(capture_process.pid)
#             for child in parent.children(recursive=True):
#                 child.kill()  # Kill adb and any other children
#             parent.kill()  # Kill app_profiler.py
#             capture_process.wait(timeout=5)  # Wait for process to exit
            
#             # Step 5: Double-check and kill any lingering adb processes
#             for proc in psutil.process_iter(['pid', 'name']):
#                 if proc.info['name'] == 'adb.exe' and proc.is_running():
#                     try:
#                         proc.kill()
#                     except psutil.NoSuchProcess:
#                         pass
            
#             status_label.config(text="Capture ended! All processes terminated.", fg="green")
#             capture_process = None
#             return True
#         except Exception as e:
#             status_label.config(text=f"Failed to end capture: {e}", fg="red")
#             return False
#     else:
#         status_label.config(text="No capture process running.", fg="red")
#         return False


# def end_button_click():
#     if end_capture():
#         status_label.config(text="Capture ended and data processed!", fg="green")
#     else:
#         status_label.config(text="Failed to end capture.", fg="red")
