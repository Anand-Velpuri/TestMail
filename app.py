import os
import ssl
import smtplib
from datetime import datetime
from typing import Optional, Dict

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, EmailStr, Field
from email.message import EmailMessage
from email.utils import formataddr

from logging_setup import setup_app_logger

# -------------------------------------------------------------------
# App & Logger
# -------------------------------------------------------------------

logger = setup_app_logger("email_service")

app = FastAPI(
    title="SynapStore Email Service",
    version="1.0.0",
    description="SMTP-based transactional email service"
)

# -------------------------------------------------------------------
# Settings
# -------------------------------------------------------------------

class Settings:
    SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", 587))
    SMTP_USER: Optional[str] = os.getenv("SMTP_USER")
    SMTP_PASS: Optional[str] = os.getenv("SMTP_PASS")

    @property
    def EMAIL_FROM(self) -> str:
        if not self.SMTP_USER:
            raise RuntimeError("SMTP_USER is not set")
        return formataddr(("SynapStore", self.SMTP_USER))


settings = Settings()

# -------------------------------------------------------------------
# Startup validation (fail fast)
# -------------------------------------------------------------------

@app.on_event("startup")
def validate_env():
    if not settings.SMTP_USER:
        raise RuntimeError("SMTP_USER environment variable missing")
    if not settings.SMTP_PASS:
        raise RuntimeError("SMTP_PASS environment variable missing")

# -------------------------------------------------------------------
# Core mail sender
# -------------------------------------------------------------------

def send_html_email(
    *,
    to_email: str,
    subject: str,
    html_body: str,
    plain_fallback: Optional[str] = None,
) -> bool:

    msg = EmailMessage()
    msg.set_content(
        plain_fallback or "Please view this email in an HTML-capable client."
    )
    msg.add_alternative(html_body, subtype="html")

    msg["From"] = settings.EMAIL_FROM
    msg["To"] = to_email
    msg["Subject"] = subject

    context = ssl.create_default_context()

    try:
        logger.info(f"Sending email to {to_email}")

        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            server.ehlo()
            server.starttls(context=context)
            server.login(settings.SMTP_USER, settings.SMTP_PASS)
            server.send_message(msg)

        logger.info("Email sent successfully")
        return True

    except smtplib.SMTPAuthenticationError:
        logger.error("SMTP authentication failed")
        raise

    except Exception as e:
        logger.error(f"SMTP error: {e}")
        raise

# -------------------------------------------------------------------
# Request Models
# -------------------------------------------------------------------

class SupplierToStoreRequest(BaseModel):
    to_email: EmailStr
    store_name: str
    supplier_name: str
    invoice_id: str
    items: Dict[str, int] = Field(..., example={"Paracetamol": 20})
    expected_delivery: str


class SupplierFailureRequest(BaseModel):
    to_email: EmailStr
    store_name: str
    store_email: EmailStr
    supplier_name: str
    invoice_id: str
    failure_reason: str

# -------------------------------------------------------------------
# Routes
# -------------------------------------------------------------------

@app.post("/email/supplier-to-store")
def supplier_to_storeowner_email(payload: SupplierToStoreRequest):

    subject = f"Stock Dispatched to {payload.store_name} | Invoice #{payload.invoice_id}"

    items_rows = "".join(
        f"""
        <tr>
            <td style="padding:8px;border:1px solid #ddd;">{item}</td>
            <td style="padding:8px;border:1px solid #ddd;text-align:center;">{qty}</td>
        </tr>
        """
        for item, qty in payload.items.items()
    )

    html_body = f"""
    <html>
      <body style="font-family:Arial,sans-serif;">
        <h2>Stock Dispatch Notification</h2>
        <p><strong>{payload.supplier_name}</strong> has dispatched stock.</p>
        <p><strong>Invoice:</strong> {payload.invoice_id}</p>
        <p><strong>Expected Delivery:</strong> {payload.expected_delivery}</p>

        <table width="100%" cellpadding="6" cellspacing="0" border="1">
          <thead>
            <tr>
              <th>Item</th>
              <th>Quantity</th>
            </tr>
          </thead>
          <tbody>
            {items_rows}
          </tbody>
        </table>
      </body>
    </html>
    """

    try:
        send_html_email(
            to_email=payload.to_email,
            subject=subject,
            html_body=html_body,
        )
        return {"status": "success"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/email/supplier-delivery-failed")
def supplier_delivery_failed_email(payload: SupplierFailureRequest):

    subject = f"Delivery Notification Failed | Invoice #{payload.invoice_id}"
    timestamp = datetime.utcnow().strftime("%d %b %Y, %H:%M UTC")

    html_body = f"""
    <html>
      <body style="font-family:Arial,sans-serif;">
        <h2 style="color:#d9534f;">Email Delivery Failed</h2>
        <p><strong>Supplier:</strong> {payload.supplier_name}</p>
        <p><strong>Store:</strong> {payload.store_name}</p>
        <p><strong>Store Email:</strong> {payload.store_email}</p>
        <p><strong>Invoice:</strong> {payload.invoice_id}</p>
        <p><strong>Time:</strong> {timestamp}</p>
        <p><strong>Reason:</strong> {payload.failure_reason}</p>
      </body>
    </html>
    """

    try:
        send_html_email(
            to_email=payload.to_email,
            subject=subject,
            html_body=html_body,
        )
        return {"status": "success"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -------------------------------------------------------------------
# Health Check
# -------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=7860, reload=True)
