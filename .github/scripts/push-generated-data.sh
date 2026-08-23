#!/usr/bin/env bash
#
# Push the data files this run regenerated, rebasing onto anything that landed
# on the branch while the agent was working.
#
# Usage: push-generated-data.sh <generated-file>...
#
# Why this is not a plain `git pull --rebase`: these JSON files are regenerated
# wholesale on every run, so a conflict in them carries no information — the
# newest scrape always supersedes whatever is on the branch. Merging them hunk
# by hunk (what `-X theirs` does) can splice two unrelated snapshots into one
# document that is still valid JSON but describes a state that never existed.
# So conflicts in the named files are resolved by restoring this run's output
# verbatim; a conflict anywhere else is a real conflict and aborts the rebase.
#
# Guarantees on exit:
#   * exit 0  — the commit is on the remote.
#   * exit 1  — no rebase is in progress and the working tree is clean, so the
#               later `if: always()` steps still read parseable JSON.

set -euo pipefail

if [ "$#" -eq 0 ]; then
  echo "usage: $0 <generated-file>..." >&2
  exit 2
fi

GENERATED=("$@")
REMOTE="${REMOTE:-origin}"
PUSH_ATTEMPTS="${PUSH_ATTEMPTS:-5}"

# actions/checkout leaves us on the branch for push/schedule/workflow_dispatch,
# but fall back to the event's ref name if HEAD is ever detached.
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "$BRANCH" = "HEAD" ]; then
  BRANCH="${GITHUB_REF_NAME:-main}"
fi

# Snapshot this run's output before touching history: a rebase will overwrite
# the working tree with the version from whichever commit it is replaying.
SNAPSHOT="$(mktemp -d)"
cleanup() {
  # Never exit mid-rebase. A half-finished rebase leaves conflict markers in the
  # data files, which is exactly what breaks the steps that run afterwards.
  if [ -d "$(git rev-parse --git-path rebase-merge)" ] ||
     [ -d "$(git rev-parse --git-path rebase-apply)" ]; then
    echo "Aborting in-progress rebase to leave a clean tree." >&2
    git rebase --abort || true
  fi
  rm -rf "$SNAPSHOT"
}
trap cleanup EXIT

for file in "${GENERATED[@]}"; do
  if [ -f "$file" ]; then
    mkdir -p "$SNAPSHOT/$(dirname "$file")"
    cp "$file" "$SNAPSHOT/$file"
  fi
done

is_generated() {
  local candidate="$1" file
  for file in "${GENERATED[@]}"; do
    [ "$file" = "$candidate" ] && return 0
  done
  return 1
}

conflicted_paths() {
  git diff --name-only --diff-filter=U
}

# Restore this run's version of every conflicted data file. Returns non-zero if
# anything outside the generated set is conflicted.
resolve_conflicts() {
  local unexpected=() path
  while IFS= read -r path; do
    [ -n "$path" ] || continue
    if is_generated "$path" && [ -f "$SNAPSHOT/$path" ]; then
      mkdir -p "$(dirname "$path")"
      cp "$SNAPSHOT/$path" "$path"
      git add -- "$path"
      echo "  resolved $path (kept this run's output)"
    else
      unexpected+=("$path")
    fi
  done < <(conflicted_paths)

  if [ "${#unexpected[@]}" -gt 0 ]; then
    echo "Conflict outside the generated data files: ${unexpected[*]}" >&2
    return 1
  fi
  return 0
}

# Drive a conflicted rebase to completion, resolving each stop in turn.
finish_rebase() {
  while true; do
    resolve_conflicts || return 1

    if GIT_EDITOR=true git rebase --continue; then
      return 0
    fi

    # `--continue` refuses when resolving left nothing to commit, which happens
    # when the branch already carries identical content. Skip that commit.
    if [ -z "$(conflicted_paths)" ]; then
      if GIT_EDITOR=true git rebase --skip; then
        return 0
      fi
      # `--skip` can stop on the next commit's conflict; loop round and resolve.
      if [ -n "$(conflicted_paths)" ]; then
        continue
      fi
      return 1
    fi
  done
}

for attempt in $(seq 1 "$PUSH_ATTEMPTS"); do
  if git push "$REMOTE" "HEAD:$BRANCH"; then
    echo "Pushed on attempt $attempt."
    exit 0
  fi

  echo "Push rejected; rebasing onto $REMOTE/$BRANCH (attempt $attempt of $PUSH_ATTEMPTS)…"
  git fetch --quiet "$REMOTE" "$BRANCH"

  if git rebase "$REMOTE/$BRANCH"; then
    continue
  fi

  echo "Rebase stopped on a conflict; keeping this run's data files."
  if ! finish_rebase; then
    git rebase --abort || true
    echo "Could not rebase automatically." >&2
    exit 1
  fi
done

echo "Could not push after $PUSH_ATTEMPTS attempts." >&2
exit 1
