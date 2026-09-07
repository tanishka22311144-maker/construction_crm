#!/usr/bin/env bash
# End-to-end smoke test against `vercel dev`. Run manually at the end of a
# phase, or from the orchestrator agent — does not consume Copilot quota.
#
# Usage: ./tests/smoke_test.sh
set -euo pipefail

PORT=3000
LOG_FILE=$(mktemp)

echo "Starting vercel dev on :${PORT}..."
vercel dev --listen ${PORT} > "${LOG_FILE}" 2>&1 &
DEV_PID=$!
trap 'kill ${DEV_PID} 2>/dev/null || true' EXIT

# Wait for the dev server to come up.
for i in $(seq 1 30); do
  if curl -s "http://localhost:${PORT}" > /dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "Posting synthetic Meta webhook payload..."
RESPONSE=$(curl -s -X POST "http://localhost:${PORT}/api/index" \
  -H "Content-Type: application/json" \
  -d '{
    "entry": [{
      "changes": [{
        "value": {
          "messages": [{
            "id": "smoke-test-message-id-0001",
            "from": "15550001111",
            "text": {"body": "Show expenses for Pipeline Alpha"}
          }]
        }
      }]
    }]
  }')

echo "Response: ${RESPONSE}"
echo "---"
echo "Dev server log tail:"
tail -n 40 "${LOG_FILE}"

# Basic assertion: expect a 2xx-shaped response body, not a stack trace.
if echo "${RESPONSE}" | grep -qi "traceback\|internal server error"; then
  echo "SMOKE TEST FAILED: server error in response"
  exit 1
fi

echo "SMOKE TEST PASSED (manual review of response content still recommended)"
