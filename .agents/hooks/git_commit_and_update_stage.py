import subprocess
import sys
import pathlib
import datetime

def run_cmd(cmd, cwd=None):
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, shell=True)
    if result.returncode != 0:
        print(f"Command failed: {cmd}\nstdout:{result.stdout}\nstderr:{result.stderr}", file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()

def update_implementation_stages():
    stages_path = pathlib.Path(__file__).resolve().parents[2] / "IMPLEMENTATION_STAGES.md"
    if not stages_path.is_file():
        print(f"IMPLEMENTATION_STAGES.md not found at {stages_path}", file=sys.stderr)
        return
    content = stages_path.read_text(encoding="utf-8").splitlines()
    marker = "EVERYTIME YOU MAKE CHANGES WRITE IT HERE AS THE CURRENT STAGE IMPLEMENTATION PROGRESS AT THE VERY START OF `IMPLEMENTAION_STAGES.md`"
    updated = False
    for i, line in enumerate(content):
        if marker in line:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            content[i] = f"# Current progress updated at {timestamp}"
            updated = True
            break
    if updated:
        stages_path.write_text("\n".join(content) + "\n", encoding="utf-8")
        print(f"IMPLEMENTATION_STAGES.md updated with timestamp {timestamp}")
    else:
        print("Marker not found in IMPLEMENTATION_STAGES.md; no update performed", file=sys.stderr)

def main():
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    # Stage all changes
    run_cmd(["git", "add", "."], cwd=repo_root)
    # Commit with timestamped message
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    commit_msg = f"Auto-commit after changes at {timestamp}"
    # Only commit if there are changes
    status = subprocess.run(["git", "status", "--porcelain"], cwd=repo_root, capture_output=True, text=True)
    if status.stdout.strip():
        run_cmd(["git", "commit", "-m", commit_msg], cwd=repo_root)
        run_cmd(["git", "push", "origin", "main"], cwd=repo_root)
    else:
        print("No changes to commit.")
    # Update progress line in IMPLEMENTATION_STAGES.md
    update_implementation_stages()

if __name__ == "__main__":
    main()
