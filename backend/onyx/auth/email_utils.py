import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate
from email.utils import make_msgid

from onyx.configs.app_configs import EMAIL_CONFIGURED
from onyx.configs.app_configs import EMAIL_FROM
from onyx.configs.app_configs import SMTP_PASS
from onyx.configs.app_configs import SMTP_PORT
from onyx.configs.app_configs import SMTP_SERVER
from onyx.configs.app_configs import SMTP_USER
from onyx.configs.app_configs import WEB_DOMAIN
from onyx.configs.constants import AuthType
from onyx.configs.constants import TENANT_ID_COOKIE_NAME
from onyx.db.models import User
from shared_configs.configs import MULTI_TENANT

HTML_EMAIL_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width" />
  <title>{title}</title>
  <style>
    body, table, td, a {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      text-size-adjust: 100%;
      margin: 0;
      padding: 0;
      -webkit-font-smoothing: antialiased;
      -webkit-text-size-adjust: none;
    }}
    body {{
      background-color: #f7f7f7;
      color: #333;
    }}
    .body-content {{
      color: #333;
    }}
    .email-container {{
      width: 100%;
      max-width: 600px;
      margin: 0 auto;
      background-color: #ffffff;
      border-radius: 6px;
      overflow: hidden;
      border: 1px solid #eaeaea;
    }}
    .header {{
      background-color: #ffffff;
      padding: 20px;
      text-align: center;
    }}
    .header img {{
      max-width: 140px;
    }}
    .body-content {{
      padding: 20px 30px;
    }}
    .title {{
      font-size: 20px;
      font-weight: bold;
      margin: 0 0 10px;
    }}
    .message {{
      font-size: 16px;
      line-height: 1.5;
      margin: 0 0 20px;
    }}
    .cta-button {{
      display: inline-block;
      padding: 12px 20px;
      background-color: #000000;
      color: #ffffff !important;
      text-decoration: none;
      border-radius: 4px;
      font-weight: 500;
    }}
    .footer {{
      font-size: 13px;
      color: #6A7280;
      text-align: center;
      padding: 20px;
    }}
    .footer a {{
      color: #6b7280;
      text-decoration: underline;
    }}
  </style>
</head>
<body>
  <table role="presentation" class="email-container" cellpadding="0" cellspacing="0">
    <tr>
      <td class="header">
        <img
          style="background-color: #ffffff; border-radius: 8px;"
          src="https://www.eea.europa.eu/en/newsroom/branding-materials/eea_logo_compact_en.png/@@download/image/eea_logo_compact_en.png"
          alt="EEA GPT Lab Logo"
        >
      </td>
    </tr>
    <tr>
      <td class="body-content">
        <h1 class="title">{heading}</h1>
        <div class="message">
          {message}
        </div>
        {cta_block}
      </td>
    </tr>
    <tr>
      <td class="footer">
        EEA GPT Lab is powered by open source LLMs, and software such as Onyx, Litellm, Langfuse, vLLM, Vespa.
      </td>
    </tr>
  </table>
</body>
</html>
"""


def build_html_email(
    heading: str, message: str, cta_text: str | None = None, cta_link: str | None = None
) -> str:
    if cta_text and cta_link:
        cta_block = f'<a class="cta-button" href="{cta_link}">{cta_text}</a>'
    else:
        cta_block = ""
    return HTML_EMAIL_TEMPLATE.format(
        title=heading,
        heading=heading,
        message=message,
        cta_block=cta_block,
        year=datetime.now().year,
    )


def send_email(
    user_email: str,
    subject: str,
    html_body: str,
    text_body: str,
    mail_from: str = EMAIL_FROM,
) -> None:
    import pdb; pdb.set_trace()
    if not EMAIL_CONFIGURED:
        raise ValueError("Email is not configured.")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["To"] = user_email
    if mail_from:
        msg["From"] = mail_from
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="onyx.app")

    part_text = MIMEText(text_body, "plain")
    part_html = MIMEText(html_body, "html")

    msg.attach(part_text)
    msg.attach(part_html)

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as s:
            if SMTP_USER is not None and SMTP_USER != '':
                s.starttls()
                s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
    except Exception as e:
        raise e


def send_subscription_cancellation_email(user_email: str) -> None:
    import pdb; pdb.set_trace()
    # Example usage of the reusable HTML
    subject = "Your Onyx Subscription Has Been Canceled"
    heading = "Subscription Canceled"
    message = (
        "<p>We're sorry to see you go.</p>"
        "<p>Your subscription has been canceled and will end on your next billing date.</p>"
        "<p>If you change your mind, you can always come back!</p>"
    )
    cta_text = "Renew Subscription"
    cta_link = "https://www.onyx.app/pricing"
    html_content = build_html_email(heading, message, cta_text, cta_link)
    text_content = (
        "We're sorry to see you go.\n"
        "Your subscription has been canceled and will end on your next billing date.\n"
        "If you change your mind, visit https://www.onyx.app/pricing"
    )
    send_email(user_email, subject, html_content, text_content)


def send_user_email_invite(
    user_email: str, current_user: User, auth_type: AuthType
) -> None:
    subject = "Invitation to Join EEA GPT Lab"
    heading = "You've been invited to EEA GPT Lab!"

    # the exact action taken by the user, and thus the message, depends on the auth type
    message = f"<p>You have been invited by {current_user.email} (admin) to join the EEA GPT Lab.</p>"



    message += ("<p>The EEA GPT Lab is a restricted-access application designed as a safe environment to explore the potential benefits and risks of using EEA's public content with state-of-the-art Large Language Models (LLMs). The application is for experimental purposes only, with access limited to users with EEA email addresses and selected partners. GPT Lab is built with a robust privacy architecture to ensure that sensitive and personal information is not sent to third-party LLM AI providers.<br/>"
        "See <a href='https://gptlab.eea.europa.eu/pages/privacy'>Privacy Architecture</a>.<p>")



    if auth_type == AuthType.CLOUD:
        message += (
            "<p>To join the organization, please click the button below to set a password "
            "or login with Google and complete your registration.</p>"
        )
    elif auth_type == AuthType.BASIC:
        message += (
            "<p>To join the EEA GPT Lab, please click the button below to set a password "
            "and complete your registration.</p>"
        )
    elif auth_type == AuthType.GOOGLE_OAUTH:
        message += (
            "<p>To join the organization, please click the button below to login with Google "
            "and complete your registration.</p>"
        )
    elif auth_type == AuthType.OIDC or auth_type == AuthType.SAML:
        message += (
            "<p>To join the organization, please click the button below to"
            " complete your registration.</p>"
        )
    else:
        raise ValueError(f"Invalid auth type: {auth_type}")

    cta_text = "Join EEA GPT Lab"
    cta_link = f"{WEB_DOMAIN}/auth/signup?email={user_email}"
    html_content = build_html_email(heading, message, cta_text, cta_link)

    # text content is the fallback for clients that don't support HTML
    # not as critical, so not having special cases for each auth type
    text_content = (
        f"You have been invited by {current_user.email} (admin) to join the EEA GPT Lab.\n"
        "The EEA GPT Lab is a restricted-access application designed as a safe environment to explore the potential benefits and risks of using EEA's public content with state-of-the-art Large Language Models (LLMs). The application is for experimental purposes only, with access limited to users with EEA email addresses and selected contractors. GPT Lab is built with a robust privacy architecture to ensure that sensitive and personal information is not sent to third-party LLM AI providers.\n"
        "To join the EEA GPT Lab, please visit the following link:\n"
        f"{WEB_DOMAIN}/auth/signup?email={user_email}\n"
    )
    if auth_type == AuthType.CLOUD:
        text_content += "You'll be asked to set a password or login with Google to complete your registration."

    send_email(user_email, subject, html_content, text_content)


def send_forgot_password_email(
    user_email: str,
    token: str,
    tenant_id: str,
    mail_from: str = EMAIL_FROM,
) -> None:
    # Builds a forgot password email with or without fancy HTML
    subject = "EEA GPT Lab Forgot Password"
    link = f"{WEB_DOMAIN}/auth/reset-password?token={token}"
    if MULTI_TENANT:
        link += f"&{TENANT_ID_COOKIE_NAME}={tenant_id}"
    message = f"<p>Click the following link to reset your password:</p><p>{link}</p>"
    html_content = build_html_email("Reset Your Password", message)
    text_content = f"Click the following link to reset your password: {link}"
    send_email(user_email, subject, html_content, text_content, mail_from)


def send_user_verification_email(
    user_email: str,
    token: str,
    mail_from: str = EMAIL_FROM,
) -> None:
    # Builds a verification email
    subject = "EEA GPT Lab Email Verification"
    link = f"{WEB_DOMAIN}/auth/verify-email?token={token}"
    message = (
        f"<p>Click the following link to verify your email address:</p><p>{link}</p>"
    )
    html_content = build_html_email("Verify Your Email", message)
    text_content = f"Click the following link to verify your email address: {link}"
    send_email(user_email, subject, html_content, text_content, mail_from)
