import io
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from fpdf import FPDF


def _to_latin1(text: str) -> str:
    """Normaliza cadenas UTF-8 para compatibilidad segura con fuentes estándar de fpdf2."""
    if text is None:
        return ""
    return str(text).encode("latin-1", errors="replace").decode("latin-1")


def _fmt_money(amount: Decimal) -> str:
    """Formatea un Decimal a moneda con dos decimales."""
    quantized = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"S/ {quantized:,.2f}"


class _PaySlipPDF(FPDF):
    def __init__(self, tenant_id: str, period: str):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.tenant_id = tenant_id
        self.period = period

    def header(self):
        # Encabezado corporativo multi-tenant
        self.set_fill_color(24, 48, 89)
        self.rect(10, 10, 190, 24, style="F")

        self.set_xy(15, 14)
        self.set_font("Helvetica", "B", 14)
        self.set_text_color(255, 255, 255)
        self.cell(120, 7, _to_latin1(f"TENANT: {self.tenant_id.upper()}"), ln=False)

        self.set_font("Helvetica", "B", 11)
        self.cell(60, 7, _to_latin1(f"PERIODO: {self.period}"), align="R", ln=True)

        self.set_x(15)
        self.set_font("Helvetica", "", 9)
        self.set_text_color(215, 226, 242)
        self.cell(180, 6, _to_latin1("BOLETA DE PAGO DE REMUNERACIONES - COMPROBANTE ELECTRONICO"), ln=True)

        self.set_text_color(30, 30, 30)
        self.ln(8)

    def footer(self):
        self.set_y(-18)
        self.set_draw_color(200, 200, 200)
        self.line(10, self.get_y(), 200, self.get_y())
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(110, 110, 110)
        generated_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        self.cell(
            0,
            8,
            _to_latin1(f"Documento generado automaticamente por ms-payroll ({self.tenant_id}) | {generated_utc}"),
            align="C"
        )


def generate_pay_slip_pdf(
    tenant_id: str,
    period: str,
    employee_data: dict,
    base_salary: Decimal,
    unpaid_leave_deduction: Decimal,
    statutory_withholding: Decimal,
    net_pay: Decimal,
    unpaid_days: int = 0
) -> bytes:
    """
    Genera una boleta de pago PDF en memoria (io.BytesIO) y devuelve sus bytes.

    Parámetros:
        tenant_id: Identificador del tenant (ej. 'tenant_a').
        period: Periodo de nómina en formato 'YYYY-MM'.
        employee_data: Diccionario con employee_id, full_name, email, contract_type, hire_date.
        base_salary: Sueldo base mensual.
        unpaid_leave_deduction: Descuento por licencias sin goce de haber.
        statutory_withholding: Retención de ley (13%).
        net_pay: Remuneración neta a pagar.
        unpaid_days: Cantidad de días de licencia no pagada aplicados en el periodo.
    """
    base_salary = Decimal(str(base_salary)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    unpaid_leave_deduction = Decimal(str(unpaid_leave_deduction)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    statutory_withholding = Decimal(str(statutory_withholding)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    net_pay = Decimal(str(net_pay)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total_deductions = (unpaid_leave_deduction + statutory_withholding).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    pdf = _PaySlipPDF(tenant_id=tenant_id, period=period)
    pdf.set_auto_page_break(auto=True, margin=22)
    pdf.add_page()

    # =========================================================================
    # SECCIÓN 1: DATOS DEL COLABORADOR
    # =========================================================================
    pdf.set_fill_color(242, 245, 249)
    pdf.set_draw_color(210, 218, 228)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(190, 8, _to_latin1("  1. INFORMACION DEL EMPLEADO"), border=1, ln=True, fill=True)

    emp_id = str(employee_data.get("employee_id", "N/A"))
    full_name = employee_data.get("full_name") or employee_data.get("email") or "Colaborador"
    email = employee_data.get("email", "N/A")
    contract_type = employee_data.get("contract_type", "FULL_TIME")
    hire_date = str(employee_data.get("hire_date", "N/A"))

    rows_info = [
        ("Nombre / Razon Social:", full_name, "Periodo de Pago:", period),
        ("ID Empleado:", emp_id, "Tipo Contrato:", contract_type),
        ("Correo Corporativo:", email, "Fecha Ingreso:", hire_date),
    ]

    pdf.set_font("Helvetica", "", 9)
    for lbl1, val1, lbl2, val2 in rows_info:
        pdf.set_font("Helvetica", "B", 8.5)
        pdf.cell(38, 7, _to_latin1(f"  {lbl1}"), border="L")
        pdf.set_font("Helvetica", "", 8.5)
        pdf.cell(67, 7, _to_latin1(val1[:38]), border=0)
        pdf.set_font("Helvetica", "B", 8.5)
        pdf.cell(35, 7, _to_latin1(lbl2), border=0)
        pdf.set_font("Helvetica", "", 8.5)
        pdf.cell(50, 7, _to_latin1(val2), border="R", ln=True)

    pdf.cell(190, 0, "", border="T", ln=True)
    pdf.ln(8)

    # =========================================================================
    # SECCIÓN 2: DETALLE DE INGRESOS, DESCUENTOS Y RETENCIONES
    # =========================================================================
    pdf.set_fill_color(242, 245, 249)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(190, 8, _to_latin1("  2. LIQUIDACION DE REMUNERACIONES"), border=1, ln=True, fill=True)

    # Cabecera de tabla
    pdf.set_fill_color(230, 236, 244)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(110, 8, _to_latin1("  Concepto"), border=1, fill=True)
    pdf.cell(40, 8, _to_latin1("Ingresos"), border=1, align="R", fill=True)
    pdf.cell(40, 8, _to_latin1("Descuentos  "), border=1, align="R", fill=True, ln=True)

    # Fila 1: Sueldo Base
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(110, 8, _to_latin1("  Sueldo Basico Mensual"), border="LR")
    pdf.cell(40, 8, _to_latin1(_fmt_money(base_salary)), border="LR", align="R")
    pdf.cell(40, 8, _to_latin1("-  "), border="LR", align="R", ln=True)

    # Fila 2: Descuentos por licencias no pagadas
    leave_label = f"  Descuento por Licencias No Pagadas ({unpaid_days} dias)"
    pdf.cell(110, 8, _to_latin1(leave_label), border="LR")
    pdf.cell(40, 8, _to_latin1("-"), border="LR", align="R")
    pdf.cell(40, 8, _to_latin1(f"{_fmt_money(unpaid_leave_deduction)}  "), border="LR", align="R", ln=True)

    # Fila 3: Retenciones de ley (13%)
    pdf.cell(110, 8, _to_latin1("  Retenciones de Ley (13.00% - Sistema Pensionario)"), border="LRB")
    pdf.cell(40, 8, _to_latin1("-"), border="LRB", align="R")
    pdf.cell(40, 8, _to_latin1(f"{_fmt_money(statutory_withholding)}  "), border="LRB", align="R", ln=True)

    # Subtotales
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(248, 250, 252)
    pdf.cell(110, 8, _to_latin1("  TOTAL INGRESOS / TOTAL DESCUENTOS"), border=1, fill=True)
    pdf.cell(40, 8, _to_latin1(_fmt_money(base_salary)), border=1, align="R", fill=True)
    pdf.cell(40, 8, _to_latin1(f"{_fmt_money(total_deductions)}  "), border=1, align="R", fill=True, ln=True)

    pdf.ln(6)

    # =========================================================================
    # SECCIÓN 3: NETO A PAGAR
    # =========================================================================
    pdf.set_fill_color(24, 48, 89)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(130, 11, _to_latin1("  NETO A PAGAR AL COLABORADOR:"), border=1, fill=True)
    pdf.cell(60, 11, _to_latin1(f"{_fmt_money(net_pay)}  "), border=1, align="R", fill=True, ln=True)

    pdf.set_text_color(30, 30, 30)

    # Exportar documento PDF a buffer en memoria io.BytesIO
    buffer = io.BytesIO()
    raw_pdf = pdf.output()
    buffer.write(bytes(raw_pdf))
    buffer.seek(0)
    return buffer.getvalue()
