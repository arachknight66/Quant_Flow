import resend
from backend.core.config import settings
import structlog

log = structlog.get_logger()

if settings.RESEND_API_KEY:
    resend.api_key = settings.RESEND_API_KEY

async def send_signal_alert_email(email: str, symbol: str, old_action: str, new_action: str):
    if not settings.RESEND_API_KEY:
        log.warning("Resend API key not set; email alert skipped.", email=email, symbol=symbol, old_action=old_action, new_action=new_action)
        return False
        
    try:
        params = {
            "from": "alerts@quantflow.app",
            "to": email,
            "subject": f"QuantPlatform Signal Alert: {symbol} Changed to {new_action}",
            "html": f"""
            <h3>QuantPlatform Alert</h3>
            <p>The model signal for <strong>{symbol}</strong> has changed:</p>
            <ul>
                <li><strong>Previous Signal:</strong> {old_action}</li>
                <li><strong>New Signal:</strong> {new_action}</li>
            </ul>
            <p>View the dashboard to manage your paper trading positions.</p>
            """
        }
        resend.Emails.send(params)
        log.info("Email alert successfully sent via Resend.", email=email, symbol=symbol, new_action=new_action)
        return True
    except Exception as e:
        log.error("Failed to send email alert via Resend.", email=email, symbol=symbol, error=str(e))
        return False
