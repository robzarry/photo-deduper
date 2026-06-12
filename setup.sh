#!/bin/bash
# =============================================================================
# Photo Deduper — Setup Script
# Installs Python dependencies and verifies macOS Photos access.
# Run once before first launch: bash setup.sh
# =============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}"
echo "  ╔══════════════════════════════════════════════════╗"
echo "  ║        📷  Photo Deduper — Setup                ║"
echo "  ╚══════════════════════════════════════════════════╝"
echo -e "${NC}"

# ---------------------------------------------------------------------------
# 1. Python 3.9+
# ---------------------------------------------------------------------------
echo -e "${YELLOW}── Checking Python ─────────────────────────────────────────────────────${NC}"
if ! command -v python3 &>/dev/null; then
    echo -e "  ${RED}Python 3 not found. Install via https://python.org or Homebrew.${NC}"
    exit 1
fi

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
REQUIRED="3.9"
if python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)"; then
    echo -e "  ${GREEN}Python ${PY_VER} ✓${NC}"
else
    echo -e "  ${RED}Python ${PY_VER} found but 3.9+ is required.${NC}"
    exit 1
fi

# ---------------------------------------------------------------------------
# 2. pip dependencies
# ---------------------------------------------------------------------------
echo ""
echo -e "${YELLOW}── Installing Dependencies ─────────────────────────────────────────────${NC}"
echo ""

pip3 install --quiet --upgrade pip

PACKAGES=(
    "osxphotos"   # Photos library access
    "imagehash"   # Perceptual hashing
    "Pillow"      # Image loading & display
)

for pkg in "${PACKAGES[@]}"; do
    echo -ne "  Installing ${pkg}…"
    pip3 install --quiet "$pkg"
    echo -e " ${GREEN}✓${NC}"
done

# ---------------------------------------------------------------------------
# 3. Tkinter check (ships with macOS system Python; may be absent in pyenv)
# ---------------------------------------------------------------------------
echo ""
echo -e "${YELLOW}── Checking Tkinter ────────────────────────────────────────────────────${NC}"
if python3 -c "import tkinter" 2>/dev/null; then
    echo -e "  ${GREEN}Tkinter available ✓${NC}"
else
    echo -e "  ${RED}Tkinter not found.${NC}"
    echo -e "  If using Homebrew Python: ${CYAN}brew install python-tk@$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')${NC}"
    echo -e "  Or use the official Python installer from python.org (includes Tk)."
    exit 1
fi

# ---------------------------------------------------------------------------
# 4. Photos library access reminder
# ---------------------------------------------------------------------------
echo ""
echo -e "${YELLOW}── macOS Privacy Permissions ───────────────────────────────────────────${NC}"
echo ""
echo -e "  When you first run the app, macOS will prompt you to grant"
echo -e "  ${CYAN}Photos access${NC} to Terminal (or your Python interpreter)."
echo ""
echo -e "  If the prompt doesn't appear or the library can't be opened:"
echo -e "  ${CYAN}System Settings → Privacy & Security → Photos${NC}"
echo -e "  and enable access for Terminal / Python."
echo ""
echo -e "  Deletion uses ${CYAN}AppleScript${NC} — the Photos app will open"
echo -e "  automatically when you delete photos."
echo ""

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo -e "${GREEN}══ Setup complete! ════════════════════════════════════════════════════${NC}"
echo -e "  Run with: ${CYAN}python3 photo_deduper.py${NC}"
echo ""
