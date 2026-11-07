"""Shared account-backed raw match statistics, independent of game wire formats.

Only authenticated workers call record(). Native rating/skill formulas are not
invented here. Boards expose raw totals, scoped by product and optional mode.
"""
from __future__ import annotations
from contextlib import closing
from dataclasses import dataclass
import hashlib,json,re,sqlite3,time
from pathlib import Path
from .accounts import initialize_database

SCHEMA='tubisoft-match-result-v1'
COUNTERS=('kills','deaths','team_kills','suicides','shots','hits','play_ms','rounds_won')
TOKEN=re.compile(r'[A-Za-z0-9_.:-]{1,96}')


class LadderError(ValueError):pass
class ConflictingReport(LadderError):pass
class UnknownAccount(LadderError):pass


def number(value,high=0x7fffffff):
    if type(value)is not int or not 0<=value<=high:raise LadderError('Bounded nonnegative statistic required')
    return value


def token(value):
    if not isinstance(value,str) or TOKEN.fullmatch(value)is None:raise LadderError('Invalid result identity')
    return value


def normalize(document):
    fields={'schema','product','mode','worker','match','round','winner','ranked','players'}
    if not isinstance(document,dict)or set(document)!=fields or document['schema']!=SCHEMA:
        raise LadderError('Exact result schema required')
    result={name:token(document[name])for name in('product','mode','worker','match')}
    result.update(schema=SCHEMA,round=number(document['round']))
    if result['round']==0:raise LadderError('Positive round required')
    if document['winner']is not None and (type(document['winner'])is not int or document['winner']not in(2,3)):raise LadderError('Winner must be Alpha, Bravo or draw')
    if type(document['ranked'])is not bool:raise LadderError('Explicit ranked decision required')
    if not isinstance(document['players'],list)or not 1<=len(document['players'])<=16:
        raise LadderError('Bounded participant list required')
    players=[];accounts=set();slots=set()
    for row in document['players']:
        if not isinstance(row,dict)or set(row)!={'slot','account','team','stats'}:raise LadderError('Exact participant schema required')
        slot=number(row['slot'],15)
        if slot in slots:raise LadderError('Duplicate participant slot')
        slots.add(slot);account=row['account']
        if account is not None:
            if (not isinstance(account,str)or not 1<=len(account)<=128
                    or any(ord(c)<32 or ord(c)==127 for c in account)):raise LadderError('Invalid account identity')
            account=account.casefold()
            if account in accounts:raise LadderError('Duplicate account participant')
            accounts.add(account)
        if type(row['team'])is not int or row['team']not in(2,3):raise LadderError('Combat participant team required')
        if not isinstance(row['stats'],dict)or set(row['stats'])!=set(COUNTERS):raise LadderError('Exact counter schema required')
        players.append(dict(slot=slot,account=account,team=row['team'],stats={k:number(row['stats'][k])for k in COUNTERS}))
    if document['ranked']and(any(p['account']is None for p in players)or {p['team']for p in players}!={2,3}):
        raise LadderError('Ranked rounds require verified accounts on both sides')
    result.update(winner=document['winner'],ranked=document['ranked'],players=sorted(players,key=lambda p:p['slot']))
    return result


@dataclass(frozen=True)
class RecordReceipt:
    inserted:bool
    credited:bool


class LadderStore:
    def __init__(self,path:Path):
        self.path=Path(path);initialize_database(self.path)
        with self.connection()as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS ladder_schema(component TEXT PRIMARY KEY,version INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS ladder_events(
                  worker TEXT NOT NULL,match_id TEXT NOT NULL,round_no INTEGER NOT NULL,
                  product TEXT NOT NULL,mode TEXT NOT NULL,digest TEXT NOT NULL,ranked INTEGER NOT NULL,
                  winner INTEGER,created_at INTEGER NOT NULL,payload TEXT NOT NULL,
                  PRIMARY KEY(worker,match_id,round_no));
                CREATE TABLE IF NOT EXISTS ladder_results(
                  worker TEXT NOT NULL,match_id TEXT NOT NULL,round_no INTEGER NOT NULL,slot INTEGER NOT NULL,
                  account TEXT,team INTEGER NOT NULL,kills INTEGER NOT NULL,deaths INTEGER NOT NULL,
                  team_kills INTEGER NOT NULL,suicides INTEGER NOT NULL,shots INTEGER NOT NULL,hits INTEGER NOT NULL,
                  play_ms INTEGER NOT NULL,rounds_won INTEGER NOT NULL,
                  PRIMARY KEY(worker,match_id,round_no,slot),FOREIGN KEY(account)REFERENCES accounts(name_key),
                  FOREIGN KEY(worker,match_id,round_no)REFERENCES ladder_events(worker,match_id,round_no));
                CREATE INDEX IF NOT EXISTS ladder_account_results ON ladder_results(account);
                CREATE INDEX IF NOT EXISTS ladder_event_boards ON ladder_events(product,ranked,mode);
            """)
            row=db.execute("SELECT version FROM ladder_schema WHERE component='match-results'").fetchone()
            if row is not None and row[0]!=1:raise LadderError('Unknown ladder schema version')
            db.execute("INSERT OR IGNORE INTO ladder_schema VALUES('match-results',1)")
            db.commit()

    def connection(self):
        db=sqlite3.connect(self.path,timeout=10)
        db.execute('PRAGMA foreign_keys=ON')
        return closing(db)

    def record(self,document):
        value=normalize(document);raw=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True)
        digest=hashlib.sha256(raw.encode()).hexdigest();identity=(value['worker'],value['match'],value['round'])
        with self.connection()as db:
            try:
                db.execute('BEGIN IMMEDIATE')
                old=db.execute('SELECT digest,ranked FROM ladder_events WHERE worker=? AND match_id=? AND round_no=?',identity).fetchone()
                if old is not None:
                    if old[0]!=digest:raise ConflictingReport('Result identity already has different content')
                    db.rollback();return RecordReceipt(False,bool(old[1]))
                for row in value['players']:
                    if row['account']is not None and db.execute('SELECT 1 FROM accounts WHERE name_key=?',(row['account'],)).fetchone()is None:
                        raise UnknownAccount('Result account does not exist')
                db.execute('INSERT INTO ladder_events VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (*identity,value['product'],value['mode'],digest,int(value['ranked']),value['winner'],int(time.time()),raw))
                for row in value['players']:
                    db.execute('INSERT INTO ladder_results VALUES('+','.join('?'for _ in range(14))+')',
                        (*identity,row['slot'],row['account'],row['team'],*(row['stats'][k]for k in COUNTERS)))
                db.commit()
            except Exception:db.rollback();raise
        return RecordReceipt(True,value['ranked'])

    def leaderboard(self,product,*,mode=None,limit=100,offset=0):
        token(product)
        if mode is not None:token(mode)
        number(offset,100000);number(limit,100)
        if limit==0:raise LadderError('Positive board limit required')
        where='e.ranked=1 AND e.product=? AND r.account IS NOT NULL';args=[product]
        if mode is not None:where+=' AND e.mode=?';args.append(mode)
        sums=','.join('SUM(r.'+k+') AS '+k for k in COUNTERS)
        sql=('SELECT r.account,a.name,COUNT(*) AS rounds_played,'+sums+',SUM(CASE WHEN e.winner=r.team THEN 1 ELSE 0 END) AS team_wins '
             'FROM ladder_results r JOIN ladder_events e USING(worker,match_id,round_no) JOIN accounts a ON a.name_key=r.account '
             'WHERE '+where+' GROUP BY r.account ORDER BY team_wins DESC,kills DESC,deaths ASC,r.account ASC LIMIT ? OFFSET ?')
        with self.connection()as db:
            cursor=db.execute(sql,(*args,limit,offset));names=[c[0]for c in cursor.description]
            rows=[dict(zip(names,row))for row in cursor.fetchall()]
        return [dict(rank=offset+i+1,**row)for i,row in enumerate(rows)]

    def account_statistics(self,account,product,*,mode=None):
        token(product)
        if not isinstance(account,str)or not account:raise LadderError('Account identity required')
        if mode is not None:token(mode)
        where='e.ranked=1 AND e.product=? AND r.account IS NOT NULL';args=[product]
        if mode is not None:where+=' AND e.mode=?';args.append(mode)
        sums=','.join('SUM(r.'+k+') AS '+k for k in COUNTERS)
        sql=('WITH totals AS (SELECT r.account,a.name,COUNT(*) AS rounds_played,'+sums+
             ',SUM(CASE WHEN e.winner=r.team THEN 1 ELSE 0 END) AS team_wins FROM ladder_results r '
             'JOIN ladder_events e USING(worker,match_id,round_no) JOIN accounts a ON a.name_key=r.account WHERE '+where+
             ' GROUP BY r.account), ranked AS (SELECT ROW_NUMBER() OVER(ORDER BY team_wins DESC,kills DESC,deaths ASC,account ASC) AS rank,* FROM totals) '
             'SELECT * FROM ranked WHERE account=?')
        with self.connection()as db:
            cursor=db.execute(sql,(*args,account.casefold()));row=cursor.fetchone()
            return None if row is None else dict(zip((c[0]for c in cursor.description),row))
