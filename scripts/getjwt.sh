#!/bin/bash

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
    echo "Usage: $0 <device-id> [port]"
    echo "  Example:"
    echo "    $0 my-device-123"
    echo "  Example with custom port:"
    echo "    $0 my-device-123 8000"
    exit 1
fi

DEVICE_ID="$1"
PORT="${2:-31415}"  
API_URL="localhost:$PORT"
AUTH_ENDPOINT="/api/v1/auth/token"
SECRET_FILE="/opt/wlanpi-core/.secrets/shared_secret"

(echo > /dev/tcp/localhost/$PORT) >/dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "Error: Nothing appears to be running on port $PORT"
    echo "Please ensure the API server is running and using the correct port"
    exit 1
fi

if ! sudo test -f "$SECRET_FILE"; then
    echo "Error: Secret file not found at $SECRET_FILE"
    exit 1
fi

REQUEST_BODY="{\"device_id\": \"$DEVICE_ID\"}"

CANONICAL_STRING="POST\n$AUTH_ENDPOINT\n$REQUEST_BODY"

SIGNATURE=$(printf "$CANONICAL_STRING" | \
           openssl dgst -sha256 -hmac "$(sudo cat $SECRET_FILE)" -binary | \
           xxd -p -c 256)

curl -s -X 'POST' \
    "http://$API_URL$AUTH_ENDPOINT" \
    -H "X-Request-Signature: $SIGNATURE" \
    -H 'accept: application/json' \
    -H 'Content-Type: application/json' \
    -d "$REQUEST_BODY" | \
    jq '.'
