#!/bin/zsh
cd "$(dirname "$0")"
# Priority order: instruments where the dividend adjustment matters most.
SYMS=(SPY TLT IEF SHY LQD HYG AGG TIP VNQ XLU XLP XLE XLF XLK XLV XLI XLY XLB XLC \
      VGK SMH XBI XRT XME SLV USO UNG SHOP SMCI SNDK SPCE TSLA VRT WULF WYFI SEI TE)
for S in $SYMS; do
  [[ -s "data_adj/$S.json" ]] && continue
  ibkr bars "$S" --profile gateway-live --duration "15 Y" --bar-size "1 day" \
      --what-to-show ADJUSTED_LAST --json 2>/dev/null | cat > "data_adj/$S.tmp"
  n=$(python3 -c "
import json;raw=open('data_adj/$S.tmp').read();d=json.loads(raw[raw.index('{'):]);print(len(d['rows']))" 2>/dev/null || echo 0)
  if [ "$n" -gt 200 ]; then mv "data_adj/$S.tmp" "data_adj/$S.json"; echo "ok   $S $n"; else rm -f "data_adj/$S.tmp"; echo "FAIL $S"; fi
  sleep 15
done
echo DONE
