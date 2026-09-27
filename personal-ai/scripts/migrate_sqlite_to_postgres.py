"""Copy a consistent SQLite snapshot to a NEW PostgreSQL database, validate, then optionally switch .env."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import sys


def canonical(row):
    def convert(value):
        if isinstance(value, datetime):
            return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(timezone.utc).isoformat()
        return value
    return json.dumps({k:convert(v) for k,v in row.items() if k!='embedding'},ensure_ascii=False,sort_keys=True,default=str)


def copy_rows(source, target_engine, metadata):
    """Destination must be empty; all inserts and comparisons share one transaction."""
    from sqlalchemy import Boolean, JSON, select, func, inspect
    from infrastructure.sqlite_types import UTCDateTime, Vector
    source.row_factory=sqlite3.Row
    tables={r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    counts={}
    with target_engine.begin() as target:
        if any(target.execute(select(func.count()).select_from(t)).scalar() for t in metadata.sorted_tables):
            raise ValueError('目标已有数据，拒绝覆盖')
        # Deferring foreign keys permits a memory revision to precede its parent.
        foreign_keys=[]
        for table in metadata.sorted_tables:
            for fk in inspect(target).get_foreign_keys(table.name):
                q=target.dialect.identifier_preparer.quote
                foreign_keys.append((q(table.name),q(fk['name'])))
        for table,name in foreign_keys:
            target.exec_driver_sql(f'ALTER TABLE {table} ALTER CONSTRAINT {name} DEFERRABLE INITIALLY DEFERRED')
        for table in metadata.sorted_tables:
            if table.name not in tables:
                counts[table.name]=0
                continue
            source_rows=[]
            for raw in source.execute('SELECT * FROM "'+table.name+'"'):
                row={}
                for column in table.columns:
                    if column.name not in raw.keys(): continue
                    value=raw[column.name]
                    if value is not None:
                        if isinstance(column.type,UTCDateTime): value=datetime.fromisoformat(value)
                        elif isinstance(column.type,(Vector,JSON)): value=json.loads(value) if isinstance(value,str) else value
                        elif isinstance(column.type,Boolean): value=bool(value)
                    row[column.name]=value
                source_rows.append(row)
            for offset in range(0,len(source_rows),250):
                target.execute(table.insert(),source_rows[offset:offset+250])
            actual=target.execute(select(table)).mappings().all()
            if len(actual)!=len(source_rows): raise ValueError('行数校验失败：'+table.name)
            keys=[c.name for c in table.primary_key]
            copied={tuple(r[k] for k in keys):r for r in actual}
            for row in source_rows:
                match=copied[tuple(row[k] for k in keys)]
                if canonical(row)!=canonical({k:match[k] for k in row}):
                    raise ValueError('内容校验失败：'+table.name)
                if row.get('embedding') is not None:
                    left,right=row['embedding'],match['embedding']
                    right = right or []  # keyword-only [] is stored as SQL NULL
                    if len(left)!=len(right) or any(not math.isclose(a,b,rel_tol=1e-6,abs_tol=1e-7) for a,b in zip(left,right)):
                        raise ValueError('向量校验失败：'+table.name)
            counts[table.name]=len(actual)
        target.exec_driver_sql('SET CONSTRAINTS ALL IMMEDIATE')
        for table,name in foreign_keys:
            target.exec_driver_sql(f'ALTER TABLE {table} ALTER CONSTRAINT {name} NOT DEFERRABLE')
    return counts


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--target-env',type=Path,required=True)
    parser.add_argument('--database',required=True)
    parser.add_argument('--activate',action='store_true')
    args=parser.parse_args()
    if not re.fullmatch(r'personal_ai_[a-z0-9_]+',args.database): parser.error('请使用 personal_ai_ 前缀的新数据库名')
    from dotenv import dotenv_values, set_key
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    url=make_url(dotenv_values(args.target_env).get('DATABASE_URL',''))
    if url.get_backend_name()!='postgresql': parser.error('目标配置必须是 PostgreSQL')
    url=url.set(drivername='postgresql+psycopg',database=args.database)
    source_path=args.source.resolve(strict=True)
    backup=Path('data/backups')/('postgres-switch-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
    backup.mkdir(parents=True)
    with closing(sqlite3.connect(source_path.as_uri()+'?mode=ro',uri=True)) as source:
        if source.execute("SELECT count(*) FROM agent_runs WHERE status='running'").fetchone()[0]:
            raise ValueError('存在运行中的聊天任务，请先停止再迁移')
        with closing(sqlite3.connect(backup/'source.db')) as dest:
            source.backup(dest)
    before=hashlib.sha256((backup/'source.db').read_bytes()).hexdigest()
    admin=create_engine(url.set(database='postgres'),isolation_level='AUTOCOMMIT',connect_args={'connect_timeout':10})
    with admin.connect() as connection:
        if connection.execute(text('SELECT 1 FROM pg_database WHERE datname=:name'),{'name':args.database}).scalar():
            raise ValueError('目标数据库已存在，拒绝覆盖；请选择新的数据库名')
        connection.exec_driver_sql('CREATE DATABASE "'+args.database+'"')
    admin.dispose()
    os.environ['DATABASE_URL']=url.render_as_string(hide_password=False)
    from infrastructure.database import Base,engine,init_db
    init_db()
    with closing(sqlite3.connect(backup/'source.db')) as source:
        counts=copy_rows(source,engine,Base.metadata)
    report={'database':args.database,'source_sha256':before,'rows':counts,'verified':True}
    (backup/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    if args.activate:
        # App must be stopped while copying. Preserve its previous connection.
        import shutil
        shutil.copy2('.env',backup/'previous.env')
        set_key('.env','DATABASE_URL',url.render_as_string(hide_password=False))
    print(json.dumps({'database':args.database,'backup':str(backup),'rows':counts,'activated':args.activate},ensure_ascii=False))
    engine.dispose()


if __name__=='__main__':
    try: main()
    except Exception as exc:
        # Driver errors can include credentials or message parameters.
        print('迁移失败：'+type(exc).__name__+'；原数据库和连接配置保持不变。',file=sys.stderr)
        if isinstance(exc,ValueError): print(str(exc),file=sys.stderr)
        sys.exit(1)
