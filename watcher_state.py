"""Watcher-owned run identities, atomic metadata, legacy-compatible history."""
from contextlib import contextmanager
from datetime import datetime
import fcntl
import json
from pathlib import Path
import os
import tempfile
import uuid
from zoneinfo import ZoneInfo


def now():
    return datetime.now(ZoneInfo('Asia/Taipei'))


def atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


@contextmanager
def locked(path, blocking=True):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as f:
        fcntl.flock(f, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        try: yield
        finally: fcntl.flock(f, fcntl.LOCK_UN)


def update_metadata(path, changes):
    path = Path(path)
    with locked(str(path) + '.lock'):
        data = json.loads(path.read_text()) if path.exists() else {}
        data.update(changes)
        atomic_write(path, json.dumps(data, indent=2) + '\n')
    return data


class Run:
    def __init__(self, root, config, kind, shadow):
        self.root, self.config, self.kind, self.shadow = Path(root), config, kind, shadow
        self.state = self.root/'state'/('shadow' if shadow else '')
        started = now()
        rid = str(uuid.uuid4())
        self.prefix = self.root/'logs'/('shadow' if shadow else '')/f'{kind}-{started:%Y%m%d-%H%M%S}-{rid[:8]}'
        self.prefix.parent.mkdir(parents=True, exist_ok=True)
        self.path = self.state/'runs'/f'{rid}.json'
        self.data = {'schema_version':1, 'run_id':rid, 'provider':'codex', 'kind':kind,
                     'started_at':started.isoformat(), 'label':f'{kind}-{started:%Y-%m-%d-%H%M}',
                     'outcome':'RUNNING', 'shadow':shadow, 'artifact_prefix':str(self.prefix),
                     'model':config.get('model','gpt-6-astra'), 'report_status':'NOT-SCHEDULED'}
        self.save()
        atomic_write(self.state/f'last-{kind}-session', rid + '\n')
        self.stamp()

    def artifact(self, suffix):
        return Path(str(self.prefix) + '.' + suffix)

    def save(self):
        # Merge under lock so interactive followup session IDs are not lost while
        # a long weekly report updates its own fields.
        self.data = update_metadata(self.path, self.data)

    def stamp(self):
        tsv = self.state/'sessions.tsv'
        with locked(self.state/'sessions.lock'):
            rows = tsv.read_text().splitlines() if tsv.exists() else []
            replacement = '\t'.join([self.data['started_at'],self.kind,self.data['run_id'],
                                      self.data['label'],self.data['outcome']])
            found = False
            for i, row in enumerate(rows):
                fields = row.split('\t')
                if len(fields) >= 3 and fields[2] == self.data['run_id']:
                    rows[i] = replacement; found = True
            if not found: rows.append(replacement)
            atomic_write(tsv, '\n'.join(rows) + '\n')

    def say(self, text):
        line = f'{now():%H:%M:%S} {self.kind} {self.data["run_id"][:8]} {text}'
        print(line, flush=True)
        with (self.prefix.parent/f'{self.kind}.log').open('a') as f: f.write(line+'\n')
