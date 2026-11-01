import json, os, math
B="/Users/shawn/workspace/portfolio-watcher/ai-infra-bt"
os.chdir(B); import sys; sys.path.insert(0,B)
def load(s):
    raw=open(f"{B}/data_adj/{s}.json").read(); j,_=json.JSONDecoder().raw_decode(raw[raw.index("{"):])
    return {str(x["date"])[:10]: x["close"] for x in j["rows"] if x["close"]}
def dd_stats(eq):
    pk=eq[0]; dd=[]
    for v in eq: pk=max(pk,v); dd.append(v/pk-1)
    return dd
