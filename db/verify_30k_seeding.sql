-- ============================================================================
-- SCRIPT DE VERIFICACIÓN DE SEEDING MASIVO (30,000+ REGISTROS)
-- Dominios: ms-core-hr y ms-payroll (tenant_a, tenant_b, tenant_c)
-- Compatible con PostgreSQL 13+
-- ============================================================================

-- 1. CONTEO EXACTO POR TENANT Y TOTAL ACUMULADO (UNION ALL)
WITH tenant_counts AS (
    SELECT
        'tenant_a'::TEXT AS tenant,
        (SELECT COUNT(*) FROM tenant_a.employees) AS employees_count,
        (SELECT COUNT(*) FROM tenant_a.contracts) AS contracts_count,
        (SELECT COUNT(*) FROM tenant_a.employee_salary_profiles) AS employee_salary_profiles_count,
        (SELECT COUNT(*) FROM tenant_a.pay_slips) AS pay_slips_count
    UNION ALL
    SELECT
        'tenant_b'::TEXT AS tenant,
        (SELECT COUNT(*) FROM tenant_b.employees) AS employees_count,
        (SELECT COUNT(*) FROM tenant_b.contracts) AS contracts_count,
        (SELECT COUNT(*) FROM tenant_b.employee_salary_profiles) AS employee_salary_profiles_count,
        (SELECT COUNT(*) FROM tenant_b.pay_slips) AS pay_slips_count
    UNION ALL
    SELECT
        'tenant_c'::TEXT AS tenant,
        (SELECT COUNT(*) FROM tenant_c.employees) AS employees_count,
        (SELECT COUNT(*) FROM tenant_c.contracts) AS contracts_count,
        (SELECT COUNT(*) FROM tenant_c.employee_salary_profiles) AS employee_salary_profiles_count,
        (SELECT COUNT(*) FROM tenant_c.pay_slips) AS pay_slips_count
)
SELECT
    tenant,
    employees_count,
    contracts_count,
    employee_salary_profiles_count,
    pay_slips_count,
    (employees_count + contracts_count + employee_salary_profiles_count + pay_slips_count) AS total_filas_tenant,
    CASE
        WHEN employees_count >= 10000
         AND contracts_count >= 10000
         AND employee_salary_profiles_count >= 10000
        THEN 'OK (>= 10,000 por tenant)'
        ELSE 'ALERTA (< 10,000)'
    END AS estado_volumen
FROM tenant_counts
UNION ALL
SELECT
    'TOTAL_GLOBAL'::TEXT AS tenant,
    SUM(employees_count) AS employees_count,
    SUM(contracts_count) AS contracts_count,
    SUM(employee_salary_profiles_count) AS employee_salary_profiles_count,
    SUM(pay_slips_count) AS pay_slips_count,
    SUM(employees_count + contracts_count + employee_salary_profiles_count + pay_slips_count) AS total_filas_tenant,
    CASE
        WHEN SUM(employees_count) >= 30000
         AND SUM(contracts_count) >= 30000
         AND SUM(employee_salary_profiles_count) >= 30000
        THEN 'OK (>= 30,000 acumulados)'
        ELSE 'ALERTA (< 30,000)'
    END AS estado_volumen
FROM tenant_counts;


-- 2. AUDITORÍA DE INTEGRIDAD REFERENCIAL Y CERO REGISTROS HUÉRFANOS (UNION ALL)
WITH orphan_checks AS (
    -- tenant_a
    SELECT
        'tenant_a'::TEXT AS tenant,
        (SELECT COUNT(*) FROM tenant_a.employees e
         LEFT JOIN tenant_a.departments d ON e.department_id = d.department_id
         WHERE e.department_id IS NOT NULL AND d.department_id IS NULL) AS employees_sin_departamento,
        (SELECT COUNT(*) FROM tenant_a.contracts c
         LEFT JOIN tenant_a.employees e ON c.employee_id = e.employee_id
         WHERE e.employee_id IS NULL) AS contracts_huerfanos,
        (SELECT COUNT(*) FROM tenant_a.employee_salary_profiles esp
         LEFT JOIN tenant_a.employees e ON esp.employee_id = e.employee_id
         WHERE e.employee_id IS NULL) AS salary_profiles_huerfanos,
        (SELECT COUNT(*) FROM tenant_a.employees e
         LEFT JOIN tenant_a.employee_salary_profiles esp ON e.employee_id = esp.employee_id
         WHERE esp.employee_id IS NULL) AS employees_sin_perfil_salarial,
        (SELECT COUNT(*) FROM tenant_a.pay_slips ps
         LEFT JOIN tenant_a.employees e ON ps.employee_id = e.employee_id
         LEFT JOIN tenant_a.payroll_periods pp ON ps.period_id = pp.period_id
         WHERE e.employee_id IS NULL OR pp.period_id IS NULL) AS pay_slips_huerfanos
    UNION ALL
    -- tenant_b
    SELECT
        'tenant_b'::TEXT AS tenant,
        (SELECT COUNT(*) FROM tenant_b.employees e
         LEFT JOIN tenant_b.departments d ON e.department_id = d.department_id
         WHERE e.department_id IS NOT NULL AND d.department_id IS NULL) AS employees_sin_departamento,
        (SELECT COUNT(*) FROM tenant_b.contracts c
         LEFT JOIN tenant_b.employees e ON c.employee_id = e.employee_id
         WHERE e.employee_id IS NULL) AS contracts_huerfanos,
        (SELECT COUNT(*) FROM tenant_b.employee_salary_profiles esp
         LEFT JOIN tenant_b.employees e ON esp.employee_id = e.employee_id
         WHERE e.employee_id IS NULL) AS salary_profiles_huerfanos,
        (SELECT COUNT(*) FROM tenant_b.employees e
         LEFT JOIN tenant_b.employee_salary_profiles esp ON e.employee_id = esp.employee_id
         WHERE esp.employee_id IS NULL) AS employees_sin_perfil_salarial,
        (SELECT COUNT(*) FROM tenant_b.pay_slips ps
         LEFT JOIN tenant_b.employees e ON ps.employee_id = e.employee_id
         LEFT JOIN tenant_b.payroll_periods pp ON ps.period_id = pp.period_id
         WHERE e.employee_id IS NULL OR pp.period_id IS NULL) AS pay_slips_huerfanos
    UNION ALL
    -- tenant_c
    SELECT
        'tenant_c'::TEXT AS tenant,
        (SELECT COUNT(*) FROM tenant_c.employees e
         LEFT JOIN tenant_c.departments d ON e.department_id = d.department_id
         WHERE e.department_id IS NOT NULL AND d.department_id IS NULL) AS employees_sin_departamento,
        (SELECT COUNT(*) FROM tenant_c.contracts c
         LEFT JOIN tenant_c.employees e ON c.employee_id = e.employee_id
         WHERE e.employee_id IS NULL) AS contracts_huerfanos,
        (SELECT COUNT(*) FROM tenant_c.employee_salary_profiles esp
         LEFT JOIN tenant_c.employees e ON esp.employee_id = e.employee_id
         WHERE e.employee_id IS NULL) AS salary_profiles_huerfanos,
        (SELECT COUNT(*) FROM tenant_c.employees e
         LEFT JOIN tenant_c.employee_salary_profiles esp ON e.employee_id = esp.employee_id
         WHERE esp.employee_id IS NULL) AS employees_sin_perfil_salarial,
        (SELECT COUNT(*) FROM tenant_c.pay_slips ps
         LEFT JOIN tenant_c.employees e ON ps.employee_id = e.employee_id
         LEFT JOIN tenant_c.payroll_periods pp ON ps.period_id = pp.period_id
         WHERE e.employee_id IS NULL OR pp.period_id IS NULL) AS pay_slips_huerfanos
)
SELECT
    tenant,
    employees_sin_departamento,
    contracts_huerfanos,
    salary_profiles_huerfanos,
    employees_sin_perfil_salarial,
    pay_slips_huerfanos,
    CASE
        WHEN (employees_sin_departamento
            + contracts_huerfanos
            + salary_profiles_huerfanos
            + employees_sin_perfil_salarial
            + pay_slips_huerfanos) = 0
        THEN 'OK - 0 REGISTROS HUERFANOS'
        ELSE 'ERROR - INTEGRIDAD COMPROMETIDA'
    END AS estado_integridad
FROM orphan_checks;


-- 3. ASERCIÓN ESTRICTA (Falla si no se cumplen los 30k o existen huérfanos)
DO $$
DECLARE
    v_total_employees BIGINT;
    v_total_profiles BIGINT;
    v_total_orphans BIGINT;
BEGIN
    SELECT
        (SELECT COUNT(*) FROM tenant_a.employees)
      + (SELECT COUNT(*) FROM tenant_b.employees)
      + (SELECT COUNT(*) FROM tenant_c.employees),
        (SELECT COUNT(*) FROM tenant_a.employee_salary_profiles)
      + (SELECT COUNT(*) FROM tenant_b.employee_salary_profiles)
      + (SELECT COUNT(*) FROM tenant_c.employee_salary_profiles)
    INTO v_total_employees, v_total_profiles;

    SELECT
        (SELECT COUNT(*) FROM tenant_a.contracts c LEFT JOIN tenant_a.employees e ON c.employee_id = e.employee_id WHERE e.employee_id IS NULL)
      + (SELECT COUNT(*) FROM tenant_b.contracts c LEFT JOIN tenant_b.employees e ON c.employee_id = e.employee_id WHERE e.employee_id IS NULL)
      + (SELECT COUNT(*) FROM tenant_c.contracts c LEFT JOIN tenant_c.employees e ON c.employee_id = e.employee_id WHERE e.employee_id IS NULL)
      + (SELECT COUNT(*) FROM tenant_a.pay_slips ps LEFT JOIN tenant_a.employees e ON ps.employee_id = e.employee_id WHERE e.employee_id IS NULL)
      + (SELECT COUNT(*) FROM tenant_b.pay_slips ps LEFT JOIN tenant_b.employees e ON ps.employee_id = e.employee_id WHERE e.employee_id IS NULL)
      + (SELECT COUNT(*) FROM tenant_c.pay_slips ps LEFT JOIN tenant_c.employees e ON ps.employee_id = e.employee_id WHERE e.employee_id IS NULL)
    INTO v_total_orphans;

    IF v_total_employees < 30000 OR v_total_profiles < 30000 THEN
        RAISE EXCEPTION 'Verificación fallida: employees=%, salary_profiles=% (se requieren >= 30,000)',
            v_total_employees, v_total_profiles;
    END IF;

    IF v_total_orphans > 0 THEN
        RAISE EXCEPTION 'Verificación fallida: se detectaron % registros huérfanos', v_total_orphans;
    END IF;

    RAISE NOTICE 'VERIFICACIÓN EXITOSA: % empleados, % perfiles salariales y 0 registros huérfanos.',
        v_total_employees, v_total_profiles;
END $$;
