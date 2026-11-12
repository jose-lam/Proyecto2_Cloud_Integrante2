-- ============================================================================
-- SCRIPT DE MIGRACIÓN 003: Optimización de Consultas e Índices Multi-Tenant
-- Dominios: ms-core-hr y ms-payroll
-- Objetivo: Garantizar tiempos de respuesta < 200ms con 30,000+ registros
-- Compatible con PostgreSQL 13+ (AWS RDS db.t3.micro / db.t4g.micro)
-- ============================================================================

DO $$
DECLARE
    schema_name TEXT;
    schemas TEXT[] := ARRAY['tenant_a', 'tenant_b', 'tenant_c'];
BEGIN
    FOREACH schema_name IN ARRAY schemas LOOP

        -- ====================================================================
        -- ÍNDICES DOMINIO CORE HR (ms-core-hr)
        -- ====================================================================

        -- 1. Acelera filtrado por estado y paginación ordenada por fecha de creación
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS idx_employees_status_created ON %I.employees (status, created_at DESC);',
            schema_name
        );

        -- 2. Optimiza LEFT JOIN y filtros por departamento en employees
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS idx_employees_department ON %I.employees (department_id);',
            schema_name
        );

        -- 3. Optimiza búsquedas y ordenamientos alfabéticos por apellidos y nombres
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS idx_employees_fullname ON %I.employees (last_name, first_name);',
            schema_name
        );

        -- 4. Elimina Seq Scan en LEFT JOIN contracts ON e.employee_id = c.employee_id
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS idx_contracts_employee ON %I.contracts (employee_id);',
            schema_name
        );

        -- ====================================================================
        -- ÍNDICES DOMINIO NÓMINAS (ms-payroll)
        -- ====================================================================

        -- 5. Acelera listado de boletas por periodo de pago ordenadas por emisión
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS idx_payslips_period_generated ON %I.pay_slips (period_id, generated_at DESC);',
            schema_name
        );

        -- 6. Acelera consulta del historial de boletas de un empleado específico
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS idx_payslips_employee ON %I.pay_slips (employee_id);',
            schema_name
        );

        -- 7. Optimiza lectura de licencias no pagadas pendientes durante cálculo de nómina
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS idx_unpaid_leaves_period_applied ON %I.unpaid_leaves_ledger (period_target, applied);',
            schema_name
        );

        -- ====================================================================
        -- ACTUALIZACIÓN DE ESTADÍSTICAS DEL PLANIFICADOR (pg_statistic)
        -- ====================================================================
        EXECUTE format('ANALYZE %I.departments;', schema_name);
        EXECUTE format('ANALYZE %I.employees;', schema_name);
        EXECUTE format('ANALYZE %I.contracts;', schema_name);
        EXECUTE format('ANALYZE %I.employee_salary_profiles;', schema_name);
        EXECUTE format('ANALYZE %I.unpaid_leaves_ledger;', schema_name);
        EXECUTE format('ANALYZE %I.payroll_periods;', schema_name);
        EXECUTE format('ANALYZE %I.pay_slips;', schema_name);

        RAISE NOTICE 'Índices creados y ANALYZE ejecutado exitosamente en esquema: %', schema_name;
    END LOOP;
END $$;

-- ============================================================================
-- CONSULTA DE VERIFICACIÓN DE PLAN DE EJECUCIÓN (Ejecutar manualmente en psql)
-- ============================================================================
-- SET search_path TO tenant_a, public;
-- EXPLAIN ANALYZE
-- SELECT e.employee_id, e.first_name, e.last_name, d.name, c.salary
-- FROM employees e
-- LEFT JOIN departments d ON e.department_id = d.department_id
-- LEFT JOIN contracts c ON e.employee_id = c.employee_id
-- WHERE e.status = 'ACTIVE'
-- ORDER BY e.created_at DESC
-- LIMIT 50 OFFSET 0;
