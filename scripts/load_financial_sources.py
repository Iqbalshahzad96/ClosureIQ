"""Load an explicit private source manifest through ClosureIQ's Phase 2 service."""
import argparse
import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--database', type=Path, required=True,
                        help='Explicit local SQLite file; never dropped or replaced')
    parser.add_argument('--storage-root', type=Path, required=True,
                        help='Private runtime raw-copy directory')
    parser.add_argument('--initialize', action='store_true',
                        help='Create missing canonical tables; does not migrate existing columns')
    parser.add_argument('--validate-only', action='store_true',
                        help='Validate configuration/references/source paths without database writes')
    args = parser.parse_args(argv)
    # The explicit command target wins over runtime configuration. No default DB
    # is created/used by module imports, including during preflight-only mode.
    import os
    os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
    from sqlalchemy import URL, create_engine, event
    from sqlalchemy.orm import sessionmaker
    from app.database.database import Base
    from app.ingestion.loading import (LoadError, read_plan, resolve_files, load_sources,
                                       verify_canonical, verify_mcp)
    from app.ingestion.storage import RawStorageManager

    engine = None
    try:
        plan = read_plan(args.manifest)
        paths = resolve_files(plan, args.manifest.resolve().parent)
        database = args.database.resolve()
        storage_root = args.storage_root.resolve()
        if database in paths or database == args.manifest.resolve():
            raise ValueError('Database target overlaps input')
        if args.validate_only:
            print(json.dumps({'status': 'VALID_CONFIGURATION', 'source_files': len(paths)}))
            return 0
        if not args.initialize and not database.is_file():
            raise ValueError('Database needs explicit initialization')
        database.parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(URL.create('sqlite', database=str(database)), echo=False, hide_parameters=True)
        @event.listens_for(engine, 'connect')
        def foreign_keys(connection, record):
            connection.execute('PRAGMA foreign_keys=ON')
        if args.initialize:
            Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine)
        result = load_sources(factory, plan, args.manifest.resolve().parent,
                              RawStorageManager(str(storage_root)))
        result['canonical'] = verify_canonical(factory, plan)
        result['mcp'] = asyncio.run(verify_mcp(factory, plan))
        has_issues = bool(result['canonical']['lineage_issues']) or any(
            f['stored_parse_status'] in ('FAILED', 'QUARANTINED') for f in result['files'])
        result['status'] = 'REVIEW_REQUIRED' if has_issues else 'COMPLETED'
        print(json.dumps(result, indent=2))
        return 2 if has_issues else 0
    except LoadError as exc:
        print(json.dumps({'status': 'FAILED', 'message': str(exc)}), file=sys.stderr)
        return 1
    except Exception:
        # Do not emit exception repr, paths, source names, SQL or parameter values.
        print(json.dumps({'status': 'FAILED', 'message':
              'Loading failed. Check the private manifest, schema and source availability; committed earlier files are safe to rerun.'}), file=sys.stderr)
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == '__main__':
    raise SystemExit(main())
