from pathlib import Path

# Example project structure (required)
project_structure = {
    "folders": [
        "src",
        "data",
        "notebooks",
        "tests"
    ],
    "files": [
        "src/main.py",
        "src/utils.py",
        "README.md"
    ]
}

def setup_project():
    # Create directories
    for folder in project_structure["folders"]:
        Path(folder).mkdir(parents=True, exist_ok=True)

    # Header template for Python files
    py_header = (
        "# PROJECT KALA AGNI\n"
        "# Advanced Orbital Intelligence Platform\n"
        "# File: {filename}\n\n"
    )

    # Create files
    for file_path in project_structure["files"]:
        p = Path(file_path)
        if p.suffix == ".py":
            content = py_header.format(filename=p.name)
            p.write_text(content, encoding="utf-8")
        else:
            p.touch(exist_ok=True)

    # Create requirements.txt
    requirements_content = (
        "streamlit\n"
        "requests\n"
        "pandas\n"
        "numpy\n"
        "plotly\n"
        "poliastro\n"
        "sgp4\n"
        "python-dateutil\n"
    )
    Path("requirements.txt").write_text(requirements_content, encoding="utf-8")

    # Success Message
    print("✅ PROJECT KALA AGNI project skeleton created successfully!")

    # Simple Tree Summary
    print("\nProject Structure:")
    paths = sorted(Path(".").rglob("*"))
    for path in paths:
        if "__pycache__" in str(path) or ".git" in str(path) or path.name == "setup_kala_agni.py":
            continue
        depth = len(path.relative_to(".").parts)
        spacer = "  " * (depth - 1)
        prefix = "└── " if depth > 0 else ""
        print(f"{spacer}{prefix}{path.name}")


if __name__ == "__main__":
    setup_project()