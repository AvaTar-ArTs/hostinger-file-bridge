#!/usr/bin/env bash
set -euo pipefail

FILE="${1:-$HOME/Downloads/AvatarArts-CreativeOS-Memory-Product-2026-08-18.zip}"
REMOTE="${2:-releases/AvatarArts-CreativeOS-Memory-Product-2026-08-18.zip}"

hostinger-upload status
hostinger-upload upload "$FILE" "$REMOTE"
hostinger-upload list releases
