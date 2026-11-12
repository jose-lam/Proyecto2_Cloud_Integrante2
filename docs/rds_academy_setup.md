# ARCHIVO: docs/rds_academy_setup.md

# Guía de Aprovisionamiento y Verificación de Amazon RDS PostgreSQL en AWS Academy

Esta guía documenta los parámetros de configuración y los comandos requeridos para desplegar la base de datos relacional PostgreSQL en **AWS Academy Learner Lab** y ejecutar la inicialización del esquema y catálogos.

## 1. Parámetros de Creación de la Instancia RDS

En la consola de AWS Academy, diríjase a **RDS > Databases > Create database** e ingrese los siguientes valores exactos:

| Parámetro | Valor Exigido | Notas |
| :--- | :--- | :--- |
| **Engine type** | PostgreSQL | Versión recomendada: PostgreSQL 15.x o 16.x |
| **Templates** | Free Tier / Dev/Test | Ajustar para laboratorios |
| **DB Instance Identifier** | `hcm-rds-postgres` | Nombre identificador en la consola |
| **Master Username** | `postgres` | Usuario administrador |
| **Master Password** | `[FALTA_INTEGRANTE_1_DB_PASSWORD]` | Definido por el Integrante 1 |
| **DB Instance Class** | `db.t3.micro` o `db.t4g.micro` | Permitidos en la cuota de AWS Academy |
| **Storage Type** | General Purpose SSD (`gp2`) | Recomendado para pruebas |
| **Allocated Storage** | `20 GB` | Mínimo requerido |
| **Auto Scaling** | Disabled | Desactivar para evitar consumo innecesario |
| **VPC** | Default VPC | VPC asignada por AWS Academy |
| **Publicly Accessible** | **Yes** | Permite ejecución de scripts DDL y seeding masivo |
| **VPC Security Group** | Create new (`rds-hcm-sg`) | Configurar regla de entrada |
| **Initial Database Name** | `hcm_db` | Nombre de la base de datos relacional inicial |

## 2. Configuración del Security Group (`rds-hcm-sg`)

Una vez creada la instancia, modifique las **Inbound rules** del Security Group asignado a RDS:

- **Type:** PostgreSQL
- **Protocol:** TCP
- **Port:** `5432`
- **Source:** Anywhere IPv4 (`0.0.0.0/0`) o su IP pública actual para asegurar acceso desde la terminal local.

## 3. Ejecución de Migraciones con `psql`

Obtenga el **Endpoint** de la instancia RDS desde la sección de conectividad en la consola de AWS (ejemplo: `hcm-rds-postgres.c1234567890.us-east-1.rds.amazonaws.com`).

Desde la raíz del repositorio local, ejecute secuencialmente los comandos de migración:

### Paso A: Creación de Esquemas y Tablas (`001_initial_schema.sql`)

    psql -h <ENDPOINT_RDS> -U postgres -d hcm_db -p 5432 -f db/migrations/001_initial_schema.sql

### Paso B: Poblamiento de Catálogos Iniciales (`002_seed_initial_catalogs.sql`)

    psql -h <ENDPOINT_RDS> -U postgres -d hcm_db -p 5432 -f db/migrations/002_seed_initial_catalogs.sql

## 4. Script de Verificación Rápida

Para comprobar que los 3 esquemas y sus catálogos fueron creados exitosamente, conéctese a la base de datos y ejecute las siguientes consultas SQL de prueba:

    psql -h <ENDPOINT_RDS> -U postgres -d hcm_db

Consultas de verificación SQL:

    -- Verificar existencia de esquemas
    SELECT schema_name 
    FROM information_schema.schemata 
    WHERE schema_name IN ('tenant_a', 'tenant_b', 'tenant_c');

    -- Verificar departamentos iniciales en tenant_a
    SELECT * FROM tenant_a.departments;

    -- Verificar periodo de nómina en tenant_b
    SELECT * FROM tenant_b.payroll_periods;

    -- Verificar aislamiento de tablas en tenant_c
    SELECT table_name 
    FROM information_schema.tables 
    WHERE table_schema = 'tenant_c';
