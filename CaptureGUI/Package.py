import shutil
import os
import sys
import subprocess
import json

# Paths
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(PROJECT_ROOT, 'dist')
FOLDER_TO_ARCHIVE = os.path.join(DIST_DIR, 'Capture')
ARCHIVE_NAME = os.path.join(DIST_DIR, 'Capture')  # Will become Capture.zip
CONFIG_PATH = os.path.join(PROJECT_ROOT, 'PackageConfig.json')
CAPTURE_PY = os.path.join(PROJECT_ROOT, 'Capture.py')


def load_dest_dir():
    if not os.path.exists(CONFIG_PATH):
        print(f"Config file not found: {CONFIG_PATH}")
        sys.exit(1)
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        config = json.load(f)
    dest_dir = config.get('DEST_DIR')
    if not dest_dir:
        print(f"DEST_DIR not found in config file: {CONFIG_PATH}")
        sys.exit(1)
    return dest_dir

def build_with_pyinstaller():
    print('Building with PyInstaller...')
    result = subprocess.run([
        sys.executable, '-m', 'PyInstaller',
        '--noconfirm', '--add-data', 'deps;deps', CAPTURE_PY
    ], cwd=PROJECT_ROOT)
    if result.returncode != 0:
        print('PyInstaller build failed!')
        sys.exit(1)
    print('PyInstaller build complete.')

def main():
    dest_dir = load_dest_dir()
    build_with_pyinstaller()

    # Remove old archive if exists
    zip_path = ARCHIVE_NAME + '.zip'
    if os.path.exists(zip_path):
        os.remove(zip_path)

    # Create zip archive
    archive_path = shutil.make_archive(ARCHIVE_NAME, 'zip', FOLDER_TO_ARCHIVE)
    print(f"Archive created: {archive_path}")

    # Copy to destination
    dest_path = os.path.join(dest_dir, os.path.basename(archive_path))
    shutil.copy2(archive_path, dest_path)
    print(f"Copied to: {dest_path}")

if __name__ == '__main__':
    main() 