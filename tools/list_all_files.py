#!/usr/bin/env python3
"""List all Python files in the project with line counts."""

from pathlib import Path

def count_lines(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return sum(1 for _ in f)
    except:
        return 0

def main():
    root = Path.cwd()

    print("ALL PYTHON FILES IN PROJECT")
    print("=" * 80)

    all_files = []

    for py_file in root.rglob("*.py"):
        # Skip venv and hidden folders
        if any(part.startswith('.') or part == 'venv' or part == '__pycache__'
               for part in py_file.parts):
            continue

        lines = count_lines(py_file)
        rel_path = str(py_file.relative_to(root))
        all_files.append((rel_path, lines))

    # Sort by path
    all_files.sort()

    # Group by top-level folder
    by_folder = {}
    for filepath, lines in all_files:
        parts = filepath.split('\\') if '\\' in filepath else filepath.split('/')
        top_folder = parts[0] if len(parts) > 1 else "root"

        if top_folder not in by_folder:
            by_folder[top_folder] = []
        by_folder[top_folder].append((filepath, lines))

    # Print by folder
    for folder in sorted(by_folder.keys()):
        print(f"\n{folder}/")
        print("-" * 80)

        folder_total = sum(lines for _, lines in by_folder[folder])
        print(f"Total: {folder_total} lines in {len(by_folder[folder])} files")
        print()

        for filepath, lines in by_folder[folder]:
            print(f"  {filepath}: {lines} lines")

    # Grand total
    grand_total = sum(lines for _, lines in all_files)
    print(f"\n{'=' * 80}")
    print(f"GRAND TOTAL: {grand_total:,} lines in {len(all_files)} Python files")
    print("=" * 80)

if __name__ == "__main__":
    main()

