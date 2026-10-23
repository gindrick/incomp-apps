-- Semafor Provozu: schéma pro MS SQL Server 2016+ / Azure SQL (vygenerováno scripts/generate_mssql_ddl.py).
-- Aplikace chybějící tabulky zakládá sama (python -m semafor db-init). Tento skript je pro DBA, pokud
-- servisní účet nemá mít právo CREATE TABLE; pak mu stačí db_datareader + db_datawriter.

SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

IF OBJECT_ID(N'dbo.sp_assets', N'U') IS NULL
BEGIN
CREATE TABLE sp_assets (
	id NVARCHAR(64) COLLATE Latin1_General_100_BIN2 NOT NULL, 
	filename NVARCHAR(260) NOT NULL, 
	content_type NVARCHAR(100) NOT NULL, 
	size_bytes BIGINT NOT NULL, 
	sha256 NVARCHAR(64) NOT NULL, 
	data VARBINARY(max) NOT NULL, 
	created_at BIGINT NOT NULL, 
	created_by NVARCHAR(320) NOT NULL, 
	PRIMARY KEY (id)
);
END
GO

IF OBJECT_ID(N'dbo.sp_audit_log', N'U') IS NULL
BEGIN
CREATE TABLE sp_audit_log (
	id BIGINT NOT NULL IDENTITY, 
	at BIGINT NOT NULL, 
	user_id NVARCHAR(64) NOT NULL, 
	user_email NVARCHAR(320) NOT NULL, 
	op NVARCHAR(20) NOT NULL, 
	path NVARCHAR(450) NOT NULL, 
	version INTEGER NULL, 
	bytes INTEGER NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_sp_audit_log_at ON sp_audit_log (at);
CREATE INDEX ix_sp_audit_log_path ON sp_audit_log (path);
END
GO

IF OBJECT_ID(N'dbo.sp_counters', N'U') IS NULL
BEGIN
CREATE TABLE sp_counters (
	name NVARCHAR(50) NOT NULL, 
	value BIGINT NOT NULL, 
	PRIMARY KEY (name)
);
END
GO

IF OBJECT_ID(N'dbo.sp_documents', N'U') IS NULL
BEGIN
CREATE TABLE sp_documents (
	path NVARCHAR(450) COLLATE Latin1_General_100_BIN2 NOT NULL, 
	collection NVARCHAR(400) COLLATE Latin1_General_100_BIN2 NOT NULL, 
	doc_id NVARCHAR(200) COLLATE Latin1_General_100_BIN2 NOT NULL, 
	data NVARCHAR(max) NOT NULL, 
	version INTEGER NOT NULL, 
	seq BIGINT NOT NULL, 
	deleted BIT NOT NULL, 
	created_at BIGINT NOT NULL, 
	updated_at BIGINT NOT NULL, 
	updated_by NVARCHAR(320) NOT NULL, 
	PRIMARY KEY (path)
);
CREATE INDEX ix_sp_documents_collection ON sp_documents (collection, deleted);
CREATE INDEX ix_sp_documents_seq ON sp_documents (seq);
END
GO

IF OBJECT_ID(N'dbo.sp_leases', N'U') IS NULL
BEGIN
CREATE TABLE sp_leases (
	path NVARCHAR(450) COLLATE Latin1_General_100_BIN2 NOT NULL, 
	holder NVARCHAR(200) NOT NULL, 
	expires_at BIGINT NOT NULL, 
	PRIMARY KEY (path)
);
END
GO

IF OBJECT_ID(N'dbo.sp_users', N'U') IS NULL
BEGIN
CREATE TABLE sp_users (
	id NVARCHAR(64) NOT NULL, 
	email NVARCHAR(320) NOT NULL, 
	name NVARCHAR(200) NOT NULL, 
	roles NVARCHAR(400) NOT NULL, 
	first_seen BIGINT NOT NULL, 
	last_seen BIGINT NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_sp_users_email ON sp_users (email);
END
GO

IF NOT EXISTS (SELECT 1 FROM sp_counters WHERE name = N'docs')
    INSERT INTO sp_counters (name, value) VALUES (N'docs', 0);
GO
