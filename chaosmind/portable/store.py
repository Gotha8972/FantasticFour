"""SQLite run records, application locks, cancellation, and operation journal."""
from contextlib import contextmanager, closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / 'runs.sqlite'
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS runs (
                  id TEXT PRIMARY KEY, application TEXT NOT NULL, profile TEXT NOT NULL,
                  request TEXT NOT NULL, status TEXT NOT NULL, cancelled INTEGER DEFAULT 0,
                  result TEXT, error TEXT);
                CREATE TABLE IF NOT EXISTS locks (application TEXT PRIMARY KEY, run_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                  seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS operations (
                  id TEXT PRIMARY KEY, run_id TEXT NOT NULL, data TEXT NOT NULL);
            ''')

    @contextmanager
    def connection(self):
        with closing(sqlite3.connect(self.path, timeout=30)) as db:
            db.row_factory = sqlite3.Row
            with db:
                yield db

    def create(self, run_id, profile, request):
        with self.connection() as db:
            db.execute('INSERT INTO runs(id,application,profile,request,status) VALUES(?,?,?,?,?)',
                       (run_id, profile['id'], json.dumps(profile), json.dumps(request), 'queued'))

    def get(self, run_id):
        with self.connection() as db:
            row = db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        value = dict(row)
        for k in ('profile', 'request', 'result'):
            value[k] = json.loads(value[k]) if value[k] else None
        return value

    def status(self, run_id, status, result=None, error=None):
        with self.connection() as db:
            db.execute('UPDATE runs SET status=?,result=COALESCE(?,result),error=? WHERE id=?',
                       (status, json.dumps(result) if result is not None else None, error, run_id))

    def cancel(self, run_id):
        self.get(run_id)
        with self.connection() as db:
            db.execute('UPDATE runs SET cancelled=1 WHERE id=?', (run_id,))

    def cancelled(self, run_id):
        return bool(self.get(run_id)['cancelled'])

    def acquire(self, application, run_id):
        with self.connection() as db:
            db.execute('INSERT OR IGNORE INTO locks VALUES(?,?)', (application, run_id))
            owner = db.execute('SELECT run_id FROM locks WHERE application=?', (application,)).fetchone()[0]
            if owner != run_id:
                raise RuntimeError('Another assessment owns this application; recover it before proceeding')

    def release(self, application, run_id):
        with self.connection() as db:
            db.execute('DELETE FROM locks WHERE application=? AND run_id=?', (application, run_id))

    def event(self, run_id, stage, **details):
        event = {'timestamp': datetime.now(timezone.utc).isoformat(), 'stage': stage, **details}
        with self.connection() as db:
            db.execute('INSERT INTO events(run_id,data) VALUES(?,?)', (run_id, json.dumps(event)))

    def events(self, run_id, after=0):
        with self.connection() as db:
            rows = db.execute('SELECT seq,data FROM events WHERE run_id=? AND seq>? ORDER BY seq LIMIT 500',
                              (run_id, after)).fetchall()
        return [{'cursor': r['seq'], **json.loads(r['data'])} for r in rows]

    def operation(self, operation_id):
        with self.connection() as db:
            row = db.execute('SELECT data FROM operations WHERE id=?', (operation_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_operation(self, operation_id, run_id, data):
        with self.connection() as db:
            db.execute('INSERT INTO operations VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',
                       (operation_id, run_id, json.dumps(data)))

    def interrupted(self):
        with self.connection() as db:
            db.execute("UPDATE runs SET status='interrupted' WHERE status IN ('running','queued')")
