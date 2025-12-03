#!/usr/bin/env python3
"""
apply_custom_patch.py

Apply patches in two supported formats:
  1) Custom format with blocks:
     *** Begin Patch
     *** Update File: path/to/file
     ... lines: anchors (no +/-), -removed, +added, @@ separators ...
     *** End Patch

  2) Git unified diff format:
     diff --git a/path b/path
     --- a/path
     +++ b/path
     @@ -oldStart,oldCount +newStart,newCount @@   (optional)
      context lines (leading ' ')
     -removed lines (leading '-')
     +added lines (leading '+')

This script:
 - Accepts a mix of both formats in one file.
 - Uses whitespace-insensitive matching (collapses whitespace sequences).
 - Attempts to apply all hunks in memory; if any hunk fails to match, aborts without writing.
 - Does not create backup files (per user request).
 - Prints diagnostics including best approximate match context when a hunk fails.
 - Usage:
     python apply_custom_patch.py patchfile [repo_root]
"""

from __future__ import annotations

import sys
import os
import re
from typing import List, Dict, Any, Tuple, Optional

# --- regexes and helpers ----------------------------------------------------
RE_CUSTOM_BEGIN = re.compile(r"^\*\*\* Begin Patch\s*$")
RE_CUSTOM_END = re.compile(r"^\*\*\* End Patch\s*$")
RE_CUSTOM_UPDATE = re.compile(r"^\*\*\* Update File:\s*(.+)$")
RE_DIFF_GIT = re.compile(r"^diff --git a/(.+) b/(.+)$")
# Accept hunk headers like:
# @@ -1,3 +1,4 @@
# @@ -1 +1 @@
# @@ -12,7 +12,8 @@ optional trailing text
RE_GIT_HUNK_HDR = re.compile(r"^@@\s*-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s*@@")
RE_HUNK_AT = re.compile(r"^@@")

def normalize_cmp(s: str) -> str:
    """Collapse whitespace sequences into single spaces and strip ends for comparison."""
    return " ".join(s.strip().split())

def read_file_lines(path: str) -> List[str]:
    with open(path, "r", encoding="utf-8", errors="surrogateescape") as f:
        return [ln.rstrip("\n") for ln in f.readlines()]

# --- parsers ---------------------------------------------------------------
def parse_custom_blocks(lines: List[str]) -> List[Dict[str, Any]]:
    """
    Parse custom blocks. Returns list of {path, hunks: [list_of_lines_per_hunk_raw], format: 'custom'}.
    Hunk separators '@@' are allowed and will be removed from content.
    """
    i = 0
    patches: List[Dict[str, Any]] = []
    while i < len(lines):
        if RE_CUSTOM_BEGIN.match(lines[i].strip()):
            i += 1
            if i >= len(lines):
                raise ValueError("Unexpected EOF after Begin Patch")
            m = RE_CUSTOM_UPDATE.match(lines[i])
            if not m:
                raise ValueError(f"Expected '*** Update File: path' after Begin Patch, got: {lines[i]!r}")
            path = m.group(1).strip()
            i += 1
            block_lines: List[str] = []
            while i < len(lines) and not RE_CUSTOM_END.match(lines[i].strip()):
                block_lines.append(lines[i])
                i += 1
            if i >= len(lines) or not RE_CUSTOM_END.match(lines[i].strip()):
                raise ValueError("Missing End Patch for file " + path)
            i += 1
            # split into hunks by '@@' separators (do not include @@ lines)
            hunks: List[List[str]] = []
            cur: List[str] = []
            for ln in block_lines:
                if RE_HUNK_AT.match(ln):
                    if cur:
                        hunks.append(cur)
                    cur = []
                else:
                    cur.append(ln)
            if cur:
                hunks.append(cur)
            patches.append({"path": path, "hunks": hunks, "format": "custom"})
        else:
            i += 1
    return patches

def parse_git_unified(lines: List[str]) -> List[Dict[str, Any]]:
    """
    Parse git unified diffs. Returns list of {path, hunks: [hunk_dicts], format: 'git'}.
    Each hunk_dict: {'old_start','old_count','new_start','new_count','lines': [raw lines with leading ' ','-','+']}
    This parser accepts:
      - standard hunks with @@ header
      - hunks without @@ header: contiguous blocks of lines starting with ' ', '-', '+' are treated as hunks
    """
    i = 0
    patches: List[Dict[str, Any]] = []
    while i < len(lines):
        m = RE_DIFF_GIT.match(lines[i])
        if not m:
            i += 1
            continue
        old_path, new_path = m.group(1), m.group(2)
        i += 1
        # advance to --- and +++ lines (they may be present)
        while i < len(lines) and not lines[i].startswith('--- '):
            i += 1
        if i < len(lines) and lines[i].startswith('--- '):
            i += 1
        while i < len(lines) and not lines[i].startswith('+++ '):
            i += 1
        if i < len(lines) and lines[i].startswith('+++ '):
            i += 1
        hunks: List[Dict[str, Any]] = []
        while i < len(lines):
            if RE_DIFF_GIT.match(lines[i]):
                break
            # If we see a git hunk header, parse it
            mh = RE_GIT_HUNK_HDR.match(lines[i])
            if mh:
                old_start = int(mh.group(1))
                old_count = int(mh.group(2)) if mh.group(2) else 1
                new_start = int(mh.group(3))
                new_count = int(mh.group(4)) if mh.group(4) else 1
                i += 1
                hlines: List[str] = []
                while i < len(lines) and not RE_GIT_HUNK_HDR.match(lines[i]) and not RE_DIFF_GIT.match(lines[i]):
                    hlines.append(lines[i])
                    i += 1
                hunks.append({
                    "old_start": old_start,
                    "old_count": old_count,
                    "new_start": new_start,
                    "new_count": new_count,
                    "lines": hlines
                })
                continue
            # Otherwise, if we encounter a block of lines starting with ' ', '-', '+', treat as a hunk (no header)
            if lines[i].startswith((" ", "-", "+")):
                hlines: List[str] = []
                # collect contiguous block of diff-like lines
                while i < len(lines) and lines[i].startswith((" ", "-", "+")):
                    hlines.append(lines[i])
                    i += 1
                # unknown positions; set starts to 0 to indicate "no header"
                hunks.append({
                    "old_start": 0,
                    "old_count": 0,
                    "new_start": 0,
                    "new_count": 0,
                    "lines": hlines
                })
                continue
            # skip unrelated lines
            i += 1
        patches.append({"path": new_path, "hunks": hunks, "format": "git"})
    return patches

def parse_patch_file(patch_path: str) -> List[Dict[str, Any]]:
    with open(patch_path, "r", encoding="utf-8", errors="replace") as f:
        lines = [ln.rstrip("\n") for ln in f.readlines()]
    patches: List[Dict[str, Any]] = []
    # Try custom blocks first (if any)
    try:
        custom = parse_custom_blocks(lines)
        patches.extend(custom)
    except Exception:
        # ignore parse errors for custom; we'll still try git format
        pass
    # Try git unified diffs
    try:
        gitp = parse_git_unified(lines)
        patches.extend(gitp)
    except Exception:
        pass
    # If nothing parsed, try to detect a simple git unified without diff --git header
    if not patches:
        i = 0
        while i < len(lines):
            if lines[i].startswith('--- '):
                old = lines[i][4:].strip()
                j = i + 1
                if j < len(lines) and lines[j].startswith('+++ '):
                    new = lines[j][4:].strip()
                    i = j + 1
                    hunks: List[Dict[str, Any]] = []
                    while i < len(lines):
                        mh = RE_GIT_HUNK_HDR.match(lines[i])
                        if mh:
                            old_start = int(mh.group(1))
                            old_count = int(mh.group(2)) if mh.group(2) else 1
                            new_start = int(mh.group(3))
                            new_count = int(mh.group(4)) if mh.group(4) else 1
                            i += 1
                            hlines: List[str] = []
                            while i < len(lines) and not RE_GIT_HUNK_HDR.match(lines[i]):
                                hlines.append(lines[i])
                                i += 1
                            hunks.append({
                                "old_start": old_start,
                                "old_count": old_count,
                                "new_start": new_start,
                                "new_count": new_count,
                                "lines": hlines
                            })
                        else:
                            # also accept contiguous diff-like blocks without headers
                            if lines[i].startswith((" ", "-", "+")):
                                hlines = []
                                while i < len(lines) and lines[i].startswith((" ", "-", "+")):
                                    hlines.append(lines[i])
                                    i += 1
                                hunks.append({
                                    "old_start": 0,
                                    "old_count": 0,
                                    "new_start": 0,
                                    "new_count": 0,
                                    "lines": hlines
                                })
                            else:
                                i += 1
                    patches.append({"path": new, "hunks": hunks, "format": "git"})
                    break
            i += 1
    return patches

# --- build orig/new from hunks ---------------------------------------------
def build_orig_new_from_git_hunk(hunk_lines: List[str]) -> Tuple[List[str], List[str], List[str]]:
    """
    From git hunk raw lines produce:
      orig_lines: list of lines that should be present in file (context + removed)
      new_lines: list of lines that will replace orig (context + added)
      raw: raw hunk preview for diagnostics
    """
    orig: List[str] = []
    new: List[str] = []
    raw: List[str] = []
    for ln in hunk_lines:
        raw.append(ln)
        if ln == "":
            orig.append("")
            new.append("")
            continue
        prefix = ln[0]
        if prefix == " ":
            text = ln[1:]
            orig.append(text)
            new.append(text)
        elif prefix == "-":
            orig.append(ln[1:])
        elif prefix == "+":
            new.append(ln[1:])
        else:
            # treat as context line without explicit prefix
            orig.append(ln)
            new.append(ln)
    return orig, new, raw

def build_orig_new_from_custom_hunk(hunk_lines: List[str]) -> Tuple[List[str], List[str], List[str]]:
    """
    From custom hunk lines produce orig (anchors+subs) and new (anchors+adds).
    Lines starting with '-' are subs, '+' are adds, others are anchors.
    """
    orig: List[str] = []
    new: List[str] = []
    raw: List[str] = []
    for ln in hunk_lines:
        raw.append(ln)
        if ln == "":
            orig.append("")
            new.append("")
            continue
        first = ln[0]
        if first == "-":
            orig.append(ln[1:])
        elif first == "+":
            new.append(ln[1:])
        else:
            orig.append(ln)
            new.append(ln)
    return orig, new, raw

# --- matching helpers ------------------------------------------------------
def find_match_position(file_lines: List[str], pattern_lines: List[str]) -> int:
    """
    Find position where pattern_lines occur contiguously in file_lines using whitespace-insensitive comparison.
    Return 0-based index or -1.
    """
    if not pattern_lines:
        return 0
    n = len(file_lines)
    m = len(pattern_lines)
    if m == 0:
        return 0
    file_norm = [normalize_cmp(x) for x in file_lines]
    pat_norm = [normalize_cmp(x) for x in pattern_lines]
    for i in range(0, n - m + 1):
        ok = True
        for j in range(m):
            if file_norm[i + j] != pat_norm[j]:
                ok = False
                break
        if ok:
            return i
    return -1

def find_best_match(file_lines: List[str], pattern_lines: List[str]) -> Tuple[int, float]:
    """
    Find best approximate match position (simple line-equality ratio).
    Returns (best_index, ratio).
    """
    if not pattern_lines:
        return 0, 1.0
    file_norm = [normalize_cmp(x) for x in file_lines]
    pat_norm = [normalize_cmp(x) for x in pattern_lines]
    n = len(file_norm)
    m = len(pat_norm)
    best_ratio = 0.0
    best_idx = -1
    if m == 0 or n == 0:
        return -1, 0.0
    for i in range(0, max(1, n - m + 1)):
        matches = 0
        for j in range(m):
            if file_norm[i + j] == pat_norm[j]:
                matches += 1
        ratio = matches / m
        if ratio > best_ratio:
            best_ratio = ratio
            best_idx = i
    return best_idx, best_ratio

# --- apply logic -----------------------------------------------------------
def apply_all_patches(root: str, patches: List[Dict[str, Any]]) -> int:
    """
    Attempt to apply all patches in memory. If any hunk fails, abort and return non-zero.
    If all succeed, write files and return 0.
    """
    results: List[Tuple[str, bool, str, List[str]]] = []
    for p in patches:
        rel = p["path"]
        fmt = p.get("format", "custom")
        target = os.path.join(root, rel)
        file_exists = os.path.exists(target)
        if file_exists:
            file_lines = read_file_lines(target)
        else:
            file_lines = []

        working = list(file_lines)
        ok_all = True
        msg_fail = ""
        for hidx, h in enumerate(p["hunks"], start=1):
            if fmt == "git":
                orig, new, raw = build_orig_new_from_git_hunk(h["lines"])
            else:
                orig, new, raw = build_orig_new_from_custom_hunk(h)
            # If file doesn't exist and orig is non-empty -> fail
            if not file_exists:
                if any(normalize_cmp(x) != "" for x in orig):
                    ok_all = False
                    msg_fail = f"hunk {hidx} for {rel} expects existing content but file does not exist."
                    break
                # create file content by concatenating new segments
                working.extend(new)
                file_exists = True
                continue

            pos = find_match_position(working, orig)
            if pos != -1:
                L_old = len(orig)
                working = working[:pos] + new + working[pos + L_old:]
                continue

            # no exact match -> diagnostics and abort
            best_idx, best_ratio = find_best_match(working, orig)
            ctx_before = 5
            ctx_after = 5
            if best_idx == -1:
                context_snippet = "(no approximate match found in file)"
            else:
                start = max(0, best_idx - ctx_before)
                end = min(len(working), best_idx + len(orig) + ctx_after)
                snippet = working[start:end]
                numbered = []
                for k, ln in enumerate(snippet, start=start + 1):
                    numbered.append(f"{k:5d}: {ln}")
                context_snippet = "\n".join(numbered)
            raw_preview = "\n".join(raw[:80]) + ("\n..." if len(raw) > 80 else "")
            msg_fail = (
                f"hunk {hidx} for {rel} did not match (whitespace-insensitive).\n"
                f"Hunk preview:\n{raw_preview}\n\n"
                f"Best approximate match ratio: {best_ratio:.3f} at index {best_idx}.\n"
                f"File context around best match (lines shown as 'num: text'):\n{context_snippet}\n"
            )
            ok_all = False
            break

        results.append((rel, ok_all, msg_fail, working))

    # If any failed, print diagnostics and abort without writing
    failed = [r for r in results if not r[1]]
    if failed:
        print("Patch application aborted. The following files/hunks failed to match:")
        for path, ok, msg, _ in failed:
            print(f"- {path}: {msg}")
        print("No files were modified.")
        return 2

    # All succeeded: write files (no backups)
    for path, ok, msg, new_lines in results:
        target = os.path.join(root, path)
        d = os.path.dirname(target)
        if d and not os.path.exists(d):
            os.makedirs(d, exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(new_lines) + ("\n" if new_lines and not new_lines[-1].endswith("\n") else ""))
        print(f"[APPLIED] {path} ({len(new_lines)} lines)")
    print("All patches applied successfully.")
    return 0

# --- main ------------------------------------------------------------------
def main():
    if len(sys.argv) < 2:
        print("Usage: python apply_custom_patch.py patchfile [repo_root]")
        sys.exit(2)
    patchfile = sys.argv[1]
    root = sys.argv[2] if len(sys.argv) > 2 else os.getcwd()
    if not os.path.exists(patchfile):
        print("Patch file not found:", patchfile)
        sys.exit(1)
    try:
        patches = parse_patch_file(patchfile)
    except Exception as e:
        print("Failed to parse patch file:", e)
        sys.exit(1)
    if not patches:
        print("No patches found in file.")
        sys.exit(1)
    rc = apply_all_patches(root, patches)
    sys.exit(rc)

if __name__ == "__main__":
    main()
