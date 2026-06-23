import io

import qrcode
from reportlab.lib.pagesizes import A6
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

def generate_qr_png_bytes(qr_payload: str) -> bytes:
    qr = qrcode.QRCode(version=None,error_correction=qrcode.constants.ERROR_CORRECT_M,box_size=10,border=4)
    qr.add_data(qr_payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_colors="white")

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()

def render_ticket_pdf(*,qr_payload: str, event_title: str,event_starts_at, venue: str,attendee_name: str,tier_name: str,order_reference: str) -> bytes:
    qr_bytes = generate_qr_png_bytes(qr_payload)
    qr_image = ImageReader(io.BytesIO(qr_bytes))

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A6)
    width, height = A6
    margin = 8 * mm

    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(margin, height - 15 * mm, (event_title or "")[:40])

    pdf.setFont("Helvectica", 9)
    pdf.drawString(margin, height - 21 * mm, (venue or "")[:50])
    pdf.drawString(margin, height - 26 * mm, event_starts_at.strftime("%a, %d %b %Y - %H:%M %Z"))

    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(margin, height - 36 * mm, f"Attendee: {attendee_name}")
    pdf.setFont("Helvetica", 10)
    pdf.drawString(margin, height - 42 * mm, f"Tier: {tier_name}")
    pdf.drawString(margin, height - 48 * mm, f"Order ref: {order_reference}")

    qr_size = 42 * mm
    pdf.drawImage(qr_image, width - qr_size - margin, margin,width=qr_size, height=qr_size, preserveAspectRatio=True, mask="auto")

    pdf.setFont("Helvetica-Oblique", 6)
    pdf.drawString(margin, margin, f"QR: {qr_payload[:16]}...")

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()