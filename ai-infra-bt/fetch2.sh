#!/bin/zsh
cd "$(dirname "$0")/data"
# Cross-asset + sector ETF set: the diversification the single-name sleeve lacks.
SYMS=(SPY QQQ IWM MDY EFA EEM VGK EWJ EWZ TLT IEF SHY LQD HYG TIP AGG \
      GLD SLV DBC USO UNG DBA UUP FXE FXY VNQ IYR \
      XLK XLE XLF XLV XLI XLY XLP XLU XLB XLC SMH XBI ITB IBB KRE OIH XME XRT)
for S in $SYMS; do
  [[ -s "$S.json" ]] && { echo "skip $S"; continue; }
  ibkr bars "$S" --profile gateway-live --duration "20 Y" --bar-size "1 day" --json 2>/dev/null | cat > "$S.tmp"
  if grep -q '"rows"' "$S.tmp"; then mv "$S.tmp" "$S.json"; echo "ok   $S $(python3 -c "
import json;raw=open('$S.json').read();d=json.loads(raw[raw.index('{'):]);r=d['rows'];print(len(r),'bars',str(r[0]['date'])[:10])" 2>/dev/null)"
  else echo "FAIL $S"; rm -f "$S.tmp"; fi
  sleep 0.7
done
