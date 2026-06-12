# Photo Deduper

A macOS desktop app that scans your **Photos library**, finds duplicate and
near-duplicate images using perceptual hashing, and lets you review and delete
them through a clean GUI — without ever touching the library files directly.

---

## Screenshots

| Duplicate group view | Mark & delete |
|---|---|
| Side-by-side photo cards with metadata | Checkbox to mark, confirmation dialog before any deletion |

---

## Features

- **Perceptual hash duplicate detection** — catches re-saved, resized, and
  slightly edited copies, not just byte-for-byte duplicates
- **Side-by-side comparison** — see each photo in the group with filename,
  date, resolution, and file size at a glance
- **Click to preview** — click any thumbnail for a full-size preview window
- **Smart auto-mark** — "Mark all duplicates" keeps the largest file (usually
  the original) and marks the rest
- **Safe deletion via AppleScript** — photos go to the Photos *Recently Deleted*
  album (recoverable for 30 days), never directly removed from disk
- **iCloud aware** — photos not downloaded locally show a placeholder; only
  local files are hashed and previewed
- **Rescan** — re-run detection at any time without restarting the app

---

## Requirements

- macOS 12 Monterey or later
- Python 3.9+
- Photos app with an existing library

---

## Installation

```bash
git clone https://github.com/robzarry/photo-deduper.git
cd photo-deduper
bash setup.sh
```

`setup.sh` installs three packages (`osxphotos`, `imagehash`, `Pillow`) and
verifies that Tkinter is available.

---

## Running

```bash
python3 photo_deduper.py
```

On first launch macOS will prompt for **Photos access** — grant it in
System Settings → Privacy & Security → Photos.

### Workflow

1. The app scans your library and hashes all locally-available photos
2. Duplicate groups appear in the left panel
3. Click a group to see all photos side by side
4. Check individual photos or use **"Mark all duplicates"** (keeps the largest)
5. When ready, click **"Delete Marked"** — a confirmation dialog lists every
   photo about to be deleted
6. Deleted photos move to Photos → Recently Deleted (30-day recovery window)

---

## How duplicates are detected

Each photo is run through a **perceptual hash** (`phash`, 16-bit). Two photos
are considered duplicates if their hash distance is ≤ 6 (configurable via
`HASH_THRESH` in the source). This catches:

- Identical copies
- Re-saved JPEGs at different quality settings
- Lightly edited versions (brightness, crop, minor colour correction)

It will **not** catch heavily edited photos or different shots of the same
subject.

---

## Privacy & Safety

- The app reads the Photos library **read-only** via `osxphotos`
- Deletion goes through the **Photos AppleScript API** — the library database
  is never modified directly
- No photos, metadata, or hashes leave your machine
- Deleted photos are **recoverable** from Photos → Recently Deleted for 30 days

---

## Tuning sensitivity

In `photo_deduper.py`:

```python
HASH_BITS   = 16   # larger = finer hash = catches subtler dupes (slower)
HASH_THRESH = 6    # max hamming distance; lower = stricter matching
```

| `HASH_THRESH` | Effect |
|---|---|
| 0–2 | Near-identical only (different JPEG saves) |
| 3–6 | Default — catches most practical duplicates |
| 8–12 | Aggressive — may match different photos of same scene |

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| "Could not open Photos library" | Grant Photos access: System Settings → Privacy → Photos → Terminal |
| Thumbnails all show "No preview" | Photos are stored in iCloud and not downloaded — open Photos and download them first |
| AppleScript deletion fails | Make sure Photos app is not locked / in a modal dialog |
| `imagehash` not found | Run `bash setup.sh` or `pip3 install imagehash` |
| Tkinter not found | `brew install python-tk@3.x` or use the python.org installer |
