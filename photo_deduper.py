#!/usr/bin/env python3
"""
photo_deduper.py — macOS Photos Library Duplicate Finder & Cleaner

Scans your Photos library using osxphotos, finds duplicates via
perceptual hashing (imagehash), and presents them in a Tkinter GUI
for review and deletion through AppleScript.
"""

import os
import sys
import threading
import subprocess
import hashlib
import datetime
import pathlib
import tkinter as tk
from tkinter import ttk, messagebox, font as tkfont
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Dependency checks
# ---------------------------------------------------------------------------
def _require(pkg, install):
    import importlib
    try:
        return importlib.import_module(pkg)
    except ImportError:
        print(f"Missing package '{pkg}'. Install with: {install}")
        sys.exit(1)

osxphotos  = _require("osxphotos",  "pip install osxphotos")
imagehash  = _require("imagehash",  "pip install imagehash")
PIL        = _require("PIL",        "pip install Pillow")

from PIL import Image, ImageTk, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Colours & constants
# ---------------------------------------------------------------------------
BG          = "#1e1e2e"
BG_PANEL    = "#2a2a3e"
BG_HOVER    = "#313145"
BG_SELECTED = "#3b3b5c"
ACCENT      = "#cba6f7"   # mauve
ACCENT2     = "#89b4fa"   # blue
RED         = "#f38ba8"
GREEN       = "#a6e3a1"
SUBTEXT     = "#6c7086"
TEXT        = "#cdd6f4"
TEXT_DIM    = "#9399b2"

THUMB_SIZE  = (220, 220)
PREVIEW_MAX = (520, 520)
HASH_BITS   = 16          # larger = more sensitive (catches subtler dupes)
HASH_THRESH = 6           # max hamming distance to call two images duplicates

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class PhotoRecord:
    uuid:         str
    filename:     str
    path:         Optional[str]      # may be None if not downloaded from iCloud
    date:         Optional[datetime.datetime]
    file_size:    int                # bytes
    width:        int
    height:       int
    phash:        Optional[object]   # imagehash.ImageHash or None
    marked:       bool = False       # user has marked this for deletion

    @property
    def megapixels(self) -> str:
        mp = (self.width * self.height) / 1_000_000
        return f"{mp:.1f} MP"

    @property
    def size_str(self) -> str:
        if self.file_size >= 1_048_576:
            return f"{self.file_size / 1_048_576:.1f} MB"
        return f"{self.file_size / 1024:.0f} KB"

    @property
    def date_str(self) -> str:
        if self.date:
            return self.date.strftime("%b %d, %Y  %H:%M")
        return "Unknown date"


DuplicateGroup = list[PhotoRecord]


# ---------------------------------------------------------------------------
# Library scanning & duplicate detection
# ---------------------------------------------------------------------------

def load_library(progress_cb=None) -> list[PhotoRecord]:
    """Load all photos from the default Photos library via osxphotos."""
    db = osxphotos.PhotosDB()
    photos = db.photos(movies=False)
    records = []
    total = len(photos)
    for i, p in enumerate(photos):
        if progress_cb and i % 50 == 0:
            progress_cb(i, total, f"Loading photo {i:,} / {total:,}")
        path = None
        try:
            path = p.path  # None if iCloud-only and not downloaded
        except Exception:
            pass
        rec = PhotoRecord(
            uuid=p.uuid,
            filename=p.filename or "",
            path=path,
            date=p.date,
            file_size=p.file_size or 0,
            width=p.width or 0,
            height=p.height or 0,
            phash=None,
        )
        records.append(rec)
    if progress_cb:
        progress_cb(total, total, f"Loaded {total:,} photos")
    return records


def compute_hashes(records: list[PhotoRecord], progress_cb=None) -> None:
    """Compute perceptual hashes in-place for photos that have a local path."""
    hashable = [r for r in records if r.path and os.path.exists(r.path)]
    total = len(hashable)
    for i, rec in enumerate(hashable):
        if progress_cb and i % 20 == 0:
            progress_cb(i, total, f"Hashing {i:,} / {total:,}")
        try:
            img = Image.open(rec.path).convert("RGB")
            rec.phash = imagehash.phash(img, hash_size=HASH_BITS)
        except Exception:
            pass
    if progress_cb:
        progress_cb(total, total, "Hashing complete")


def find_duplicates(records: list[PhotoRecord]) -> list[DuplicateGroup]:
    """
    Group photos into duplicate clusters using perceptual hash similarity.
    Uses a union-find so transitive similarity is handled correctly.
    """
    hashed = [r for r in records if r.phash is not None]

    # Union-Find
    parent = {r.uuid: r.uuid for r in hashed}
    by_uuid = {r.uuid: r for r in hashed}

    def find(u):
        while parent[u] != u:
            parent[u] = parent[parent[u]]
            u = parent[u]
        return u

    def union(u, v):
        pu, pv = find(u), find(v)
        if pu != pv:
            parent[pu] = pv

    # O(n²) comparison — fine up to ~20k photos; add BK-tree if needed
    for i, a in enumerate(hashed):
        for b in hashed[i + 1:]:
            if abs(a.phash - b.phash) <= HASH_THRESH:
                union(a.uuid, b.uuid)

    clusters: dict[str, list[PhotoRecord]] = defaultdict(list)
    for r in hashed:
        clusters[find(r.uuid)].append(r)

    groups = [g for g in clusters.values() if len(g) > 1]

    # Sort each group: larger file first (usually the original)
    for g in groups:
        g.sort(key=lambda r: r.file_size, reverse=True)

    # Sort groups by date of first photo
    groups.sort(key=lambda g: g[0].date or datetime.datetime.min)
    return groups


# ---------------------------------------------------------------------------
# AppleScript deletion
# ---------------------------------------------------------------------------

def delete_photos_applescript(uuids: list[str]) -> tuple[bool, str]:
    """
    Delete photos from the Photos library via AppleScript.
    Photos must be running (or will be launched).
    Returns (success, message).
    """
    if not uuids:
        return True, "Nothing to delete."

    # Build a comma-separated list of quoted UUIDs for the script
    uuid_list = ", ".join(f'"{u}"' for u in uuids)

    script = f"""
tell application "Photos"
    set targetUUIDs to {{{uuid_list}}}
    set toDelete to {{}}
    repeat with u in targetUUIDs
        try
            set toDelete to toDelete & (media item id u)
        end try
    end repeat
    if (count of toDelete) > 0 then
        delete toDelete
    end if
    return (count of toDelete) as string
end tell
"""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0:
            n = result.stdout.strip()
            return True, f"Deleted {n} photo(s) from Photos library."
        else:
            return False, result.stderr.strip() or "AppleScript error."
    except subprocess.TimeoutExpired:
        return False, "Timed out waiting for Photos app."
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# Thumbnail helpers
# ---------------------------------------------------------------------------

def load_thumbnail(path: str, size=THUMB_SIZE) -> Optional[ImageTk.PhotoImage]:
    try:
        img = Image.open(path).convert("RGB")
        img.thumbnail(size, Image.LANCZOS)
        return ImageTk.PhotoImage(img)
    except Exception:
        return None


def load_preview(path: str, max_size=PREVIEW_MAX) -> Optional[ImageTk.PhotoImage]:
    try:
        img = Image.open(path).convert("RGB")
        img.thumbnail(max_size, Image.LANCZOS)
        return ImageTk.PhotoImage(img)
    except Exception:
        return None


def placeholder_image(size, text="No preview", bg="#2a2a3e", fg="#6c7086"):
    img = Image.new("RGB", size, bg)
    try:
        draw = ImageDraw.Draw(img)
        draw.text((size[0]//2, size[1]//2), text, fill=fg, anchor="mm")
    except Exception:
        pass
    return ImageTk.PhotoImage(img)


# ---------------------------------------------------------------------------
# Styled widget helpers
# ---------------------------------------------------------------------------

def styled_button(parent, text, command, color=ACCENT, **kw):
    btn = tk.Button(
        parent, text=text, command=command,
        bg=color, fg=BG, relief="flat", cursor="hand2",
        font=("SF Pro Display", 12, "bold"),
        padx=14, pady=6, **kw
    )
    btn.bind("<Enter>", lambda e: btn.config(bg=_lighten(color)))
    btn.bind("<Leave>", lambda e: btn.config(bg=color))
    return btn


def _lighten(hex_color: str) -> str:
    r, g, b = int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)
    r = min(255, r + 30)
    g = min(255, g + 30)
    b = min(255, b + 30)
    return f"#{r:02x}{g:02x}{b:02x}"


# ---------------------------------------------------------------------------
# Main Application Window
# ---------------------------------------------------------------------------

class PhotoDeduper(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("Photo Deduper")
        self.geometry("1280x820")
        self.minsize(960, 640)
        self.configure(bg=BG)

        # State
        self.all_records:    list[PhotoRecord]    = []
        self.groups:         list[DuplicateGroup] = []
        self.current_group:  Optional[int]        = None
        self._thumb_cache:   dict[str, ImageTk.PhotoImage] = {}
        self._preview_cache: dict[str, ImageTk.PhotoImage] = {}
        self._scanning       = False

        self._build_ui()
        self.after(200, self._start_scan)

    # ── UI construction ───────────────────────────────────────────────────

    def _build_ui(self):
        # ── Top bar ──────────────────────────────────────────────────────
        top = tk.Frame(self, bg=BG, pady=10, padx=16)
        top.pack(fill="x")

        tk.Label(top, text="📷  Photo Deduper", bg=BG, fg=ACCENT,
                 font=("SF Pro Display", 20, "bold")).pack(side="left")

        self.status_var = tk.StringVar(value="Initialising…")
        tk.Label(top, textvariable=self.status_var, bg=BG, fg=TEXT_DIM,
                 font=("SF Pro Text", 12)).pack(side="left", padx=20)

        self.btn_rescan = styled_button(top, "⟳  Rescan", self._start_scan, color=ACCENT2)
        self.btn_rescan.pack(side="right")

        self.btn_delete = styled_button(
            top, "🗑  Delete Marked", self._delete_marked, color=RED
        )
        self.btn_delete.pack(side="right", padx=8)
        self.btn_delete.config(state="disabled")

        self.marked_var = tk.StringVar(value="0 marked")
        tk.Label(top, textvariable=self.marked_var, bg=BG, fg=RED,
                 font=("SF Pro Text", 12, "bold")).pack(side="right", padx=4)

        # ── Progress bar (hidden after scan) ─────────────────────────────
        self.progress_frame = tk.Frame(self, bg=BG)
        self.progress_frame.pack(fill="x", padx=16)
        self.progress = ttk.Progressbar(self.progress_frame, mode="determinate")
        self.progress.pack(fill="x")
        self.progress_label = tk.Label(self.progress_frame, text="", bg=BG, fg=TEXT_DIM,
                                       font=("SF Pro Text", 11))
        self.progress_label.pack(anchor="w")

        ttk.Style().configure("TProgressbar", troughcolor=BG_PANEL,
                              background=ACCENT, thickness=6)

        # ── Main pane ────────────────────────────────────────────────────
        pane = tk.PanedWindow(self, orient="horizontal", bg=BG,
                              sashwidth=6, sashrelief="flat",
                              handlesize=0)
        pane.pack(fill="both", expand=True, padx=0, pady=0)

        # Left: group list
        left = tk.Frame(pane, bg=BG_PANEL, width=280)
        pane.add(left, minsize=200)

        tk.Label(left, text="Duplicate Groups", bg=BG_PANEL, fg=ACCENT,
                 font=("SF Pro Text", 13, "bold"), pady=10).pack(fill="x", padx=12)

        self.group_list = tk.Listbox(
            left, bg=BG_PANEL, fg=TEXT, selectbackground=BG_SELECTED,
            selectforeground=ACCENT, font=("SF Mono", 12), relief="flat",
            highlightthickness=0, activestyle="none", cursor="hand2"
        )
        scroll_left = ttk.Scrollbar(left, orient="vertical",
                                    command=self.group_list.yview)
        self.group_list.config(yscrollcommand=scroll_left.set)
        scroll_left.pack(side="right", fill="y")
        self.group_list.pack(fill="both", expand=True, padx=4, pady=4)
        self.group_list.bind("<<ListboxSelect>>", self._on_group_select)

        # Right: comparison view
        right = tk.Frame(pane, bg=BG)
        pane.add(right, minsize=500)

        self.comparison_frame = tk.Frame(right, bg=BG)
        self.comparison_frame.pack(fill="both", expand=True)

        self._show_welcome()

    # ── Welcome / empty state ─────────────────────────────────────────────

    def _show_welcome(self):
        for w in self.comparison_frame.winfo_children():
            w.destroy()
        tk.Label(
            self.comparison_frame,
            text="Scanning your Photos library…\nThis may take a few minutes.",
            bg=BG, fg=TEXT_DIM,
            font=("SF Pro Text", 16), justify="center"
        ).place(relx=0.5, rely=0.5, anchor="center")

    # ── Scanning ──────────────────────────────────────────────────────────

    def _start_scan(self):
        if self._scanning:
            return
        self._scanning = True
        self.btn_rescan.config(state="disabled")
        self.btn_delete.config(state="disabled")
        self.group_list.delete(0, "end")
        self.groups = []
        self.current_group = None
        self._thumb_cache.clear()
        self._preview_cache.clear()
        self._show_welcome()
        self.progress_frame.pack(fill="x", padx=16)
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self):
        def prog(n, total, msg):
            pct = int(100 * n / total) if total else 0
            self.after(0, self._update_progress, pct, msg)

        self.after(0, self._update_status, "Loading Photos library…")
        try:
            records = load_library(progress_cb=prog)
        except Exception as e:
            self.after(0, self._scan_error, f"Could not open Photos library:\n{e}")
            return

        self.after(0, self._update_status, "Computing perceptual hashes…")
        compute_hashes(records, progress_cb=prog)

        self.after(0, self._update_status, "Finding duplicates…")
        groups = find_duplicates(records)

        self.all_records = records
        self.after(0, self._scan_done, groups)

    def _scan_done(self, groups: list[DuplicateGroup]):
        self.groups = groups
        self._scanning = False
        self.progress_frame.pack_forget()
        self.btn_rescan.config(state="normal")

        if not groups:
            self._update_status("No duplicates found — your library is clean!")
            for w in self.comparison_frame.winfo_children():
                w.destroy()
            tk.Label(
                self.comparison_frame,
                text="✅  No duplicates found.\nYour library looks clean!",
                bg=BG, fg=GREEN,
                font=("SF Pro Text", 18), justify="center"
            ).place(relx=0.5, rely=0.5, anchor="center")
            return

        total_photos = sum(len(g) for g in groups)
        self._update_status(
            f"Found {len(groups)} duplicate group(s)  ·  {total_photos} photos"
        )

        for i, g in enumerate(groups):
            date_str = g[0].date.strftime("%b %Y") if g[0].date else "Unknown"
            label = f"  {i+1:3}.  {len(g)} photos  ·  {date_str}"
            self.group_list.insert("end", label)

        self.group_list.selection_set(0)
        self._on_group_select(None)

    def _scan_error(self, msg: str):
        self._scanning = False
        self.progress_frame.pack_forget()
        self.btn_rescan.config(state="normal")
        messagebox.showerror("Scan Error", msg)
        self._update_status("Scan failed.")

    def _update_progress(self, pct: int, msg: str):
        self.progress["value"] = pct
        self.progress_label.config(text=msg)

    def _update_status(self, msg: str):
        self.status_var.set(msg)

    # ── Group selection & comparison view ─────────────────────────────────

    def _on_group_select(self, _event):
        sel = self.group_list.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx == self.current_group:
            return
        self.current_group = idx
        self._render_group(self.groups[idx])

    def _render_group(self, group: DuplicateGroup):
        frame = self.comparison_frame
        for w in frame.winfo_children():
            w.destroy()

        # Scrollable canvas for the photo cards
        canvas = tk.Canvas(frame, bg=BG, highlightthickness=0)
        vscroll = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vscroll.set)
        vscroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = tk.Frame(canvas, bg=BG)
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_configure(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(win_id, width=canvas.winfo_width())
        inner.bind("<Configure>", _on_configure)
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win_id, width=e.width))

        # Mousewheel scroll
        def _scroll(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _scroll)

        # Group header
        header = tk.Frame(inner, bg=BG, pady=10, padx=16)
        header.pack(fill="x")

        n = len(group)
        tk.Label(header, text=f"Duplicate Group — {n} photos",
                 bg=BG, fg=ACCENT, font=("SF Pro Display", 15, "bold")).pack(side="left")

        btn_mark_all = styled_button(
            header, "Mark all duplicates",
            lambda g=group: self._mark_all_but_best(g),
            color=RED
        )
        btn_mark_all.pack(side="right", padx=4)

        btn_clear = styled_button(
            header, "Clear marks",
            lambda g=group: self._clear_marks(g),
            color=SUBTEXT
        )
        btn_clear.pack(side="right")

        # Photo cards in a wrapping row
        cards = tk.Frame(inner, bg=BG)
        cards.pack(fill="both", expand=True, padx=8, pady=4)

        for rec in group:
            self._build_photo_card(cards, rec)

    def _build_photo_card(self, parent: tk.Frame, rec: PhotoRecord):
        card = tk.Frame(parent, bg=BG_PANEL, bd=0, relief="flat",
                        padx=8, pady=8)
        card.pack(side="left", padx=8, pady=8, anchor="n")

        # Checkbox + filename
        var = tk.BooleanVar(value=rec.marked)

        def _toggle(r=rec, v=var):
            r.marked = v.get()
            self._refresh_marked_count()
            self._refresh_card_border(card, r)

        chk_frame = tk.Frame(card, bg=BG_PANEL)
        chk_frame.pack(fill="x")

        chk = tk.Checkbutton(
            chk_frame, variable=var, command=_toggle,
            bg=BG_PANEL, fg=RED, selectcolor=BG_PANEL,
            activebackground=BG_PANEL, relief="flat",
            font=("SF Pro Text", 11, "bold"),
            text=" Mark for deletion",
            cursor="hand2"
        )
        chk.pack(side="left")

        # Thumbnail
        thumb = None
        if rec.path and os.path.exists(rec.path):
            if rec.path not in self._thumb_cache:
                self._thumb_cache[rec.path] = load_thumbnail(rec.path)
            thumb = self._thumb_cache.get(rec.path)

        if thumb is None:
            thumb = placeholder_image(THUMB_SIZE, "No preview\n(iCloud)")

        img_label = tk.Label(card, image=thumb, bg=BG_PANEL, cursor="hand2")
        img_label.image = thumb  # prevent GC
        img_label.pack(pady=(6, 4))

        if rec.path and os.path.exists(rec.path):
            img_label.bind("<Button-1>", lambda e, p=rec.path: self._show_fullscreen(p))

        # Metadata
        meta = tk.Frame(card, bg=BG_PANEL)
        meta.pack(fill="x")

        def meta_row(label, value, highlight=False):
            row = tk.Frame(meta, bg=BG_PANEL)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=label, bg=BG_PANEL, fg=SUBTEXT,
                     font=("SF Mono", 10), width=9, anchor="w").pack(side="left")
            color = ACCENT if highlight else TEXT_DIM
            tk.Label(row, text=value, bg=BG_PANEL, fg=color,
                     font=("SF Mono", 10), anchor="w").pack(side="left")

        meta_row("File",  rec.filename[:28] + ("…" if len(rec.filename) > 28 else ""))
        meta_row("Date",  rec.date_str)
        meta_row("Size",  rec.size_str, highlight=True)
        meta_row("Res",   f"{rec.width}×{rec.height}  ({rec.megapixels})")

        self._refresh_card_border(card, rec)

    def _refresh_card_border(self, card: tk.Frame, rec: PhotoRecord):
        color = RED if rec.marked else BG_PANEL
        card.config(highlightbackground=color, highlightthickness=2 if rec.marked else 0,
                    highlightcolor=color)

    def _refresh_marked_count(self):
        n = sum(1 for r in self.all_records if r.marked)
        self.marked_var.set(f"{n} marked")
        self.btn_delete.config(state="normal" if n > 0 else "disabled")

    # ── Quick-mark helpers ────────────────────────────────────────────────

    def _mark_all_but_best(self, group: DuplicateGroup):
        """Mark all photos in the group except the first (largest file = best)."""
        for i, rec in enumerate(group):
            rec.marked = (i > 0)
        self._refresh_marked_count()
        if self.current_group is not None:
            self._render_group(self.groups[self.current_group])

    def _clear_marks(self, group: DuplicateGroup):
        for rec in group:
            rec.marked = False
        self._refresh_marked_count()
        if self.current_group is not None:
            self._render_group(self.groups[self.current_group])

    # ── Full-screen preview ───────────────────────────────────────────────

    def _show_fullscreen(self, path: str):
        win = tk.Toplevel(self, bg=BG)
        win.title(pathlib.Path(path).name)
        win.geometry("900x700")

        if path not in self._preview_cache:
            self._preview_cache[path] = load_preview(path, (860, 640))
        img = self._preview_cache.get(path)

        if img:
            lbl = tk.Label(win, image=img, bg=BG)
            lbl.image = img
            lbl.pack(expand=True, pady=16)
        else:
            tk.Label(win, text="Preview unavailable", bg=BG, fg=TEXT_DIM,
                     font=("SF Pro Text", 14)).pack(expand=True)

        tk.Label(win, text=path, bg=BG, fg=SUBTEXT,
                 font=("SF Mono", 10)).pack(pady=(0, 8))
        tk.Button(win, text="Close", command=win.destroy,
                  bg=BG_PANEL, fg=TEXT, relief="flat").pack(pady=4)
        win.bind("<Escape>", lambda e: win.destroy())

    # ── Deletion ──────────────────────────────────────────────────────────

    def _delete_marked(self):
        to_delete = [r for r in self.all_records if r.marked]
        if not to_delete:
            return

        names = "\n".join(f"  • {r.filename}" for r in to_delete[:10])
        if len(to_delete) > 10:
            names += f"\n  … and {len(to_delete) - 10} more"

        confirmed = messagebox.askyesno(
            "Confirm Deletion",
            f"Permanently delete {len(to_delete)} photo(s) from your Photos library?\n\n"
            f"{names}\n\n"
            "This will send them to the Photos Recently Deleted album.\n"
            "They can be recovered within 30 days.",
            icon="warning"
        )
        if not confirmed:
            return

        self._update_status(f"Deleting {len(to_delete)} photo(s)…")
        uuids = [r.uuid for r in to_delete]

        def _worker():
            ok, msg = delete_photos_applescript(uuids)
            self.after(0, self._deletion_done, ok, msg, to_delete)

        threading.Thread(target=_worker, daemon=True).start()

    def _deletion_done(self, ok: bool, msg: str, deleted: list[PhotoRecord]):
        if ok:
            # Remove from local state
            deleted_set = {r.uuid for r in deleted}
            self.all_records = [r for r in self.all_records if r.uuid not in deleted_set]
            for g in self.groups:
                g[:] = [r for r in g if r.uuid not in deleted_set]
            self.groups = [g for g in self.groups if len(g) > 1]

            self.group_list.delete(0, "end")
            for i, g in enumerate(self.groups):
                date_str = g[0].date.strftime("%b %Y") if g[0].date else "Unknown"
                self.group_list.insert("end", f"  {i+1:3}.  {len(g)} photos  ·  {date_str}")

            self.current_group = None
            for w in self.comparison_frame.winfo_children():
                w.destroy()
            tk.Label(
                self.comparison_frame,
                text=f"✅  {msg}\n\nSelect a group on the left to continue.",
                bg=BG, fg=GREEN,
                font=("SF Pro Text", 15), justify="center"
            ).place(relx=0.5, rely=0.5, anchor="center")

            self._refresh_marked_count()
            n_groups = len(self.groups)
            self._update_status(
                f"{n_groups} group(s) remaining" if n_groups else "All duplicates resolved!"
            )
            messagebox.showinfo("Deleted", msg)
        else:
            messagebox.showerror("Deletion Failed", msg)
            self._update_status("Deletion failed — see error dialog.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    # Request Photos access prompt text visible in System Settings → Privacy
    app = PhotoDeduper()
    app.mainloop()


if __name__ == "__main__":
    main()
