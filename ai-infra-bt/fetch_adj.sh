#!/bin/zsh
cd "$(dirname "$0")"
for f in data/*.json; do
  S=$(basename "$f" .json)
  [[ -s "data_adj/$S.json" ]] && continue
  for D in "20 Y" "15 Y" "10 Y" "6 Y"; do
    ibkr bars "$S" --profile gateway-live --duration "$D" --bar-size "1 day" \
        --what-to-show ADJUSTED_LAST --json 2>/dev/null | cat > "data_adj/$S.tmp"
    n=$(python3 -c "
import json;raw=open('data_adj/$S.tmp').read();d=json.loads(raw[raw.index('{'):]);print(len(d['rows']))" 2>/dev/null || echo 0)
    if [ "$n" -gt 200 ]; then mv "data_adj/$S.tmp" "data_adj/$S.json"; echo "ok   $S $n ($D)"; break; fi
    rm -f "data_adj/$S.tmp"; sleep 1
  done
  [[ -s "data_adj/$S.json" ]] || echo "FAIL $S"
  sleep 0.6
done
