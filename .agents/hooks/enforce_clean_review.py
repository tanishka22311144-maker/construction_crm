#!/usr/bin/env python3
"""Stop hook: best-effort flag if the most recent transcript content
contains an unchecked `[ ]` box, which in this project should only ever
come from the `reviewer` subagent's checklist output.

IMPORTANT PROTOCOL DIFFERENCE FROM THE COPILOT VERSION: the original
Copilot hook fired on `subagentStop` specifically matched to `reviewer`,
and could return `{"behavior": "block", ...}` to actually stop the
orchestrator from continuing. Antigravity's documented hook events are
only PreToolUse / PostToolUse / PreInvocation / PostInvocation / Stop —
there is no subagent-specific stop event, and Stop's stdout contract is
`{}` (notification only; it cannot block continuation).

So this hook can only leave evidence, not enforce anything by itself:
it writes `.agents/hooks/.review_flag.json` when it finds an unchecked
box in the transcript tail. The real enforcement has to be a standing
instruction — see build-orchestrator's agent.md and the root AGENTS.md —
telling the orchestrator to check that file (or just re-read the
reviewer's own output) before treating a checkpoint as passed, and to
never proceed past a Stage 2 / 5 / 6 checkpoint while it exists.
"""
import json
import sys
from pathlib import Path

FLAG_FILE = Path(__file__).resolve().parent / ".review_flag.json"


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = {}

    transcript_path = payload.get("transcriptPath")
    tail_text = ""
    if transcript_path:
        try:
            tail_text = Path(transcript_path).read_text(encoding="utf-8", errors="ignore")[-8000:]
        except OSError:
            tail_text = ""

    if "[ ]" in tail_text:
        FLAG_FILE.write_text(json.dumps({
            "conversationId": payload.get("conversationId"),
            "reason": "Unchecked box found in recent transcript — likely an "
                      "unresolved reviewer finding. Resolve before continuing "
                      "past this checkpoint.",
        }, indent=2))
    elif FLAG_FILE.exists():
        FLAG_FILE.unlink()

    print(json.dumps({}))


if __name__ == "__main__":
    main()
