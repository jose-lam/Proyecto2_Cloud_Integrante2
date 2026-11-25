\set ON_ERROR_STOP on
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL search_path TO pg_catalog;

-- TOTAL_GLOBAL suma exclusivamente empleados y boletas del seed SQL (60 000).
-- Contratos, perfiles, períodos y departamentos se verifican fuera del total.
DO $verify$
DECLARE
    tenant text;
    namespace constant uuid := 'db5e9d63-39e5-4763-8f62-dc18e22da4ab';
    department_names text[] := ARRAY['Ingeniería','Recursos Humanos','Finanzas','Operaciones'];
    required constant integer := 10000;
    payees constant integer := 1000;
    month_start date;
    period_name text;
    period_id uuid;
    employees bigint;
    contracts bigint;
    profiles bigint;
    departments bigint;
    slips bigint;
    total_slips bigint;
    invalid bigint;
    actual_slips bigint;
    actual_total numeric;
    problems boolean;
    global_principal bigint := 0;
BEGIN
    FOR i IN 1..16 LOOP
        department_names := array_append(department_names, 'HCM Seed 30k ' || lpad(i::text, 2, '0'));
    END LOOP;
    FOREACH tenant IN ARRAY ARRAY['tenant_a','tenant_b','tenant_c'] LOOP
        EXECUTE format($check$
            SELECT count(*) FROM %I.departments d
            JOIN unnest($3) WITH ORDINALITY AS x(name, slot) ON x.name = d.name
            WHERE x.slot <= 4 OR (
                d.department_id = public.uuid_generate_v5($1, $2 || ':department:' || d.name)
                AND d.budget = 100000 AND d.created_at = timestamp '2025-12-31 22:00:00'
            )
        $check$, tenant) INTO departments USING namespace, tenant, department_names;
        IF departments <> 20 THEN
            RAISE EXCEPTION '%: departamentos válidos=%, esperados=20', tenant, departments;
        END IF;

        EXECUTE format($check$
            WITH expected AS (
                SELECT i, public.uuid_generate_v5($1, $2 || ':employee:' || i) AS employee_id,
                       public.uuid_generate_v5($1, $2 || ':contract:' || i) AS contract_id,
                       $4[1 + i %% 20] AS department,
                       (ARRAY['FULL_TIME', 'PART_TIME', 'CONTRACTOR'])[1 + i %% 3] AS contract_type,
                       1800 + 25 * (i %% 400) AS salary
                FROM generate_series(0, $3 - 1) AS i
            )
            SELECT count(e.employee_id), count(c.contract_id), count(p.employee_id),
                   count(*) FILTER (WHERE
                       d.name IS DISTINCT FROM x.department
                       OR e.email IS DISTINCT FROM x.employee_id::text || '@seed.example.invalid'
                       OR e.status IS DISTINCT FROM 'ACTIVE' OR e.source_candidate_id IS NOT NULL
                       OR e.hire_date IS DISTINCT FROM date '2024-01-02'
                       OR c.employee_id IS DISTINCT FROM x.employee_id
                       OR c.start_date IS DISTINCT FROM e.hire_date OR c.end_date IS NOT NULL
                       OR c.contract_type IS DISTINCT FROM x.contract_type
                       OR c.salary IS DISTINCT FROM x.salary OR c.s3_contract_key IS NOT NULL
                       OR p.email IS DISTINCT FROM e.email OR p.hire_date IS DISTINCT FROM e.hire_date
                       OR p.base_salary IS DISTINCT FROM x.salary OR p.is_active IS DISTINCT FROM true
                       OR EXISTS (SELECT 1 FROM %1$I.contracts other
                                  WHERE other.employee_id = x.employee_id AND other.contract_id <> x.contract_id)
                   )
            FROM expected x
            LEFT JOIN %1$I.employees e ON e.employee_id = x.employee_id
            LEFT JOIN %1$I.departments d ON d.department_id = e.department_id
            LEFT JOIN %1$I.contracts c ON c.contract_id = x.contract_id
            LEFT JOIN %1$I.employee_salary_profiles p ON p.employee_id = x.employee_id
        $check$, tenant)
        INTO employees, contracts, profiles, invalid
        USING namespace, tenant, required, department_names;

        IF employees <> required OR contracts <> required OR profiles <> required OR invalid <> 0 THEN
            RAISE EXCEPTION '%: empleados=%, contratos=%, perfiles=%, relaciones inválidas=%',
                tenant, employees, contracts, profiles, invalid;
        END IF;

        total_slips := 0;
        FOR month IN 3..12 LOOP
            month_start := make_date(2025, month, 1);
            period_name := to_char(month_start, 'YYYY-MM');
            period_id := public.uuid_generate_v5(namespace, tenant || ':period:' || period_name);
            EXECUTE format($check$
                WITH expected AS (
                    SELECT public.uuid_generate_v5($1, $2 || ':employee:' || i) AS employee_id,
                           public.uuid_generate_v5($1, $2 || ':slip:' || $4 || ':' || i) AS slip_id,
                           1800 + 25 * (i %% 400) AS salary
                    FROM generate_series(0, $3 - 1) AS i
                )
                SELECT count(s.pay_slip_id), count(*) FILTER (WHERE
                           s.employee_id IS DISTINCT FROM x.employee_id OR s.period_id IS DISTINCT FROM $5
                           OR s.base_salary IS DISTINCT FROM x.salary OR s.deductions IS DISTINCT FROM x.salary * 0.13
                           OR s.net_pay IS DISTINCT FROM x.salary * 0.87 OR s.s3_slip_key IS NOT NULL
                           OR s.generated_at IS DISTINCT FROM $6 + interval '1 month' - interval '2 hours'
                       )
                FROM expected x LEFT JOIN %I.pay_slips s ON s.pay_slip_id = x.slip_id
            $check$, tenant)
            INTO slips, invalid
            USING namespace, tenant, payees, period_name, period_id, month_start;

            EXECUTE format(
                'SELECT count(*), sum(net_pay) FROM %I.pay_slips WHERE period_id = $1', tenant
            ) INTO actual_slips, actual_total USING period_id;

            EXECUTE format($check$
                SELECT NOT EXISTS (
                    SELECT 1 FROM %1$I.payroll_periods
                    WHERE period_id = $1 AND period_name = $2 AND is_closed
                      AND total_paid = $3 AND created_at = $7
                ) OR EXISTS (
                    SELECT 1 FROM generate_series(0, $6 - 1) i
                    JOIN %1$I.unpaid_leaves_ledger l
                      ON l.employee_id = public.uuid_generate_v5($4, $5 || ':employee:' || i)
                    WHERE l.period_target = $2
                )
            $check$, tenant)
            INTO problems USING period_id, period_name, actual_total, namespace, tenant, required, month_start;

            IF slips <> payees OR actual_slips <> payees OR invalid <> 0 OR problems THEN
                RAISE EXCEPTION '% %: boletas=%, boletas del período=%, relaciones inválidas=%, conflicto de período o licencia=%',
                    tenant, period_name, slips, actual_slips, invalid, problems;
            END IF;
            total_slips := total_slips + slips;
        END LOOP;
        IF total_slips <> required THEN
            RAISE EXCEPTION '%: boletas=%, esperadas=%', tenant, total_slips, required;
        END IF;
        RAISE NOTICE '%: empleados=%, boletas=%, contratos=%, perfiles=%, departamentos=%, períodos=10, empleados de Payroll=%',
            tenant, employees, total_slips, contracts, profiles, departments, payees;
        global_principal := global_principal + employees + total_slips;
    END LOOP;

    RAISE NOTICE 'TOTAL_GLOBAL=% (empleados + boletas del seed SQL)', global_principal;
END
$verify$;
COMMIT;
