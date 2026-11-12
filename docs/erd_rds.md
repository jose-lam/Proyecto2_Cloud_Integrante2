# ARCHIVO: docs/erd_rds.md

# Diagrama Entidad-Relación (ERD) - Amazon RDS PostgreSQL

Este documento contiene la especificación gráfica y estructural del modelo relacional multi-tenant para los microservicios `ms-core-hr` y `ms-payroll`. La estructura se aplica de forma idéntica en los esquemas aislados `tenant_a`, `tenant_b` y `tenant_c`.

Código Mermaid (erDiagram):

    erDiagram
        departments ||--o{ employees : "pertenece_a"
        employees ||--o{ contracts : "posee"

        departments {
            uuid department_id PK
            varchar_100 name UK
            numeric_12_2 budget
            timestamp created_at
        }

        employees {
            uuid employee_id PK
            uuid department_id FK
            varchar_50 first_name
            varchar_50 last_name
            varchar_120 email UK
            varchar_30 role
            date hire_date
            varchar_20 status
            timestamp created_at
        }

        contracts {
            uuid contract_id PK
            uuid employee_id FK
            numeric_10_2 salary
            date start_date
            date end_date
            varchar_30 contract_type
            text s3_contract_key
        }

        payroll_periods ||--o{ pay_slips : "genera"

        employee_salary_profiles {
            uuid employee_id PK
            varchar_120 email
            numeric_10_2 base_salary
            date hire_date
            boolean is_active
            timestamp synced_at
        }

        unpaid_leaves_ledger {
            uuid leave_id PK
            uuid employee_id
            integer days_unpaid
            varchar_7 period_target
            boolean applied
            timestamp processed_at
        }

        payroll_periods {
            uuid period_id PK
            varchar_7 period_name UK
            boolean is_closed
            numeric_14_2 total_paid
            timestamp created_at
        }

        pay_slips {
            uuid pay_slip_id PK
            uuid period_id FK
            uuid employee_id
            numeric_10_2 base_salary
            numeric_10_2 deductions
            numeric_10_2 net_pay
            text s3_slip_key
            timestamp generated_at
        }

## Descripción de Tablas

### Dominio `ms-core-hr`
- **`departments`**: Almacena las áreas organizacionales y su presupuesto asignado.
- **`employees`**: Entidad principal del personal, vinculada a un departamento.
- **`contracts`**: Contratos laborales asociados a cada empleado. Incluye referencia al archivo PDF del contrato almacenado en S3.

### Dominio `ms-payroll`
- **`employee_salary_profiles`**: Réplica de la información salarial sincronizada asíncronamente desde `ms-core-hr` mediante eventos SQS.
- **`unpaid_leaves_ledger`**: Registro acumulativo de licencias no pagadas (enviadas desde `ms-attendance` vía SQS) para ser liquidadas en la nómina correspondiente.
- **`payroll_periods`**: Control de los ciclos de pago mensuales (ej. `2026-11`) y su estado de cierre.
- **`pay_slips`**: Boletas de pago consolidadas para cada empleado dentro de un periodo específico, incluyendo el enlace S3 de la boleta generada en PDF.
