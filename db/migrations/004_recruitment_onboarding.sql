BEGIN;

DO $migration$
DECLARE
    tenant_schema TEXT;
BEGIN
    FOREACH tenant_schema IN ARRAY
        ARRAY['tenant_a', 'tenant_b', 'tenant_c']
    LOOP
        EXECUTE format(
            'ALTER TABLE %I.employees ALTER COLUMN hire_date DROP NOT NULL',
            tenant_schema
        );

        EXECUTE format(
            'ALTER TABLE %I.employees ADD COLUMN IF NOT EXISTS source_candidate_id VARCHAR(100)',
            tenant_schema
        );

        EXECUTE format(
            'ALTER TABLE %I.employees DROP CONSTRAINT IF EXISTS employees_status_check',
            tenant_schema
        );

        EXECUTE format(
            'ALTER TABLE %I.employees ADD CONSTRAINT employees_status_check CHECK (status IN (''ACTIVE'', ''INACTIVE'', ''ON_LEAVE'', ''PENDING_ONBOARDING''))',
            tenant_schema
        );

        EXECUTE format(
            'CREATE UNIQUE INDEX IF NOT EXISTS %I ON %I.employees (source_candidate_id) WHERE source_candidate_id IS NOT NULL',
            'idx_employees_source_candidate_id',
            tenant_schema
        );
    END LOOP;
END
$migration$;

COMMIT;
