\set ON_ERROR_STOP on

-- Local Compose credentials only. Production provisions the same separation
-- through its secret manager / database control plane.
DO $role$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'narrative_app') THEN
    CREATE ROLE narrative_app LOGIN PASSWORD 'local-app-password'
      NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
  END IF;
END
$role$;

ALTER ROLE narrative_app WITH
  LOGIN PASSWORD 'local-app-password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
GRANT CONNECT ON DATABASE narrative TO narrative_app;
GRANT USAGE ON SCHEMA public TO narrative_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO narrative_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO narrative_app;

ALTER DEFAULT PRIVILEGES FOR ROLE narrative IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO narrative_app;
ALTER DEFAULT PRIVILEGES FOR ROLE narrative IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO narrative_app;
