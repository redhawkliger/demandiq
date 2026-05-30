# CLAUDE.md

Project-level notes for working in this repo with Claude Code.

## Environment: harness tmpfs ENOSPC (Bash output failures)

**Symptom.** Bash tool calls intermittently fail with:

> the temp filesystem at `/private/tmp/claude-502/.../tasks` is full (0MB free).
> The child process's stdout/stderr writes failed with ENOSPC.

The real disk has space (`df` shows plenty free). The harness captures each
command's stdout/stderr to a small tmpfs that fills as `.output` files
accumulate over a long session, so commands that print more than a few bytes
start failing. Commands that produce **no** stdout still run fine.

**Workarounds**, in order of preference:

1. **Route output to a file on the main disk, then Read it.** The harness sees
   empty stdout (no tmpfs write), and the Read tool is unaffected:
   ```bash
   { cmd1; cmd2; } > /Users/Ak47/dq_scratch.txt 2>&1; true
   ```
   then Read `/Users/Ak47/dq_scratch.txt`. Delete the scratch file when done.
   This is the reliable approach for anything verbose (`gh run watch`, test
   suites, builds, multi-line greps).

2. **Clear the accumulated output files** (produces no stdout, so it runs even
   when the tmpfs is full):
   ```bash
   find /private/tmp/claude-502 -name '*.output' -type f -delete 2>/dev/null; true
   ```
   This also deletes the current command's own output file, so the tool result
   shows a benign `ENOENT ... could not be read` — the command still executed.

3. A no-output command such as `true` always works; use it to confirm recovery.

**Prefer dedicated tools over Bash** for file reads/edits/searches — Read, Write,
and Edit never hit this tmpfs; only Bash stdout capture does.
