-- ============================================================================
-- SCRIPT DE MIGRACIÓN 002: Carga de Catálogos Iniciales
-- Inserta departamentos base y el periodo de nómina activo (2026-11) en cada tenant
-- ============================================================================

DO $$
DECLARE
    schema_name TEXT;
    schemas TEXT[] := ARRAY['tenant_a', 'tenant_b', 'tenant_c'];
BEGIN
    FOREACH schema_name IN ARRAY schemas LOOP
        -- Inserción de departamentos iniciales (ms-core-hr)
        EXECUTE format('
            INSERT INTO %I.departments (department_id, name, budget, created_at)
            VALUES
                (gen_random_uuid(), ''Ingeniería'', 150000.00, CURRENT_TIMESTAMP),
                (gen_random_uuid(), ''Recursos Humanos'', 80000.00, CURRENT_TIMESTAMP),
                (gen_random_uuid(), ''Finanzas'', 95000.00, CURRENT_TIMESTAMP),
                (gen_random_uuid(), ''Operaciones'', 110000.00, CURRENT_TIMESTAMP)
            ON CONFLICT (name) DO NOTHING;
        ', schema_name);

        -- Inserción de periodo inicial de nómina (ms-payroll)
        EXECUTE format('
            INSERT INTO %I.payroll_periods (period_id, period_name, is_closed, total_paid, created_at)
            VALUES
                (gen_random_uuid(), ''2026-11'', FALSE, 0.00, CURRENT_TIMESTAMP)
            ON CONFLICT (period_name) DO NOTHING;
        ', schema_name);
    END LOOP;
END $$;
