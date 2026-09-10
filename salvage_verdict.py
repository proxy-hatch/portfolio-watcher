#!/usr/bin/env python3
"""Recover a completed circuit-breaker verdict from a killed run's transcript.

`claude -p` can finish the review (verdict emitted, run log written) and then be unable to
EXIT, because a Bash command it ran was AUTO-BACKGROUNDED (a slow `find ~` did exactly this
on 2026-09-05 and 2026-09-10). run.sh's watchdog then kills it, the --output-format json
file is empty, and a real decision is thrown away.

The session transcript is flushed as the run goes, so the verdict survives the kill. Print
it ONLY when the model demonstrably finished: the LAST assistant entry must be a text
message carrying a well-formed `VERDICT: APPROVE|HALT`. If that entry is a tool call the
model was still working, so we print nothing and the caller fails closed.

Usage: salvage_verdict.py <transcript.jsonl>   → prints the final text, or exits 1.
"""
import json
import re
import sys

VERDICT = re.compile(r"VERDICT:\s*(APPROVE|HALT)\b")


def last_assistant_entry(path):
    """Return (kind, text) of the final assistant turn; kind is 'tool' or 'text'."""
    last = None
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("type") != "assistant":
                continue
            texts, used_tool = [], False
            for chunk in (row.get("message") or {}).get("content") or []:
                if not isinstance(chunk, dict):
                    continue
                if chunk.get("type") == "tool_use":
                    used_tool = True
                elif chunk.get("type") == "text":
                    texts.append(chunk.get("text", ""))
            last = ("tool" if used_tool else "text", "\n".join(texts))
    return last


def main():
    try:
        last = last_assistant_entry(sys.argv[1])
    except (OSError, IndexError):
        return 1
    if not last or last[0] != "text":
        return 1                      # still mid-work -> fail closed
    if not VERDICT.search(last[1]):
        return 1                      # no clean verdict -> fail closed
    sys.stdout.write(last[1])
    return 0


if __name__ == "__main__":
    sys.exit(main())
