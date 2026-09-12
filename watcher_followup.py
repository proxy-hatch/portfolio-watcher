#!/usr/bin/env python3
"""Provider-aware interactive followup for the latest or selected watcher run."""
import argparse
import json
import os
from pathlib import Path
import sys
from codex_agent import agent_env, run_agent
from watcher import load_config
from watcher_state import locked, update_metadata

ROOT=Path(__file__).resolve().parent


def context(root, data):
    prefix=Path(data['artifact_prefix'])
    sections=['Watcher run context. This historical packet is not a new trade authorization. '
              'Do not place, modify or cancel orders until the present user asks you to act. '
              'Refresh broker state before acting; never replay a historical plan automatically. '
              'Use ib_async for authorized writes, SMART routing and writer clientId=1; wait if busy. '
              'Resume assistance with a concise factual summary, then wait for the user. '
              'Approved playbook parameters must not be changed without explicit sign-off.',
              'METADATA\n'+json.dumps(data,indent=2)]
    for suffix in ['targets.json','plan.txt','evidence.json','exec.txt','weekly.md']:
        path=Path(str(prefix)+'.'+suffix)
        sections.append(f'{path}\n'+(path.read_text() if path.exists() else 'Unavailable'))
    sections.append('Execution audit (authoritative for submitted orders, not proof of fills): '+str(Path(root)/'state/orders-audit.jsonl'))
    return '\n\n'.join(sections)


def bootstrap(root,config,data,safe):
    prefix=Path(data['artifact_prefix'])
    # Tool-free seed, without output schema. Interactive resume uses normal Codex
    # tools/config and is not trapped in the verdict-only conversation.
    result=run_agent(context(root,data),Path(str(prefix)+('-safe' if safe else '')+'-followup'),
                     None,config,effort=config['followup_effort'],timeout=180,retries=0)
    return result['session_id']


def prepare(root,config,kind,sid,safe,extra):
    root=Path(root)
    if sid is None: sid=(root/'state'/f'last-{kind}-session').read_text().strip()
    # IDs are local identifiers, never path fragments supplied to a shell.
    if not sid or '/' in sid or '\\' in sid or '..' in sid: raise ValueError('invalid session/run ID')
    path=root/'state/runs'/f'{sid}.json'
    if not path.exists():
        args=['/opt/homebrew/bin/claude','-r',sid,'--model','claude-opus-5']
        if not safe: args.append('--dangerously-skip-permissions')
        return args+extra
    data=json.loads(path.read_text())
    if data.get('provider')!='codex' or data.get('kind')!=kind:
        raise ValueError('run provider/kind mismatch')
    field='safe_followup_session_id' if safe else 'followup_session_id'
    with locked(str(path)+'.followup.lock'):
        data=json.loads(path.read_text())
        if not data.get(field):
            if data.get('outcome')=='RUNNING':
                raise ValueError('Trading pass is still running; reconnect after its outcome is recorded.')
            print('Preparing Astra followup context ...',file=sys.stderr,flush=True)
            thread=bootstrap(root,config,data,safe)
            data=update_metadata(path,{field:thread})
    args=[config['codex_bin'],'resume',data[field],'-m',config['model'],
          '-c','model_reasoning_effort='+json.dumps(config['followup_effort']),
          '-c','forced_login_method="chatgpt"',
          '-C',config['vault'],'--add-dir',str(root),'--no-alt-screen']
    if safe: args+=['--sandbox','workspace-write','--ask-for-approval','on-request']
    else: args+=['--dangerously-bypass-approvals-and-sandbox']
    # Always refresh metadata (report may have finished since the seed was made).
    args+=extra+[context(root,data)]
    return args


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('kind',choices=['daily','weekly'],nargs='?',default='daily')
    p.add_argument('--safe','-s',action='store_true')
    p.add_argument('--yolo','-y',action='store_true')
    p.add_argument('--sid')
    args,extra=p.parse_known_args()
    if args.safe and args.yolo: p.error('--safe and --yolo are mutually exclusive')
    config=load_config(ROOT)
    try: command=prepare(ROOT,config,args.kind,args.sid,args.safe,extra)
    except Exception as exc:
        print(f'Cannot open watcher followup: {exc}',file=sys.stderr);return 1
    os.chdir(config['vault'])
    env=agent_env()
    if command[0].endswith('/claude'): env['MAX_THINKING_TOKENS']='32000'
    os.execve(command[0],command,env)


if __name__=='__main__':sys.exit(main())
