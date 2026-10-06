# photo-dedupe-mac

Find and clean up duplicate photos in a folder on your Mac or an external drive: exact copies,
and lower-resolution copies of the same photo. Every photo in every subfolder is compared
against every other one. Runs on macOS with no Homebrew needed (works on Intel Macs).

Nothing is ever deleted by these scripts. Unwanted copies are **moved** into a `_duplicates`
folder inside your photo folder, so you can check them before deleting.

## What's here

| File | What it does |
|---|---|
| `find_dupes.py` | Finds byte-identical files. Keeps one copy of each, moves the rest. |
| `scan_similar.sh` | Runs [Czkawka](https://github.com/qarmin/czkawka) to find visually similar photos (resized copies, bursts). Downloads it the first time. |
| `review_similar.py` | Opens Czkawka's report as a page in Chrome: photos side by side, sensible pre-ticks, one-click move. |

Requirements: macOS with `python3` (if macOS offers to install the command line developer
tools the first time, click Install). Python standard library only, no `pip install`.

## Workflow

Set your photo folder once per Terminal session (keep the quotes if the path has spaces):

```bash
PHOTOS="$HOME/Pictures/Photos"           # a folder on your Mac
PHOTOS="/Volumes/MyDrive/Photos"         # or a folder on an external drive
```

### 1. Exact duplicates

```bash
python3 find_dupes.py "$PHOTOS"          # report only: ~/Desktop/exact_dupes.txt
python3 find_dupes.py "$PHOTOS" --move   # move extra copies into $PHOTOS/_duplicates
```

Which copy is kept: the one with the shorter path, then the first alphabetically.
Hidden files (`._*`, `.DS_Store`) are ignored.

### 2. Similar photos

```bash
./scan_similar.sh "$PHOTOS"              # report: ~/Desktop/similar_photos.txt
```

Strictness is an optional second argument: `VeryHigh` mostly finds the same photo saved at
a different size; `High` (default) also groups near-identical bursts; `Medium` and below
group photos that just look alike. Cropped or rotated copies usually aren't detected.

HEIC files are skipped by this Czkawka build.

### 3. Review and move

```bash
python3 review_similar.py ~/Desktop/similar_photos.txt "$PHOTOS"
```

Chrome opens the review page (the default browser if Chrome isn't installed). Keep the
Terminal window open while reviewing; press Control+C when done.

Every group keeps one photo by default and the rest are ticked:

1. **Smaller copy**: lower resolution than the biggest photo in the group
2. **Exact copy**: byte-identical to another largest-size photo (the one with the shorter path is kept)
3. **Similar, same size**: e.g. bursts. One **Suggested keep** (the biggest file)

The suggestion can't tell whose eyes are closed, so use **Keep only this one** on the photo
you prefer. Then click **Move ticked to _duplicates**.

### 4. Delete

Check `$PHOTOS/_duplicates` in Finder, move it to the Trash, and empty the Trash. For an
external drive, keep it connected while emptying the Trash; the space is only freed then.

## Notes

- Run on the whole photo folder so all photos in subfolders are compared.
- The `_duplicates` folder is skipped by all scans.
- If Terminal says "Operation not permitted", give Terminal access under
  System Settings → Privacy & Security → Full Disk Access (or Files and Folders → Removable Volumes
  for an external drive).
- If macOS blocks the Czkawka download, allow it under System Settings → Privacy & Security → Open Anyway.
