#!/usr/bin/env bash
# Stage 2 smoke test: posts a synthetic Meta webhook payload at a running
# `vercel dev` instance and checks for a non-error reply.
#
# Usage:
#   bash tests/smoke_test.sh [URL] [MESSAGE] [SENDER]
#
# Default sender hash matches the seeded test user (918698510857).
set -euo pipefail

URL="${1:-http://localhost:3000/api/index}"
MESSAGE="${2:-Show expenses for Metro Line Extension}"
SENDER="${3:-918698510857}"

PAYLOAD=$(cat <<JSON
{
  "entry": [
    {
      "changes": [
        {
          "value": {
            "messages": [
              {
                "from": "${SENDER}",
                "id": "wamid.smoketest.$(date +%s)",
                "text": { "body": "${MESSAGE}" },
                "type": "text"
              }
            ]
          }
        }
      ]
    }
  ]
}
JSON
)

echo "POST ${URL}"
echo "Message: ${MESSAGE}"
echo "Sender: ${SENDER}"
echo "---"

RESPONSE=$(curl -sS -X POST "${URL}" \
  -H "Content-Type: application/json" \
  -d "${PAYLOAD}" \
  -w "\n__HTTP__%{http_code}")

HTTP_CODE=$(echo "${RESPONSE}" | grep "__HTTP__" | sed 's/__HTTP__//')
BODY=$(echo "${RESPONSE}" | grep -v "__HTTP__")

echo "${BODY}"
echo "HTTP ${HTTP_CODE}"

# Basic assertions
if [ "${HTTP_CODE}" != "200" ]; then
  echo "FAIL: Expected HTTP 200, got ${HTTP_CODE}"
  exit 1
fi

if echo "${BODY}" | grep -qi "error"; then
  echo "WARN: Response contains 'error'"
fi

echo "---"
echo "PASS: Smoke test completed."
