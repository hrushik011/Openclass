import os
import resend

resend.api_key = os.getenv("RESEND_API_KEY")

def send_platform_email(to_email: str, subject: str, html_content: str):
    if not resend.api_key:
        print("Resend API key not configured.")
        return None
    try:
        params = {
            "from": "Openclass Updates <updates@useopenclass.in>",
            "to": [to_email],
            "subject": subject,
            "html": html_content,
        }
        response = resend.Emails.send(params)
        return response
    except Exception as e:
        print(f"Email delivery error: {e}")
        return None