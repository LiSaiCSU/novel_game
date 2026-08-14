\set ON_ERROR_STOP on

-- app_password is supplied by the deployment environment through psql -v.
-- format(%L) quotes it as a SQL literal, so credentials never enter this file.
SELECT format(
  'CREATE ROLE narrative_app LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS',
  :'app_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'narrative_app')
\gexec

SELECT format(
  'ALTER ROLE narrative_app WITH LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS',
  :'app_password'
)
\gexec
GRANT CONNECT ON DATABASE narrative TO narrative_app;
GRANT USAGE ON SCHEMA public TO narrative_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO narrative_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO narrative_app;

ALTER DEFAULT PRIVILEGES FOR ROLE narrative IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO narrative_app;
ALTER DEFAULT PRIVILEGES FOR ROLE narrative IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO narrative_app;
