#!/bin/zsh
cd "$(dirname "$0")"
typeset -A WANT
WANT=(QQQ "30 Y" QLD "20 Y" TQQQ "20 Y" BIL "20 Y" SHY "20 Y" TLT "20 Y" SPY "30 Y" IEF "20 Y" GLD "20 Y")
for S in ${(k)WANT}; do
  D=$WANT[$S]
  for DUR in "$D" "20 Y" "15 Y"; do
    ibkr bars "$S" --profile gateway-live --duration "$DUR" --bar-size "1 day" \
      --what-to-show ADJUSTED_LAST --json 2>/dev/null | cat > "data_adj/$S.tmp"
    n=$(python3 -c "
import json;raw=open('data_adj/$S.tmp').read();d=json.loads(raw[raw.index('{'):]);print(len(d['rows']))" 2>/dev/null || echo 0)
    old=$(python3 -c "
import json,os
p='data_adj/$S.json'
print(len(json.loads(open(p).read()[open(p).read().index('{'):])['rows']) if os.path.exists(p) else 0)" 2>/dev/null || echo 0)
    if [ "$n" -gt "$old" ]; then mv "data_adj/$S.tmp" "data_adj/$S.json"; echo "ok   $S $n ($DUR)"; break; fi
    rm -f "data_adj/$S.tmp"; sleep 14
  done
  sleep 14
done
echo DONE
