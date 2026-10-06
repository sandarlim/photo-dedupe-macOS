"""
find_dupes.py - find exact duplicate files (same bytes) in a photo folder.

How to run (in Terminal):
    python3 find_dupes.py "/path/to/Photos"          # report only, changes nothing
    python3 find_dupes.py "/path/to/Photos" --move   # also moves extra copies into Photos/_duplicates

Works on any folder (on your Mac or an external drive), including all its subfolders:
every file is compared against every other file.

Which copy is kept in each group of identical files:
    1. the one with the shorter path
    2. then alphabetical order (just so the choice is always the same)

Skipped: hidden files (._x.jpg, .DS_Store) and the _duplicates folder.
Nothing is ever deleted. --move only moves files into _duplicates so you can check them first.
"""

import hashlib
import os
import sys
from collections import defaultdict
from pathlib import Path

# Where the report is written
REPORT = Path.home() / "Desktop" / "exact_dupes.txt"

# Folders directly inside the photo folder that are never scanned
SKIP_FOLDERS = {"_duplicates"}


def read_arguments():
    """Return (photo folder, move?) from what was typed in Terminal."""
    args = sys.argv[1:]
    move = "--move" in args
    folders = [a for a in args if a != "--move"]
    root = Path(folders[0] if folders else ".").resolve()
    if not root.is_dir():
        sys.exit(f"Folder not found: {root}")
    return root, move


def list_files(root):
    """Every normal file under root. Skips hidden files (._x.jpg, .DS_Store),
    hidden folders, and the top-level folders in SKIP_FOLDERS."""
    for folder, subfolders, files in os.walk(root):
        here = Path(folder)
        # Removing names from subfolders stops os.walk from going into them
        subfolders[:] = [
            name for name in subfolders
            if not name.startswith(".") and not (here == root and name in SKIP_FOLDERS)
        ]
        for name in files:
            path = here / name
            if not name.startswith(".") and path.is_file() and not path.is_symlink():
                yield path


def file_fingerprint(path):
    """MD5 of the file's contents, read in 1 MB chunks so big videos are fine."""
    md5 = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            md5.update(chunk)
    return md5.hexdigest()


def keep_order(path):
    """Sort key: the file that sorts first is the one we keep."""
    return (len(str(path)), str(path))


def main():
    root, move = read_arguments()
    duplicates_folder = root / "_duplicates"

    # Step 1: group files by size. Files of different sizes can't be identical,
    # so this avoids reading most files at all.
    by_size = defaultdict(list)
    count = 0
    for path in list_files(root):
        size = path.stat().st_size
        if size > 0:
            by_size[size].append(path)
        count += 1
        if count % 500 == 0:
            print(f"\rScanned {count} files", end="", file=sys.stderr)
    print(f"\rScanned {count} files. Comparing same-size files...", file=sys.stderr)

    # Step 2: only for sizes shared by 2+ files, compare the actual contents.
    candidates = [paths for paths in by_size.values() if len(paths) > 1]
    total = sum(len(paths) for paths in candidates)
    checked = 0
    groups = []
    for paths in candidates:
        by_fingerprint = defaultdict(list)
        for path in paths:
            checked += 1
            if checked % 25 == 0:
                print(f"\rChecked {checked} / {total}", end="", file=sys.stderr)
            try:
                by_fingerprint[file_fingerprint(path)].append(path)
            except OSError as error:
                print(f"\nCan't read {path}: {error}", file=sys.stderr)
        groups += [same for same in by_fingerprint.values() if len(same) > 1]
    print(f"\rChecked {checked} / {total}", file=sys.stderr)

    # Step 3: in each group, keep one file and list (or move) the rest.
    groups = [sorted(g, key=keep_order) for g in groups]
    groups.sort(key=lambda g: str(g[0]))

    extra_count = 0
    extra_bytes = 0
    with open(REPORT, "w") as report:
        for keep, *extras in groups:
            report.write(f"KEEP   {keep}\n")
            for extra in extras:
                report.write(f"EXTRA  {extra}\n")
                extra_count += 1
                extra_bytes += extra.stat().st_size
                if move:
                    # Same subfolder layout inside _duplicates, e.g. _duplicates/2015-07/IMG_0001.jpg
                    destination = duplicates_folder / extra.relative_to(root)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        extra.rename(destination)
                    except OSError as error:
                        print(f"Couldn't move {extra}: {error}", file=sys.stderr)
            report.write("\n")

    print(f"\n{len(groups)} duplicate groups, {extra_count} extra copies, "
          f"{extra_bytes / 1e9:.2f} GB could be freed.")
    print(f"Report: {REPORT}")
    if move:
        print(f"Extra copies moved to: {duplicates_folder}")
        print("Check it, then delete that folder and empty the Trash.")
    else:
        print("Nothing was changed. Run again with --move to move the extra copies into _duplicates.")


if __name__ == "__main__":
    main()
