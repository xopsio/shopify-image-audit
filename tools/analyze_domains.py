#!/usr/bin/env python3
"""Analyze what has been implemented in each domain."""

from pathlib import Path

# 3×3 Model definition
DOMAINS = {
    "JetBrains/Claude": {
        "expected_folders": ["src/engine/", "tests/"],
        "expected_files": ["pyproject.toml"],
        "description": "Orchestrator, CLI, data models, tests, packaging"
    },
    "Cursor/Grok": {
        "expected_folders": ["src/core/"],
        "expected_files": [],
        "description": "Core algorithms, image_extractor, performance_scorer"
    },
    "Windsurf/ChatGPT": {
        "expected_folders": ["schemas/", "docs/"],
        "expected_files": ["QA_CHECKLIST.md"],
        "description": "Specs, schemas, runbooks, QA criteria"
    }
}

def count_lines(filepath):
    """Count lines in a file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return sum(1 for _ in f)
    except:
        return 0

def analyze_folder(folder_path):
    """Analyze contents of a folder."""
    if not folder_path.exists():
        return None

    files = {}
    total_lines = 0

    for py_file in folder_path.rglob("*.py"):
        lines = count_lines(py_file)
        rel_path = str(py_file.relative_to(folder_path.parent))
        files[rel_path] = lines
        total_lines += lines

    return {
        "file_count": len(files),
        "total_lines": total_lines,
        "files": files
    }

def main():
    root = Path.cwd()

    print("=" * 80)
    print("DOMAIN IMPLEMENTATION ANALYSIS")
    print("=" * 80)
    print(f"Project root: {root}")
    print()

    results = {}

    # Analyze each domain
    for domain_name, config in DOMAINS.items():
        print(f"\n{domain_name}")
        print("-" * 80)
        print(f"Expected: {config['description']}")
        print()

        domain_data = {
            "folders": {},
            "files": {},
            "total_lines": 0
        }

        # Check expected folders
        for folder in config["expected_folders"]:
            folder_path = root / folder
            analysis = analyze_folder(folder_path)

            if analysis:
                print(f"  [OK] {folder}")
                print(f"   Files: {analysis['file_count']}")
                print(f"   Lines: {analysis['total_lines']}")
                for filepath, lines in sorted(analysis['files'].items())[:10]:
                    print(f"      - {filepath}: {lines} lines")
                if analysis['file_count'] > 10:
                    print(f"      ... and {analysis['file_count'] - 10} more files")

                domain_data["folders"][folder] = analysis
                domain_data["total_lines"] += analysis["total_lines"]
            else:
                print(f"  [MISSING] {folder} - NOT FOUND")
                domain_data["folders"][folder] = None

        # Check expected files
        for filename in config["expected_files"]:
            filepath = root / filename
            if filepath.exists():
                lines = count_lines(filepath)
                print(f"  [OK] {filename}: {lines} lines")
                domain_data["files"][filename] = lines
                domain_data["total_lines"] += lines
            else:
                print(f"  [MISSING] {filename} - NOT FOUND")
                domain_data["files"][filename] = 0

        results[domain_name] = domain_data

    # Check UNEXPECTED folders
    print(f"\n{'=' * 80}")
    print("UNEXPECTED IMPLEMENTATIONS (not in 3x3 model)")
    print("=" * 80)

    unexpected_folders = ["src/audit/", "src/output/", "report_templates/"]

    for folder in unexpected_folders:
        folder_path = root / folder
        analysis = analyze_folder(folder_path)

        if analysis:
            print(f"\n  [WARNING] {folder}")
            print(f"   Files: {analysis['file_count']}")
            print(f"   Lines: {analysis['total_lines']}")
            print(f"   WHO SHOULD OWN THIS?")

            for filepath, lines in sorted(analysis['files'].items()):
                print(f"      - {filepath}: {lines} lines")
        else:
            print(f"\n  [--] {folder} - does not exist")

    # SUMMARY
    print(f"\n{'=' * 80}")
    print("SUMMARY BY DOMAIN")
    print("=" * 80)

    for domain_name, data in results.items():
        print(f"\n{domain_name}:")
        print(f"  Total lines implemented: {data['total_lines']}")

        implemented_folders = sum(1 for v in data['folders'].values() if v is not None)
        total_folders = len(data['folders'])

        implemented_files = sum(1 for v in data['files'].values() if v > 0)
        total_files = len(data['files'])

        print(f"  Folders: {implemented_folders}/{total_folders} implemented")
        print(f"  Files: {implemented_files}/{total_files} implemented")

        if data['total_lines'] > 0:
            print(f"  Status: HAS IMPLEMENTATION")
        else:
            print(f"  Status: EMPTY / NOT STARTED")

    # Calculate percentages
    total_all = sum(d['total_lines'] for d in results.values())
    if total_all > 0:
        print(f"\n{'=' * 80}")
        print("DOMAIN OWNERSHIP BY CODE VOLUME")
        print("=" * 80)

        for domain_name, data in results.items():
            percentage = (data['total_lines'] / total_all * 100) if total_all > 0 else 0
            print(f"{domain_name}: {data['total_lines']:,} lines ({percentage:.1f}%)")

            # Compare to model expectation
            if "Claude" in domain_name:
                print(f"  Expected per model: ~40%")
                if percentage > 50:
                    print(f"  OVER EXPECTED by {percentage - 40:.1f}%")
            elif "Cursor" in domain_name:
                print(f"  Expected per model: ~40%")
            elif "Windsurf" in domain_name:
                print(f"  Expected per model: ~20%")

    print(f"\n{'=' * 80}")
    print("ANALYSIS COMPLETE")
    print("=" * 80)

if __name__ == "__main__":
    main()

