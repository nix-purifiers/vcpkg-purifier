#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
set -euo pipefail
system=$(nix eval --impure --raw --expr builtins.currentSystem)
for name in cli environment project release; do
  nix build ".#checks.$system.$name" --no-link
  nix build ".#checks.$system.$name" --no-link --rebuild
done
