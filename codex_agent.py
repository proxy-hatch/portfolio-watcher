"""Bounded Codex CLI calls using saved ChatGPT auth; no trading code."""
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

VERDICT_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'properties': {'verdict': {'type': 'string', 'enum': ['APPROVE', 'HALT']},
                   'reason': {'type': 'string'}, 'plan_sha256': {'type': 'string'}},
    'required': ['verdict', 'reason', 'plan_sha256'],
}
# Explicitly strip execution, discovery and persistence tools from unattended agents.
# Web search is enabled ONLY for evidence collection / weekly reporting.
DISABLED = ('shell_tool', 'unified_exec', 'code_mode', 'code_mode_host', 'apps',
            'plugins', 'hooks', 'browser_use', 'browser_use_external', 'computer_use',
            'image_generation', 'multi_agent', 'multi_agent_v2', 'goals', 'sleep_tool',
            'skill_search', 'memories', 'shell_snapshot', 'view_image',
            'workspace_dependencies', 'tool_suggest', 'unbounded_connection_retries')


class AgentError(RuntimeError):
    def __init__(self, category, detail):
        super().__init__(detail)
        self.category = category


def agent_env():
    # A Codex desktop turn may export its own runtime/API settings. Scheduled runs
    # deliberately use only the user's default saved ChatGPT login.
    keep = ('HOME', 'USER', 'LOGNAME', 'PATH', 'TMPDIR', 'LANG', 'LC_ALL', 'TERM', 'SHELL')
    return {k: v for k, v in os.environ.items() if k in keep}


def classify(detail):
    s = detail.lower()
    if any(w in s for w in ('401', 'unauthorized', 'refresh token', 'not logged in', 'authentication')):
        return 'auth'
    if any(w in s for w in ('429', 'usage limit', 'rate limit', 'quota', 'credits')):
        return 'quota'
    if any(w in s for w in ('502', '503', '504', 'connection reset', 'stream disconnected', 'connection closed', 'temporarily unavailable')):
        return 'api'
    return 'model'


def stop_group(proc):
    # Always address the group, even if the group leader already exited.
    try: os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError: pass
    try: proc.wait(timeout=2)
    except subprocess.TimeoutExpired: pass
    try: os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError: pass
    proc.wait()


def run_process(command, prompt, prefix, timeout, env=None):
    prefix = Path(prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    with prefix.with_suffix('.jsonl').open('w') as out, prefix.with_suffix('.err').open('w') as err:
        try:
            proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=out, stderr=err,
                                    text=True, start_new_session=True, env=env)
        except OSError as exc:
            raise AgentError('model', str(exc)) from exc
        try:
            proc.communicate(prompt, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            stop_group(proc)
            prefix.with_suffix('.timedout').touch()
            raise AgentError('timeout', f'deadline exceeded ({timeout}s)') from exc
        except BaseException:
            stop_group(proc)
            raise
        finally:
            # No background children survive a bounded model or command step.
            stop_group(proc)
    return proc.returncode, time.monotonic() - start


def check_events(events, web=False):
    sid = None
    completed = False
    allowed = {'agent_message', 'reasoning', 'plan'}
    if web: allowed.add('web_search')
    for e in events:
        kind = e.get('type')
        if kind == 'thread.started': sid = e.get('thread_id')
        if kind == 'turn.completed': completed = True
        if kind in ('turn.failed', 'error'):
            detail = json.dumps(e)
            raise AgentError(classify(detail), detail[:1000])
        if kind in ('item.started', 'item.updated', 'item.completed'):
            typ = e.get('item', {}).get('type')
            if typ not in allowed:
                raise AgentError('invalid', f'unexpected tool/item in scheduled agent: {typ}')
    if not sid or not completed:
        raise AgentError('invalid', 'missing thread.started or turn.completed')
    return sid


def validate_verdict(value, digest):
    if not isinstance(value, dict) or set(value) != {'verdict', 'reason', 'plan_sha256'}:
        raise AgentError('invalid', 'invalid verdict fields')
    if value['verdict'] not in ('APPROVE', 'HALT') or value['plan_sha256'] != digest:
        raise AgentError('invalid', 'invalid verdict or plan hash mismatch')
    if not isinstance(value['reason'], str) or not value['reason'].strip():
        raise AgentError('invalid', 'missing verdict reason')
    return value


def restricted_catalog(model):
    model = dict(model)
    model.update(tool_mode='standard', apply_patch_tool_type=None,
                 experimental_supported_tools=[], node_repl_disabled=True)
    return model


def write_catalog(config, path):
    # Preserve vendor model instructions and reasoning metadata, changing only the
    # tool catalog. Astra otherwise forces Code Mode even when its host is disabled.
    try:
        result = subprocess.run([config['codex_bin'], '-c', 'forced_login_method="chatgpt"', 'debug', 'models'],
                                capture_output=True, text=True, timeout=30, env=agent_env())
        if result.returncode: raise ValueError('model catalog command failed')
        models = json.loads(result.stdout)['models']
        model = next(m for m in models if m['slug'] == config['model'])
        Path(path).write_text(json.dumps({'models': [restricted_catalog(model)]}))
    except (OSError, ValueError, KeyError, StopIteration, subprocess.TimeoutExpired) as exc:
        raise AgentError('model', 'cannot resolve exact model catalog: ' + str(exc)) from exc


def command(config, cwd, schema, output, effort, web):
    args = [config['codex_bin'], 'exec', '--ignore-user-config', '--strict-config',
            '--ignore-rules', '--skip-git-repo-check', '-C', str(cwd),
            '--sandbox', 'read-only', '-m', config['model'], '--json',
            '-o', str(output)]
    if schema is not None: args += ['--output-schema', str(schema)]
    values = {'forced_login_method': 'chatgpt', 'model_provider': 'openai', 'model_reasoning_effort': effort,
              'approval_policy': 'never', 'project_doc_max_bytes': 0,
              'skills.include_instructions': False, 'agents.enabled': False,
              'tools.experimental_request_user_input.enabled': False,
              'tools.update_plan.enabled': False,
              'model_catalog_json': str(output.with_suffix('.catalog.json')),
              'web_search': 'live' if web else 'disabled', 'mcp_servers': {},
              'developer_instructions': 'This is a bounded unattended task. Use only the supplied packet and explicitly available web search. Finish with the requested structured output. Do not monitor, sleep, delegate, ask questions or pursue followup tasks.'}
    for key, value in values.items():
        encoded = '{}' if value == {} else json.dumps(value)
        args += ['-c', f'{key}={encoded}']
    for feature in DISABLED: args += ['--disable', feature]
    return args + ['-']


def attempt(prompt, prefix, schema, config, timeout=300, effort='medium', web=False):
    prefix = Path(prefix).resolve()
    prefix.parent.mkdir(parents=True, exist_ok=True)
    schema_path = prefix.with_suffix('.schema.json')
    output = prefix.with_suffix('.output.json')
    schema_path.write_text(json.dumps(schema))
    output.unlink(missing_ok=True)
    prefix.with_suffix('.prompt.txt').write_text(prompt)
    write_catalog(config, output.with_suffix('.catalog.json'))
    # Temporary root prevents repository config discovery; project instructions are
    # disabled and all needed strategy text is explicitly supplied in the packet.
    with tempfile.TemporaryDirectory(prefix='watcher-agent-') as td:
        args = command(config, td, schema_path if schema is not None else None, output, effort, web)
        rc, elapsed = run_process(args, prompt, prefix, timeout, agent_env())
    raw = prefix.with_suffix('.jsonl').read_text()
    try: events = [json.loads(line) for line in raw.splitlines() if line.strip()]
    except ValueError as exc: raise AgentError('invalid', 'invalid Codex JSONL') from exc
    if rc:
        detail = prefix.with_suffix('.err').read_text() + raw
        raise AgentError(classify(detail), f'Codex exited {rc}: {detail[-1500:]}')
    sid = check_events(events, web)
    try: value = json.loads(output.read_text()) if schema is not None else output.read_text()
    except (OSError, ValueError) as exc: raise AgentError('invalid', 'missing/invalid final output') from exc
    return {'session_id': sid, 'output': value, 'elapsed_seconds': round(elapsed, 2),
            'events_path': str(prefix.with_suffix('.jsonl')),
            'usage': next((e.get('usage', {}) for e in reversed(events) if e.get('type') == 'turn.completed'), {})}


def run_agent(prompt, prefix, schema, config, retries=1, **kwargs):
    for n in range(retries + 1):
        try:
            result = attempt(prompt, Path(str(prefix) + f'-attempt{n+1}'), schema, config, **kwargs)
            result['attempts'] = n+1
            return result
        except AgentError as exc:
            if exc.category not in ('timeout', 'api') or n == retries: raise
