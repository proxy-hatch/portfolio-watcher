"""Read-only, bounded current-halt evidence for the model review packet."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import subprocess
import sys
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

HALTS_URL='https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts'
NS='{http://www.nasdaqtrader.com/}'
MAX_FEED_BYTES=2_000_000
FETCH_CODE='''import sys, urllib.request
with urllib.request.urlopen(sys.argv[1],timeout=float(sys.argv[3])) as response:
    body=response.read(int(sys.argv[2])+1)
sys.stdout.buffer.write(body)
'''


def normalized(symbol): return symbol.replace(' ','').replace('.','').replace('-','').upper()


def parse_halts(xml,symbols,at=None):
    at=at or datetime.now(timezone.utc)
    channel=ET.fromstring(xml).find('channel')
    if channel is None: raise ValueError('halt feed has no channel')
    published=parsedate_to_datetime(channel.findtext('pubDate'))
    items=channel.findall('item')
    if int(channel.findtext(NS+'numItems'))!=len(items): raise ValueError('incomplete halt feed')
    result={'source':HALTS_URL,'retrieved_at':at.isoformat(),'published_at':published.isoformat(),
            'status':'checked','matches':[],'active_symbols':[],'not_listed':[],
            'scope':'NasdaqTrader published halt feed. Absence means not listed in this feed, not universal proof of no halt.'}
    age=(at-published).total_seconds()
    if age>900 or age < -120:
        result.update(status='unknown',error='halt feed timestamp is stale or in the future')
        return result
    lookup={normalized(s):s for s in symbols}
    matched=set()
    for item in items:
        symbol=(item.findtext(NS+'IssueSymbol') or '').strip()
        if not symbol: raise ValueError('halt feed item has no symbol')
        if normalized(symbol) not in lookup: continue
        original=lookup[normalized(symbol)];matched.add(original)
        row={k:(item.findtext(NS+k) or '').strip() for k in ('HaltDate','HaltTime','ReasonCode','ResumptionDate','ResumptionTradeTime')}
        row['symbol']=original
        resumed=False
        if row['ResumptionDate'] and row['ResumptionTradeTime']:
            try:
                value=row['ResumptionDate']+' '+row['ResumptionTradeTime'].split('.')[0]
                resume=datetime.strptime(value,'%m/%d/%Y %H:%M:%S').replace(tzinfo=ZoneInfo('America/New_York'))
                resumed=resume<=at
            except ValueError: pass
        row['resumed']=resumed
        result['matches'].append(row)
        if not resumed: result['active_symbols'].append(original)
    result['active_symbols']=sorted(set(result['active_symbols']))
    result['not_listed']=sorted(set(symbols)-matched)
    if result['active_symbols']:result['status']='halt'
    return result


def fetch_halts(symbols,artifact,total_timeout=20,socket_timeout=15,url=HALTS_URL):
    try:
        result=subprocess.run([sys.executable,'-c',FETCH_CODE,url,str(MAX_FEED_BYTES),str(socket_timeout)],
                              capture_output=True,timeout=total_timeout)
        if result.returncode:
            raise ValueError('halt feed fetch failed: '+result.stderr.decode(errors='replace')[-500:])
        body=result.stdout
        if len(body)>MAX_FEED_BYTES:raise ValueError('halt feed exceeded size bound')
        artifact.write_bytes(body)
        return parse_halts(body,symbols)
    except subprocess.TimeoutExpired:
        return {'status':'unknown','source':url,'error':f'halt feed total deadline exceeded ({total_timeout}s)',
                'retrieved_at':datetime.now(timezone.utc).isoformat()}
    except Exception as exc:
        return {'status':'unknown','source':url,'error':str(exc),
                'retrieved_at':datetime.now(timezone.utc).isoformat()}


def assess_evidence(evidence,symbols,catalysts,halt_feed):
    """Combine independent evidence without ever downgrading an identified halt."""
    value=dict(evidence)
    rows=value.get('symbols',[])
    halt_findings=[]
    if value.get('status')=='halt':
        halt_findings.append(value.get('summary') or 'Evidence review identified a material execution risk.')
    for row in rows:
        if row.get('status')=='halt':
            halt_findings.append(f"{row.get('symbol','unknown')}: {row.get('finding') or 'material execution risk'}")
    if halt_feed.get('status')=='halt':
        active=halt_feed.get('active_symbols',[])
        halt_findings.append('Active published halt'+((': '+', '.join(active)) if active else ' in the current halt feed.'))

    if halt_findings:
        value['status']='halt'
        value['summary']='; '.join(dict.fromkeys(halt_findings))
    else:
        gaps=[]
        if value.get('status')!='clear':
            gaps.append(value.get('summary') or 'Evidence review did not establish clear coverage.')
        if len(rows)!=len(symbols) or {row.get('symbol') for row in rows}!=set(symbols):
            gaps.append('Evidence response did not cover every planned symbol.')
        for row in rows:
            sources=row.get('sources') or []
            if row.get('status')!='clear':
                gaps.append(f"{row.get('symbol','unknown')}: {row.get('finding') or 'risk status is unknown'}")
            if not sources or any(not isinstance(url,str) or not url.startswith('https://') for url in sources):
                gaps.append(f"{row.get('symbol','unknown')}: direct source coverage is incomplete.")
        if catalysts.get('error') or catalysts.get('calendar_stale'):
            gaps.append('Catalyst collection is unavailable or stale.')
        if halt_feed.get('status')!='checked':
            gaps.append('Current halt feed could not be verified.')
        value['status']='unknown' if gaps else 'clear'
        if gaps:value['summary']='; '.join(dict.fromkeys(gaps))

    value['halt_feed']=halt_feed
    value['catalysts']=catalysts
    return value
