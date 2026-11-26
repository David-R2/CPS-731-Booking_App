#!/bin/sh
# Usage: sh make_submission_zip.sh
# Builds ../CPS731_Team16_ExtensionHandoff.zip from the COMMITTED snapshot (HEAD).
# git archive includes only tracked files: no .git, .venv, caches or databases.
set -e
NAME="CPS731_Team16_ExtensionHandoff"
git archive --format=zip --prefix="${NAME}/" -o "../${NAME}.zip" HEAD
echo "Wrote ../${NAME}.zip from commit $(git rev-parse HEAD)"
