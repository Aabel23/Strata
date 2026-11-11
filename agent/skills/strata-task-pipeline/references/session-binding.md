# Session and task binding

The viewer's card key represents one observed run or CLI process. Keep task identity separate from that transient process key.

1. A supervised task run stores `task_id`, `project`, `branch`, `worktree`, run id, and status. The terminal manager stores the PTY id and shell process root.
2. The Linux process scan finds current-user Claude/Codex CLI processes. A descendant of a Strata PTY root gets its terminal id; an external TTY gets a read-only card. Match a CLI process's current directory to the longest known task worktree to fill its task label.
3. Parent-child links come from OS process ancestry when both processes are visible. Native in-process subagents are recorded through Claude/Codex `SubagentStart` and `SubagentStop` hooks in a small local event log. The viewer attaches an active event to its observed parent process or a unique known run in the same worktree. A hook alone cannot create a live PTY for a subagent.
   A coordinator must launch a task subagent from its provisioned task worktree and pass the task contract. Observing a native subagent event does not relocate that agent or assign it a new branch.
4. A card click reuses its owned PTY in the popup. A native subagent shares its parent's terminal or run log. A headless supervised run shows its live log. An external terminal cannot be attached merely from a PID; use a shared PTY/tmux session to support live attachment later.
5. Polling and event adapters must be idempotent. A process id alone is not stable across reuse, so pair it with its start time. Remove a card when its process exits; preserve the Strata task and run history.

Do not infer a task from a branch name alone when a recorded worktree association exists. Do not read private terminal output from an unrelated external session.
