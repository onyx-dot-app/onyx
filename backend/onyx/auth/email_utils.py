import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from textwrap import dedent

from onyx.configs.app_configs import EMAIL_CONFIGURED
from onyx.configs.app_configs import EMAIL_FROM
from onyx.configs.app_configs import SMTP_PASS
from onyx.configs.app_configs import SMTP_PORT
from onyx.configs.app_configs import SMTP_SERVER
from onyx.configs.app_configs import SMTP_USER
from onyx.configs.app_configs import WEB_DOMAIN
from onyx.db.models import User


def send_email(
    user_email: str,
    subject: str,
    body: str,
    mail_from: str = EMAIL_FROM,
) -> None:
    if not EMAIL_CONFIGURED:
        raise ValueError("Email is not configured.")

    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["To"] = user_email
    if mail_from:
        msg["From"] = mail_from

    msg.attach(MIMEText(body))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as s:
            s.starttls()
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
    except Exception as e:
        raise e


def send_user_email_invite(user_email: str, current_user: User) -> None:
    subject = "Invitation to Join Onyx Organization"
    body = dedent(
        f"""\
        Hello,

        You have been invited to join an organization on Onyx.

        To join the organization, please visit the following link:

        {WEB_DOMAIN}/auth/signup?email={user_email}

        You'll be asked to set a password or login with Google to complete your registration.

        Best regards,
        The Onyx Team
    """
    )

    send_email(user_email, subject, body, current_user.email)


def send_forgot_password_email(
    user_email: str,
    token: str,
    mail_from: str = EMAIL_FROM,
) -> None:
    subject = "Onyx Forgot Password"
    link = f"{WEB_DOMAIN}/auth/reset-password?token={token}"
    body = f"Click the following link to reset your password: {link}"
    send_email(user_email, subject, body, mail_from)


def send_user_verification_email(
    user_email: str,
    token: str,
    mail_from: str = EMAIL_FROM,
) -> None:
    subject = "Onyx Email Verification"
    link = f"{WEB_DOMAIN}/auth/verify-email?token={token}"
    body = f"Click the following link to verify your email address: {link}"
    send_email(user_email, subject, body, mail_from)
