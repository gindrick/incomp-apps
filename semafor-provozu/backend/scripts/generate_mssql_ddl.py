#!/usr/bin/env python3
"""Vygeneruje sql/001_schema_mssql.sql ze schématu v semafor/db.py (po změně schématu spustit znovu)."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy.dialects import mssql  # noqa: E402
from sqlalchemy.schema import CreateIndex, CreateTable  # noqa: E402

from semafor.db import metadata  # noqa: E402

dialect = mssql.dialect()
dialect.deprecate_large_types = True
out = ["-- Semafor Provozu: schéma pro MS SQL Server 2016+ / Azure SQL (vygenerováno scripts/generate_mssql_ddl.py).",
       "-- Aplikace chybějící tabulky zakládá sama (python -m semafor db-init). Tento skript je pro DBA, pokud",
       "-- servisní účet nemá mít právo CREATE TABLE; pak mu stačí db_datareader + db_datawriter.",
       "", "SET ANSI_NULLS ON;", "SET QUOTED_IDENTIFIER ON;", "GO", ""]
for t in metadata.sorted_tables:
    out.append(f"IF OBJECT_ID(N'dbo.{t.name}', N'U') IS NULL")
    out.append("BEGIN")
    out.append(str(CreateTable(t).compile(dialect=dialect)).strip() + ";")
    for ix in sorted(t.indexes, key=lambda i: i.name):
        out.append(str(CreateIndex(ix).compile(dialect=dialect)).strip() + ";")
    out.append("END")
    out.append("GO\n")
out += ["IF NOT EXISTS (SELECT 1 FROM sp_counters WHERE name = N'docs')",
        "    INSERT INTO sp_counters (name, value) VALUES (N'docs', 0);", "GO", ""]
target = Path(__file__).resolve().parents[1] / "sql" / "001_schema_mssql.sql"
target.write_text("\n".join(out), encoding="utf-8")
print(target)
