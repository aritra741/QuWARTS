#!/bin/bash
# Script to check for errors in WDIRS log file

LOG_FILE="wdirs.log"

if [ ! -f "$LOG_FILE" ]; then
    echo "Log file not found: $LOG_FILE"
    exit 1
fi

echo "================================================================================"
echo "ERRORS AND WARNINGS FROM WDIRS LOG"
echo "================================================================================"
echo ""

echo "--- ERRORS ---"
grep -i "error" "$LOG_FILE" | tail -20

echo ""
echo "--- EXCEPTIONS ---"
grep -i "exception\|traceback" "$LOG_FILE" | tail -20

echo ""
echo "--- WARNINGS ---"
grep -i "warning" "$LOG_FILE" | tail -20

echo ""
echo "--- FAILED ---"
grep -i "failed" "$LOG_FILE" | tail -20

echo ""
echo "================================================================================"
echo "LAST 30 LINES OF LOG"
echo "================================================================================"
tail -30 "$LOG_FILE"
