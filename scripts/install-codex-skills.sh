#!/usr/bin/env bash
set -eu

repo_root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
source_dir="$repo_root/.codex/skills"
dest_dir="${CODEX_HOME:-$HOME/.codex}/skills"

if [ ! -d "$source_dir" ]; then
  echo "No repo-local skills found at $source_dir" >&2
  exit 1
fi

mkdir -p "$dest_dir"

for skill_dir in "$source_dir"/*; do
  [ -d "$skill_dir" ] || continue
  skill_name="$(basename -- "$skill_dir")"
  target_dir="$dest_dir/$skill_name"
  mkdir -p "$target_dir"
  cp -R "$skill_dir"/. "$target_dir"/
  echo "Installed $skill_name -> $target_dir"
done
