-- ============================================================================
-- SCRIPT DE MIGRACIÓN 001: Creación de Esquemas y Tablas Multi-Tenant
-- Dominios: ms-core-hr y ms-payroll
-- Compatible con PostgreSQL 13+
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

DO $$
DECLARE
    schema_name TEXT;
    schemas TEXT[] := ARRAY['tenant_a', 'tenant_b', 'tenant_c'];
BEGIN
    FOREACH schema_name IN ARRAY schemas LOOP
        -- 1. Creación del esquema aislado
        EXECUTE format('CREATE SCHEMA IF NOT EXISTS %I;', schema_name);

        -- ====================================================================
        -- DOMINIO CORE HR (ms-core-hr)
        -- ====================================================================

        -- Tabla: departments
        EXECUTE format('
            CREATE TABLE IF NOT EXISTS %I.departments (
                department_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name VARCHAR(100) NOT NULL,
                budget NUMERIC(12, 2) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uk_%I_departments_name UNIQUE (name)
            );
        ', schema_name, schema_name);

        -- Tabla: employees
        EXECUTE format('
            CREATE TABLE IF NOT EXISTS %I.employees (
                employee_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                department_id UUID REFERENCES %I.departments(department_id),
                first_name VARCHAR(50) NOT NULL,
                last_name VARCHAR(50) NOT NULL,
                email VARCHAR(120) NOT NULL,
                role VARCHAR(30) DEFAULT ''EMPLOYEE'',
                hire_date DATE NOT NULL,
                status VARCHAR(20) DEFAULT ''ACTIVE'' CHECK (status IN (''ACTIVE'', ''INACTIVE'', ''ON_LEAVE'')),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uk_%I_employees_email UNIQUE (email)
            );
        ', schema_name, schema_name, schema_name);

        -- Tabla: contracts
        EXECUTE format('
            CREATE TABLE IF NOT EXISTS %I.contracts (
                contract_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                employee_id UUID NOT NULL REFERENCES %I.employees(employee_id) ON DELETE CASCADE,
                salary NUMERIC(10, 2) NOT NULL CHECK (salary > 0),
                start_date DATE NOT NULL,
                end_date DATE NULL,
                contract_type VARCHAR(30) NOT NULL CHECK (contract_type IN (''FULL_TIME'', ''PART_TIME'', ''CONTRACTOR'')),
                s3_contract_key TEXT NULL
            );
        ', schema_name, schema_name);

        -- ====================================================================
        -- DOMINIO NÓMINAS (ms-payroll)
        -- ====================================================================

        -- Tabla: employee_salary_profiles (Réplica de perfil salarial vía SQS desde ms-core-hr)
        EXECUTE format('
            CREATE TABLE IF NOT EXISTS %I.employee_salary_profiles (
                employee_id UUID PRIMARY KEY,
                email VARCHAR(120) NOT NULL,
                base_salary NUMERIC(10, 2) NOT NULL,
                hire_date DATE NOT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        ', schema_name);

        -- Tabla: unpaid_leaves_ledger (Registro idempotente de licencias no pagadas desde ms-attendance vía SQS)
        EXECUTE format('
            CREATE TABLE IF NOT EXISTS %I.unpaid_leaves_ledger (
                leave_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                employee_id UUID NOT NULL,
                days_unpaid INTEGER NOT NULL CHECK (days_unpaid > 0),
                period_target VARCHAR(7) NOT NULL,
                applied BOOLEAN DEFAULT FALSE,
                processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        ', schema_name);

        -- Tabla: payroll_periods
        EXECUTE format('
            CREATE TABLE IF NOT EXISTS %I.payroll_periods (
                period_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                period_name VARCHAR(7) NOT NULL,
                is_closed BOOLEAN DEFAULT FALSE,
                total_paid NUMERIC(14, 2) DEFAULT 0.00,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uk_%I_payroll_periods_name UNIQUE (period_name)
            );
        ', schema_name, schema_name);

        -- Tabla: pay_slips
        EXECUTE format('
            CREATE TABLE IF NOT EXISTS %I.pay_slips (
                pay_slip_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                period_id UUID NOT NULL REFERENCES %I.payroll_periods(period_id),
                employee_id UUID NOT NULL,
                base_salary NUMERIC(10, 2) NOT NULL,
                deductions NUMERIC(10, 2) DEFAULT 0.00,
                net_pay NUMERIC(10, 2) NOT NULL,
                s3_slip_key TEXT NULL,
                generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uk_%I_pay_slips_period_employee UNIQUE (period_id, employee_id)
            );
        ', schema_name, schema_name, schema_name);

    END LOOP;
END $$;
