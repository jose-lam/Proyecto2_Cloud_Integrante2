# Guía Completa de Integración y Despliegue Manual en AWS Academy — Integrante 2 (Core HR & Nóminas)

Esta guía está diseñada para que puedas desplegar e integrar manualmente en la consola de **AWS Academy** toda la capa relacional y los dos microservicios del **Integrante 2**:

* **Base de Datos Relacional:** Amazon RDS (PostgreSQL) con aislamiento Multi-Tenant mediante *Single Database, Multiple Schemas* (`tenant_a`, `tenant_b`, `tenant_c`).
* **Microservicio `ms-core-hr`:** Gestión de departamentos, empleados y contratos PDF en S3.
* **Microservicio `ms-payroll`:** Cálculo masivo de planillas, generación de boletas PDF en S3 y workers asíncronos SQS.

> **Optimización para AWS Academy:** Para respetar el límite de ejecuciones simultáneas del laboratorio, todos los endpoints HTTP están unificados en **2 Lambdas Router** (`ms-core-hr-api` y `ms-payroll-api`), más **2 Lambdas Workers** para SQS (**4 funciones Lambda en total**).

---

## 1. Matriz Maestra de Reemplazo (`[FALTA_INTEGRANTE_...]`)

En los archivos `services/core-hr/serverless.yml` y `services/payroll/serverless.yml` dejé marcadores con el formato `[FALTA_INTEGRANTE_...]`. Como vas a crear los recursos manualmente en AWS, esta tabla te indica **qué valor real corresponde a cada marcador**, **dónde obtenerlo** y **en qué variable de entorno de qué Lambda debes pegarlo**:

| Marcador en el Código / YAML | Qué recurso es y formato esperado | Dónde configurarlo en la Consola AWS (Despliegue Manual) | Archivo YAML de referencia |
| :--- | :--- | :--- | :--- |
| `[FALTA_INTEGRANTE_1_ARN_LABROLE]` | ARN del rol IAM precreado de AWS Academy. Ej: `arn:aws:iam::123456789012:role/LabRole` | En **Execution role** al crear cada una de las **4 Lambdas** (seleccionar *Use an existing role* -> `LabRole`). | Ambos `serverless.yml` |
| `[FALTA_INTEGRANTE_1_DB_HOST]` | Endpoint DNS de la instancia RDS PostgreSQL. Ej: `hcm-db.xxxx.us-east-1.rds.amazonaws.com` | Variable de entorno **`DB_HOST`** en las **4 Lambdas**. | Ambos `serverless.yml` |
| `[FALTA_INTEGRANTE_1_DB_NAME]` | Nombre de la base de datos inicial en RDS. Ej: `hcm_db` (o `postgres`) | Variable de entorno **`DB_NAME`** en las **4 Lambdas**. | Ambos `serverless.yml` |
| `[FALTA_INTEGRANTE_1_DB_USER]` | Usuario administrador de RDS. Ej: `postgres` | Variable de entorno **`DB_USER`** en las **4 Lambdas**. | Ambos `serverless.yml` |
| `[FALTA_INTEGRANTE_1_DB_PASSWORD]` | Contraseña maestra de RDS definida al crear la BD. | Variable de entorno **`DB_PASSWORD`** en las **4 Lambdas**. | Ambos `serverless.yml` |
| `[FALTA_INTEGRANTE_1_NOMBRE_BUCKET_S3]` | **Solo el nombre** del bucket S3 único (sin `s3://` ni rutas). Ej: `hcm-saas-storage-grupo2` | Variable de entorno **`S3_BUCKET_NAME`** en `ms-core-hr-api` y `ms-payroll-api`. | Ambos `serverless.yml` |
| `[FALTA_INTEGRANTE_1_ARN_CUSTOM_AUTHORIZER]` | ARN de tu Lambda Custom Authorizer. Ej: `arn:aws:lambda:us-east-1:123456789012:function:custom-authorizer` | En **API Gateway -> Authorizers** (asociado a todas las rutas de `ms-core-hr-api` y `ms-payroll-api`). | Ambos `serverless.yml` |
| `[FALTA_INTEGRANTE_4_ARN_SNS_HR_EVENTS]` | ARN del tópico SNS de eventos de RRHH. Ej: `arn:aws:sns:us-east-1:123456789012:sns-hr-events` | Variable de entorno **`SNS_HR_EVENTS_ARN`** en `ms-core-hr-api`. | `core-hr/serverless.yml` |
| `[FALTA_INTEGRANTE_4_ARN_SNS_PAYROLL_EVENTS]` | ARN del tópico SNS de eventos de Nómina. Ej: `arn:aws:sns:us-east-1:123456789012:sns-payroll-events` | Variable de entorno **`SNS_PAYROLL_EVENTS_ARN`** en `ms-payroll-api`. | `payroll/serverless.yml` |
| `[FALTA_INTEGRANTE_4_ARN_SQS_PAYROLL_HR_SYNC]` | ARN de la cola SQS suscrita a `sns-hr-events`. Ej: `arn:aws:sqs:us-east-1:123456789012:payroll-hr-sync` | En **Add trigger -> SQS** dentro de la Lambda `ms-payroll-sync-employee`. | `payroll/serverless.yml` |
| `[FALTA_INTEGRANTE_4_ARN_SQS_PAYROLL_ATTENDANCE_SYNC]` | ARN de la cola SQS suscrita a `sns-attendance-events`. Ej: `arn:aws:sqs:us-east-1:123456789012:payroll-attendance-sync` | En **Add trigger -> SQS** dentro de la Lambda `ms-payroll-sync-leave`. | `payroll/serverless.yml` |
| `[FALTA_INTEGRANTE_1_ORGANIZACION]` | Org de Serverless Framework (no aplica si subes ZIPs a mano). | Ignorar en despliegue manual por consola AWS. | Ambos `serverless.yml` |

---

## 2. Reglas Críticas de Integración (Contratos entre Todo el Equipo)

Antes de levantar servicios, verifica estos **5 puntos obligatorios** que el código Python valida estrictamente en tiempo de ejecución:

### 2.1 Nombres Exactos de los Tenants (`tenant_a`, `tenant_b`, `tenant_c`)
En `shared/middlewares/db_tenant_middleware.py`, el código valida contra una lista blanca cerrada para prevenir SQL Injection al ejecutar `SET search_path`:

    ALLOWED_TENANTS = {'tenant_a', 'tenant_b', 'tenant_c'}

* **Impacto:** El **Custom Authorizer**, el **Frontend (registro/login)** y el **script de seeding de 30,000 registros (Integrante 4)** deben usar **literalmente** `tenant_a`, `tenant_b` y `tenant_c` (en minúsculas y con guion bajo). Si llega `tenant1` o `empresa_a`, el backend devolverá `HTTP 401 Tenant no autorizado o invalido`.

### 2.2 Nombres Exactos de los Roles (`ADMIN`, `HR_MANAGER`, `EMPLOYEE`)
En `shared/middlewares/acl_middleware.py`, los permisos se validan contra estos 3 roles exactos:
* `ADMIN` y `HR_MANAGER`: Acceso total a crear departamentos, registrar empleados, subir contratos y calcular nóminas.
* `EMPLOYEE`: Solo lectura sobre su propio `employee_id` (si intenta ver el perfil o boleta de otro empleado, devuelve `HTTP 403 Forbidden`).

### 2.3 API Gateway DEBE ser "REST API" (No HTTP API) y Formato del Authorizer
* En API Gateway crea una **REST API** (la clásica), **NO** una *HTTP API (v2)*. El código lee `event['httpMethod']`, `event['resource']` y `event['requestContext']['authorizer']`, estructura propia de REST API con Proxy Integration.
* Tu **Lambda Custom Authorizer** debe retornar dentro de `context` exactamente estas 3 llaves:

      {
        "principalId": "uuid-del-usuario",
        "policyDocument": {
          "Version": "2012-10-17",
          "Statement": [
            {
              "Action": "execute-api:Invoke",
              "Effect": "Allow",
              "Resource": "*"
            }
          ]
        },
        "context": {
          "tenant_id": "tenant_a",
          "role": "ADMIN",
          "employee_id": "uuid-del-empleado"
        }
      }

### 2.4 Configuración CORS Obligatoria en el Bucket S3
El endpoint `POST /employees/{id}/contract-upload-url` devuelve una Presigned URL para que el navegador suba el contrato PDF directamente a S3. En la consola de **S3 -> Tu Bucket -> Permissions -> Cross-origin resource sharing (CORS)**, pega esta configuración o el navegador bloqueará la subida:

    [
      {
        "AllowedHeaders": ["*"],
        "AllowedMethods": ["GET", "PUT", "POST", "HEAD"],
        "AllowedOrigins": ["*"],
        "ExposeHeaders": ["ETag"]
      }
    ]

### 2.5 Estructura de Mensajes SQS para los Workers de Nómina
* En las suscripciones **SNS -> SQS**, deja **DESMARCADA** la casilla *Enable raw message delivery*. Los workers esperan el envoltorio JSON estándar de SNS (`record["body"]["Message"]`).
* Payloads JSON que esperan los workers del Integrante 4:
  * Cola `payroll-hr-sync` (evento `employee.created`):
    `{"tenant_id": "tenant_a", "employee_id": "uuid", "email": "correo@dominio.com", "salary": 3500.00, "hire_date": "2026-11-01"}`
  * Cola `payroll-attendance-sync` (evento `leave.approved`):
    `{"tenant_id": "tenant_a", "leave_id": "uuid", "employee_id": "uuid", "days_unpaid": 2, "start_date": "2026-11-10"}`

---

## 3. Paso 1: Crear y Migrar Amazon RDS (PostgreSQL)

### 3.1 Crear la Instancia en AWS RDS
1. Ve a **Amazon RDS -> Databases -> Create database**.
2. Selecciona **Standard create** y **PostgreSQL** (versión 14 o 15).
3. En *Templates*, elige **Free tier** (o **Dev/Test**).
4. **Settings:**
   * **DB instance identifier:** `hcm-saas-postgres`
   * **Master username:** `postgres`
   * **Master password:** Define tu contraseña (anótala para `DB_PASSWORD`).
5. **Instance configuration:** Elige **`db.t3.micro`** o **`db.t4g.micro`** (son las permitidas en AWS Academy).
6. **Storage:** `20 GiB` (`gp2`), desmarca *Enable storage autoscaling*.
7. **Connectivity (MUY IMPORTANTE):**
   * **Public access:** Selecciona **Yes**. *(No metas las Lambdas en una VPC; en AWS Academy no hay NAT Gateway y si las metes en VPC perderán acceso a S3 y SNS).*
   * **VPC security group:** Crea uno nuevo (`sg-hcm-rds`) y abre el puerto **`5432` (PostgreSQL)** con origen **`0.0.0.0/0`**.
8. **Additional configuration:** En **Initial database name** escribe **`hcm_db`**.
9. Crea la base de datos, espera a que pase a estado **Available** y copia su **Endpoint** (`DB_HOST`).

### 3.2 Ejecutar los Scripts SQL en Orden Estricto
Desde **AWS CloudShell** o una terminal local con `psql` (o pgAdmin/DBeaver), ejecuta los 3 archivos ubicados en `db/migrations/` en este orden exacto:

    export PGPASSWORD="TU_DB_PASSWORD"
    RDS_HOST="TU_DB_HOST"

    # 1. Crea los esquemas tenant_a, tenant_b, tenant_c y las 7 tablas en cada uno
    psql -h $RDS_HOST -U postgres -d hcm_db -f db/migrations/001_initial_schema.sql

    # 2. Inserta los 4 departamentos base y el periodo '2026-11' en los 3 tenants
    psql -h $RDS_HOST -U postgres -d hcm_db -f db/migrations/002_seed_initial_catalogs.sql

    # 3. Crea los índices de optimización para soportar 30,000+ registros en <200ms
    psql -h $RDS_HOST -U postgres -d hcm_db -f db/migrations/003_indexes_optimization.sql

*(El archivo `db/verify_30k_seeding.sql` se ejecuta después de que el Integrante 4 corra el script de carga masiva).*

---

## 4. Paso 2: Crear Tópicos SNS y Colas SQS

En la región **`us-east-1`**:
1. **Amazon SNS (Topics - Standard):**
   * Crea `sns-hr-events` (anota su ARN para `SNS_HR_EVENTS_ARN`).
   * Crea `sns-payroll-events` (anota su ARN para `SNS_PAYROLL_EVENTS_ARN`).
   * Verifica que exista `sns-attendance-events` (del Integrante 4).
2. **Amazon SQS (Queues - Standard):**
   * Crea `payroll-hr-sync` -> Suscríbela a **`sns-hr-events`** (con *Raw message delivery* **desactivado**).
   * Crea `payroll-attendance-sync` -> Suscríbela a **`sns-attendance-events`** (con *Raw message delivery* **desactivado**).

---

## 5. Paso 3: Empaquetar los `.zip` de Python (`core-hr.zip` y `payroll.zip`)

Como el código importa desde `../shared/` y usa `psycopg2-binary` (librería compilada), ejecuta estos comandos desde la carpeta raíz `proyecto2/` para empaquetar las dependencias compatibles con **AWS Lambda Linux x86_64 (Python 3.11)** sin importar desde qué sistema operativo empaquetes:

### 5.1 Generar `core-hr.zip`

    rm -rf build/core-hr core-hr.zip
    mkdir -p build/core-hr
    cp -r services/core-hr/* build/core-hr/
    cp -r shared build/core-hr/shared

    pip install \
      --platform manylinux2014_x86_64 \
      --target=build/core-hr \
      --implementation cp \
      --python-version 3.11 \
      --only-binary=:all: \
      --upgrade \
      -r services/core-hr/requirements.txt

    cd build/core-hr && zip -r ../../core-hr.zip . && cd ../..

### 5.2 Generar `payroll.zip`

    rm -rf build/payroll payroll.zip
    mkdir -p build/payroll
    cp -r services/payroll/* build/payroll/
    cp -r shared build/payroll/shared

    pip install \
      --platform manylinux2014_x86_64 \
      --target=build/payroll \
      --implementation cp \
      --python-version 3.11 \
      --only-binary=:all: \
      --upgrade \
      -r services/payroll/requirements.txt

    cd build/payroll && zip -r ../../payroll.zip . && cd ../..

Verifica que en la raíz de ambos `.zip` existan directamente `router.py`, `handlers/` y `shared/`.

---

## 6. Paso 4: Crear las 4 Funciones Lambda en AWS

Ve a **AWS Lambda -> Create function -> Author from scratch** y crea estas **4 funciones** con la misma base:
* **Runtime:** `Python 3.11` | **Architecture:** `x86_64`
* **Execution role:** *Use an existing role* -> **`LabRole`**
* **General configuration (Configuration -> General configuration -> Edit):** Memory **`512 MB`**, Timeout **`30 sec`**.

### Ficha 1: `ms-core-hr-api`
* **Código a subir:** `core-hr.zip`
* **Handler:** `router.lambda_handler`
* **Environment variables (7 variables):**
  * `DB_HOST` = `[FALTA_INTEGRANTE_1_DB_HOST]`
  * `DB_PORT` = `5432`
  * `DB_NAME` = `[FALTA_INTEGRANTE_1_DB_NAME]`
  * `DB_USER` = `[FALTA_INTEGRANTE_1_DB_USER]`
  * `DB_PASSWORD` = `[FALTA_INTEGRANTE_1_DB_PASSWORD]`
  * `S3_BUCKET_NAME` = `[FALTA_INTEGRANTE_1_NOMBRE_BUCKET_S3]`
  * `SNS_HR_EVENTS_ARN` = `[FALTA_INTEGRANTE_4_ARN_SNS_HR_EVENTS]`

### Ficha 2: `ms-payroll-api`
* **Código a subir:** `payroll.zip`
* **Handler:** `router.lambda_handler`
* **Environment variables (7 variables):**
  * `DB_HOST` = `[FALTA_INTEGRANTE_1_DB_HOST]`
  * `DB_PORT` = `5432`
  * `DB_NAME` = `[FALTA_INTEGRANTE_1_DB_NAME]`
  * `DB_USER` = `[FALTA_INTEGRANTE_1_DB_USER]`
  * `DB_PASSWORD` = `[FALTA_INTEGRANTE_1_DB_PASSWORD]`
  * `S3_BUCKET_NAME` = `[FALTA_INTEGRANTE_1_NOMBRE_BUCKET_S3]`
  * `SNS_PAYROLL_EVENTS_ARN` = `[FALTA_INTEGRANTE_4_ARN_SNS_PAYROLL_EVENTS]`

### Ficha 3: `ms-payroll-sync-employee` (Worker SQS)
* **Código a subir:** `payroll.zip`
* **Handler:** `handlers/sync_employee_created_worker.lambda_handler`
* **Environment variables (5 variables):** `DB_HOST`, `DB_PORT` (`5432`), `DB_NAME`, `DB_USER`, `DB_PASSWORD`.
* **Trigger SQS (Add trigger -> SQS):**
  * **SQS queue:** `payroll-hr-sync` (`[FALTA_INTEGRANTE_4_ARN_SQS_PAYROLL_HR_SYNC]`)
  * **Batch size:** `10`
  * **Maximum concurrency:** `2` *(Obligatorio para no agotar las 7 concurrencias de AWS Academy)*
  * **Report batch item failures:** **Activado (Checked)**

### Ficha 4: `ms-payroll-sync-leave` (Worker SQS)
* **Código a subir:** `payroll.zip`
* **Handler:** `handlers/sync_leave_approved_worker.lambda_handler`
* **Environment variables (5 variables):** `DB_HOST`, `DB_PORT` (`5432`), `DB_NAME`, `DB_USER`, `DB_PASSWORD`.
* **Trigger SQS (Add trigger -> SQS):**
  * **SQS queue:** `payroll-attendance-sync` (`[FALTA_INTEGRANTE_4_ARN_SQS_PAYROLL_ATTENDANCE_SYNC]`)
  * **Batch size:** `10`
  * **Maximum concurrency:** `2`
  * **Report batch item failures:** **Activado (Checked)**

---

## 7. Paso 5: Configurar API Gateway (REST API)

### 7.1 Configurar el Custom Authorizer
En tu **REST API** -> **Authorizers** -> **Create authorizer**:
* **Authorizer type:** `Lambda`
* **Lambda function:** Selecciona tu Lambda Custom Authorizer (`[FALTA_INTEGRANTE_1_ARN_CUSTOM_AUTHORIZER]`)
* **Lambda event payload:** `Token`
* **Token source:** `Authorization`
* **Authorization caching (TTL):** **`300` segundos** *(Vital: evita invocar 2 Lambdas por petición HTTP y previene errores 429 en AWS Academy)*.

### 7.2 Crear los Recursos y Métodos
Para **CADA** endpoint de la siguiente tabla:
1. En **Integration type** elige `Lambda Function` y marca **Use Lambda Proxy integration = ON** *(obligatorio para que `router.py` reciba `httpMethod` y `resource`)*.
2. En **Method Request -> Authorization**, selecciona tu **Custom Authorizer**.
3. Selecciona el recurso y haz clic en **Enable CORS** (asegúrate de que el método `OPTIONS` quede sin Authorizer).

| Recurso (Path) | Método | Lambda Destino | Roles ACL Permitidos |
| :--- | :--- | :--- | :--- |
| `/departments` | `GET` | `ms-core-hr-api` | `ADMIN`, `HR_MANAGER`, `EMPLOYEE` |
| `/departments` | `POST` | `ms-core-hr-api` | `ADMIN`, `HR_MANAGER` |
| `/employees` | `GET` | `ms-core-hr-api` | `ADMIN`, `HR_MANAGER`, `EMPLOYEE` |
| `/employees` | `POST` | `ms-core-hr-api` | `ADMIN`, `HR_MANAGER` |
| `/employees/{id}` | `GET` | `ms-core-hr-api` | `ADMIN`, `HR_MANAGER`, o propio `EMPLOYEE` |
| `/employees/{id}` | `PUT` | `ms-core-hr-api` | `ADMIN`, `HR_MANAGER` |
| `/employees/{id}/contract-upload-url` | `POST` | `ms-core-hr-api` | `ADMIN`, `HR_MANAGER` |
| `/employees/{id}/contract-url` | `GET` | `ms-core-hr-api` | `ADMIN`, `HR_MANAGER`, o propio `EMPLOYEE` |
| `/payrolls/calculate` | `POST` | `ms-payroll-api` | `ADMIN`, `HR_MANAGER` |
| `/payrolls/{period}` | `GET` | `ms-payroll-api` | `ADMIN`, `HR_MANAGER` |
| `/payrolls/employee/{employee_id}` | `GET` | `ms-payroll-api` | `ADMIN`, `HR_MANAGER`, o propio `EMPLOYEE` |

Haz clic en **Deploy API** (stage `dev` o `prod`) y entrega la **Invoke URL** al Integrante 5 (Frontend).

---

## 8. Checklist de Verificación Rápida (Post-Despliegue)

Puedes importar `test/postman_integrante2.json` en Postman y validar estos 4 flujos:

1. **Aislamiento Multi-Schema:** Crea un empleado con `POST /employees` usando un token de `tenant_a`. Copia el `employee_id` devuelto e intenta consultarlo con `GET /employees/{id}` usando un token de `tenant_b` -> Debe responder **`404 Not Found`**.
2. **Sincronización Asíncrona (SNS -> SQS -> RDS):** Verifica en PostgreSQL que al crear el empleado en `tenant_a`, `ms-payroll-sync-employee` lo haya insertado automáticamente en `tenant_a.employee_salary_profiles`.
3. **Generación de Boletas PDF en S3:** Ejecuta `POST /payrolls/calculate` con `{"period": "2026-11", "generatePdfs": true}` y confirma en la consola de S3 que el PDF aparezca bajo `<S3_BUCKET_NAME>/tenant_a/payroll/slips/<period_id>/<employee_id>.pdf`.
4. **Control de Acceso (ACL):** Ejecuta `POST /departments` con un token que tenga `role: "EMPLOYEE"` -> Debe responder **`403 Forbidden`**.
