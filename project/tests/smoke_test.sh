#!/usr/bin/env bash
# Stage 1 smoke test: posts a synthetic Meta webhook payload at a running
# `vercel dev` instance and checks for a non-error reply.
#
# NOT derived from your PROJECT_SPEC.md (which wasn't in the files you
# uploaded) — this is a generic WhatsApp Cloud API payload shape. Confirm
# field names against your real spec/webhook logs before relying on it.
set -euo pipefail

URL="${1:-http://localhost:3000/api/index}"
MESSAGE="${2:-Hello, is anyone there?}"

PAYLOAD=$(cat <<JSON
{
  "entry": [
    {
      "changes": [
        {
          "value": {
            "messages": [
              {
                "from": "15550001111",
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
curl -sS -X POST "${URL}" \
  -H "Content-Type: application/json" \
  -d "${PAYLOAD}" \
  -w "\nHTTP %{http_code}\n"
