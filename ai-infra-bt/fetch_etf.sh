#!/bin/zsh
cd "$(dirname "$0")"
SYMS=(AIQ IGPT ARTY THNQ GRID PAVE POWR SMH SOXX XLU NLR AINF AIPO IGF QQQM VRT PWR ETN)
for S in $SYMS; do
  [[ -s "data_adj/$S.json" ]] && { echo "skip $S"; continue; }
  for DUR in "15 Y" "5 Y" "2 Y" "1 Y"; do
    ibkr bars "$S" --profile gateway-live --duration "$DUR" --bar-size "1 day" \
      --what-to-show ADJUSTED_LAST --json 2>/dev/null | cat > "data_adj/$S.tmp"
    n=$(python3 -c "
import json;raw=open('data_adj/$S.tmp').read();d=json.loads(raw[raw.index('{'):]);print(len(d['rows']))" 2>/dev/null || echo 0)
    if [ "$n" -gt 100 ]; then mv "data_adj/$S.tmp" "data_adj/$S.json"; echo "ok   $S $n ($DUR)"; break; fi
    rm -f "data_adj/$S.tmp"; sleep 13
  done
  [[ -s "data_adj/$S.json" ]] || echo "FAIL $S"
  sleep 13
done
echo ETF_DONE
