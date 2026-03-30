#!/bin/sh
set -eu

# Capture baseline commit at container startup (before any agent writes).
# The git-server binary reads GIT_BASELINE_COMMIT on startup; if unset it
# falls back to capturing HEAD itself, but setting it here is safer.
if [ -z "${GIT_BASELINE_COMMIT:-}" ]; then
    BASELINE=$(git -c core.hooksPath=/dev/null rev-parse HEAD 2>/dev/null || true)
    if [ -n "$BASELINE" ]; then
        export GIT_BASELINE_COMMIT="$BASELINE"
        echo "Baseline commit captured: $GIT_BASELINE_COMMIT" >&2
    else
        echo "No baseline commit (empty repo)" >&2
    fi
fi

exec /app/git-server
