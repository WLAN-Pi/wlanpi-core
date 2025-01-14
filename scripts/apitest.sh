#!/bin/bash

PORT=8000
BASE_URL="/api/v1"
SECRETS_PATH="/opt/wlanpi-core/.secrets/shared_secret"
METHOD="GET"
ENDPOINT=""
PAYLOAD=""
HEADERS=""

check_port() {
    local port="$1"
    (echo > /dev/tcp/localhost/"$port") >/dev/null 2>&1
    if [ $? -ne 0 ]; then
        echo "Error: Nothing appears to be running on port $port"
        echo "Please ensure the wlanpi-core is running on the desired port"
        exit 1
    fi
}

get_shared_secret() {
    local secrets_path="$1"
    
    if ! sudo test -f "$secrets_path"; then
        echo "Error: Secret file not found at $secrets_path"
        exit 1
    fi
    
    sudo cat "$secrets_path"
}

generate_signature() {
    local method="$1"
    local endpoint="$2"
    local payload="${3:-}"
    local shared_secret="$4"
    
    local canonical_string="${method}\n${endpoint}\n${payload}"
    local signature=$(printf "$canonical_string" | openssl dgst -sha256 -hmac "$shared_secret" -binary | xxd -p -c 256)
    
    echo "$signature"
}

api_call() {
    local method="$1"
    local endpoint="$2"
    local payload="${3:-}"
    local headers="${4:-}"
    local port="$5"
    local shared_secret="$6"
    local signature=""
    
    check_port "$port"
    
    if [[ "$method" =~ ^(GET|PATCH|POST|PUT|DELETE)$ ]]; then
        signature=$(generate_signature "$method" "$BASE_URL$endpoint" "$payload" "$shared_secret")
    fi
    
    # Construct curl command
    local curl_cmd=(
        curl -s -X "$method"
        -H "accept: application/json"
    )
    
    # Add signature header if generated
    if [[ -n "$signature" ]]; then
        curl_cmd+=(-H "X-Request-Signature: $signature")
    fi
    
    # Add additional headers
    if [[ -n "$headers" ]]; then
        IFS=',' read -ra HEADER_ARRAY <<< "$headers"
        for header in "${HEADER_ARRAY[@]}"; do
            curl_cmd+=(-H "$header")
        done
    fi
    
    # Add payload for methods that support it
    if [[ -n "$payload" ]] && [[ "$method" =~ ^(POST|PUT|PATCH)$ ]]; then
        curl_cmd+=(-H "Content-Type: application/json" -d "$payload")
    fi
    
    # Construct full URL
    local full_url="http://localhost:$port$BASE_URL$endpoint"
    curl_cmd+=("$full_url")
    
    # Execute the curl command and pretty print with jq
    "${curl_cmd[@]}" | jq '.'
}

usage() {
    echo "Usage: $0 [options]"
    echo "Options:"
    echo "  -p, --port PORT     Set the port (default: 8000)"
    echo "  -b, --base BASE     Set the base URL path (default: /api/v1)"
    echo "  -s, --secrets PATH  Set the path to shared secrets (default: /opt/wlanpi-core/.secrets/shared_secret)"
    echo "  -X, --method METHOD Set HTTP method (GET, POST, PUT, DELETE)"
    echo "  -e, --endpoint ENDPOINT Specify the API endpoint"
    echo "  -P, --payload PAYLOAD JSON payload for POST/PUT requests"
    echo "  -H, --headers HEADERS Comma-separated additional headers"
    echo "  -h, --help         Show this help message"
    echo ""
    echo "  Get Token:              $0 -X POST -e /auth/token -P '{\"device_id\": \"1\"}'"
    exit 1
}

ARGS=$(getopt -o p:b:s:X:e:P:H:h --long port:,base:,secrets:,method:,endpoint:,payload:,headers:,help -n "$0" -- "$@")

if [[ $? -ne 0 ]]; then
    usage
fi

eval set -- "$ARGS"

while true; do
    case "$1" in
        -p|--port) PORT="$2"; shift 2 ;;
        -b|--base) BASE_URL="$2"; shift 2 ;;
        -s|--secrets) SECRETS_PATH="$2"; shift 2 ;;
        -X|--method) METHOD="$2"; shift 2 ;;
        -e|--endpoint) ENDPOINT="$2"; shift 2 ;;
        -P|--payload) PAYLOAD="$2"; shift 2 ;;
        -H|--headers) HEADERS="$2"; shift 2 ;;
        -h|--help) usage ;;
        --) shift; break ;;
        *) 
            if [[ -z "$1" ]]; then
                break
            fi
            echo "Invalid option: $1"
            usage
            ;;
    esac
done

if [[ -z "$ENDPOINT" ]]; then
    usage
fi

SHARED_SECRET=$(get_shared_secret "$SECRETS_PATH")

api_call "$METHOD" "$ENDPOINT" "$PAYLOAD" "$HEADERS" "$PORT" "$SHARED_SECRET"