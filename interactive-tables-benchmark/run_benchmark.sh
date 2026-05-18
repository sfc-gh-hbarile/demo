#!/bin/bash
# =============================================================================
# Interactive Tables Benchmark Runner
# =============================================================================
# One-command script to run the benchmark. Edit config.yaml first!
#
# Usage:
#   ./run_benchmark.sh
#   ./run_benchmark.sh --concurrency "10,25,50" --duration 60
#   ./run_benchmark.sh --point-lookups-only
#   ./run_benchmark.sh --interactive-only
#
# Authentication (set ONE of these before running):
#   export SNOWFLAKE_PAT_TOKEN="<your PAT token>"   # Recommended (bypasses MFA)
#   export SNOWFLAKE_PASSWORD="<your password>"      # May trigger MFA
#
# Required environment variables:
#   export SNOWFLAKE_ACCOUNT_URL="your-org-account.snowflakecomputing.com"
#   export SNOWFLAKE_USER="your_user"
#   export SNOWFLAKE_PAT_TOKEN="<token>"
#
# Optional:
#   export SNOWFLAKE_ROLE="SYSADMIN"          # default: SYSADMIN
#   export SNOWFLAKE_JDBC_JAR="./snowflake-jdbc.jar"  # auto-downloaded if missing
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Defaults
JDBC_JAR="${SNOWFLAKE_JDBC_JAR:-./snowflake-jdbc.jar}"
EXTRA_ARGS=""

# Parse arguments (pass through to Python)
while [[ $# -gt 0 ]]; do
    case $1 in
        --concurrency)
            EXTRA_ARGS="$EXTRA_ARGS --concurrency $2"
            shift 2
            ;;
        --duration)
            EXTRA_ARGS="$EXTRA_ARGS --duration $2"
            shift 2
            ;;
        --output)
            EXTRA_ARGS="$EXTRA_ARGS --output $2"
            shift 2
            ;;
        --config)
            EXTRA_ARGS="$EXTRA_ARGS --config $2"
            shift 2
            ;;
        --interactive-only|--standard-only|--no-upload|--point-lookups-only|--mixed-workload)
            EXTRA_ARGS="$EXTRA_ARGS $1"
            shift
            ;;
        *)
            EXTRA_ARGS="$EXTRA_ARGS $1"
            shift
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

echo "=============================================="
echo " Interactive Tables Benchmark"
echo "=============================================="
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "ERROR: python3 not found. Install Python 3.11+"
    exit 1
fi

# Check config.yaml exists
if [ ! -f "config.yaml" ]; then
    echo "ERROR: config.yaml not found."
    echo "  1. Copy config.yaml from this kit"
    echo "  2. Edit it with your warehouse names, tables, and queries"
    exit 1
fi

# Check JDBC jar (auto-download if missing)
if [ ! -f "$JDBC_JAR" ]; then
    echo "JDBC jar not found at: $JDBC_JAR"
    echo "Downloading Snowflake JDBC driver..."
    curl -L -o "$JDBC_JAR" \
        "https://repo1.maven.org/maven2/net/snowflake/snowflake-jdbc/3.16.1/snowflake-jdbc-3.16.1.jar"
    echo "Downloaded: $JDBC_JAR"
fi
export SNOWFLAKE_JDBC_JAR="$JDBC_JAR"

# Check required env vars
if [ -z "$SNOWFLAKE_ACCOUNT_URL" ]; then
    echo "ERROR: SNOWFLAKE_ACCOUNT_URL not set."
    echo "  export SNOWFLAKE_ACCOUNT_URL=\"your-org-account.snowflakecomputing.com\""
    exit 1
fi

if [ -z "$SNOWFLAKE_USER" ]; then
    echo "ERROR: SNOWFLAKE_USER not set."
    echo "  export SNOWFLAKE_USER=\"your_username\""
    exit 1
fi

if [ -z "$SNOWFLAKE_PAT_TOKEN" ] && [ -z "$SNOWFLAKE_PASSWORD" ]; then
    echo "ERROR: Authentication required. Set one of:"
    echo "  export SNOWFLAKE_PAT_TOKEN='<token>'   (recommended, bypasses MFA)"
    echo "  export SNOWFLAKE_PASSWORD='<password>'  (may trigger MFA)"
    echo ""
    echo "To generate a PAT token, run in Snowflake:"
    echo "  ALTER USER <your_user> ADD PAT benchmark_token"
    echo "    DAYS_TO_EXPIRY = 30"
    echo "    COMMENT = 'Interactive Tables benchmark';"
    exit 1
fi

if [ -n "$SNOWFLAKE_PAT_TOKEN" ]; then
    echo "  Auth:        PAT token (MFA bypassed)"
else
    echo "  Auth:        Password (MFA may be triggered)"
fi

# Check Python dependencies
echo "Checking Python dependencies..."
python3 -c "import jaydebeapi, jpype, pandas, yaml" 2>/dev/null || {
    echo "Installing dependencies..."
    pip install -r requirements.txt
}

# ---------------------------------------------------------------------------
# Run Benchmark
# ---------------------------------------------------------------------------

echo ""
echo "Configuration:"
echo "  Account:     $SNOWFLAKE_ACCOUNT_URL"
echo "  User:        $SNOWFLAKE_USER"
echo "  JDBC Jar:    $JDBC_JAR"
echo "  Config:      config.yaml"
echo ""
echo "Starting benchmark..."
echo ""

python3 benchmark_driver.py $EXTRA_ARGS

echo ""
echo "=============================================="
echo " Benchmark Complete!"
echo "=============================================="
echo " Results: benchmark_results.csv"
echo ""
echo " To view the dashboard:"
echo "   streamlit run benchmark_dashboard.py"
echo "=============================================="
