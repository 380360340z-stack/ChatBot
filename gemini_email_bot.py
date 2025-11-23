import os
import imaplib
import email
import smtplib
import requests
import markdown
from email.mime.text import MIMEText
import json
import re
 
# --- הגדרות קבועות ---
IMAP_SERVER = "imap.gmail.com"
SMTP_SERVER = "smtp.gmail.com"
THREADS_FILE = "threads.json"
 
EMAIL_ACCOUNT = os.getenv("EMAIL_ACCOUNT")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
 
# --- טעינה ושמירה של השרשורים מקובץ JSON ---
def load_threads():
    try:
        with open(THREADS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"[!] Error loading threads: {e}")
        return {}
 
def save_threads(threads):
    try:
        with open(THREADS_FILE, "w", encoding="utf-8") as f:
            json.dump(threads, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[!] Error saving threads: {e}")
 
# --- ניקוי חתימות והודעות חוזרות ---
def clean_email_body(body):
    # הסרת חתימות סטנדרטיות
    patterns_to_remove = [
        r"--\s*\n.*",               # קו חתימה --
        r"Sent from my .*",          # טקסטים כמו Sent from my iPhone
        r"שלח:.*",                   # שורות של מייל קודם בעברית
        r"נשלח:.*",
        r"From:.*",
        r"To:.*",
        r"Cc:.*",
        r"Subject:.*",
        r"-----Original Message-----",
        r"^>+",                       # ציטוטים מקויים
    ]
    pattern = "|".join(patterns_to_remove)
    body = re.split(pattern, body, flags=re.IGNORECASE | re.MULTILINE)[0]
    return body.strip()
 
# --- קבלת מיילים חדשים ---
def get_unread_emails():
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(EMAIL_ACCOUNT, EMAIL_PASSWORD)
        mail.select("inbox")
 
        result, data = mail.search(None, "(UNSEEN)")
        unread_msg_nums = data[0].split()
        messages = []
 
        for num in unread_msg_nums:
            result, msg_data = mail.fetch(num, "(RFC822)")
            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)
 
            sender = email.utils.parseaddr(msg["From"])[1]
            subject = msg["Subject"] if msg["Subject"] else "(ללא נושא)"
            message_id = msg["Message-ID"]
            in_reply_to = msg.get("In-Reply-To")
            body = ""
 
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        charset = part.get_content_charset() or "utf-8"
                        body += part.get_payload(decode=True).decode(charset, errors="ignore")
            else:
                charset = msg.get_content_charset() or "utf-8"
                body += msg.get_payload(decode=True).decode(charset, errors="ignore")
 
            body = clean_email_body(body)
 
            messages.append({
                "from": sender,
                "subject": subject,
                "body": body,
                "message_id": message_id,
                "in_reply_to": in_reply_to
            })
 
        mail.logout()
        return messages
 
    except Exception as e:
        print(f"[!] Error fetching emails: {e}")
        return []
 
# --- בניית השרשור עבור ג'מיני ---
def build_thread_for_gemini(message, threads):
    thread_id = message["in_reply_to"] or message["message_id"]
 
    if thread_id not in threads:
        threads[thread_id] = []
 
    # הוספת הודעת המשתמש החדשה
    threads[thread_id].append({
        "from": "user",
        "body": message["body"]
    })
 
    # בניית טקסט לג'מיני
    gemini_prompt = ""
    for msg in threads[thread_id]:
        if msg["from"] == "user":
            gemini_prompt += f"[משתמש כתב]:\n{msg['body']}\n\n"
        elif msg["from"] == "gemini":
            gemini_prompt += f"[ג'מיני כתב]:\n{msg['body']}\n\n"
 
    return gemini_prompt, thread_id
 
# --- שליחת מייל כולל שרשור ---
def send_email(to_email, subject, body_text, original_message_id=None):
    try:
        formatted_text = markdown.markdown(body_text)
 
        signature = """
        <hr>
        <div style="color:#666; font-size:14px; margin-top:10px;">
        בינה מלאכותית ג'מיני באימייל נבנה ע"י @טשיקאוור ניוז
        </div>
        """
 
        html_body = f"""
        <html>
            <body style="direction: rtl; text-align: right; font-family: Arial, sans-serif;">
                {formatted_text}
                {signature}
            </body>
        </html>
        """
 
        msg = MIMEText(html_body, "html", "utf-8")
        msg["From"] = EMAIL_ACCOUNT
        msg["To"] = to_email
        msg["Subject"] = subject
 
        if original_message_id:
            msg["In-Reply-To"] = original_message_id
            msg["References"] = original_message_id
 
        with smtplib.SMTP_SSL(SMTP_SERVER, 465) as server:
            server.login(EMAIL_ACCOUNT, EMAIL_PASSWORD)
            server.sendmail(EMAIL_ACCOUNT, to_email, msg.as_string())
 
        print(f"[✔] Sent reply to {to_email}")
 
    except Exception as e:
        print(f"[!] Error sending email: {e}")
 
# --- קבלת תגובה מג'מיני ---
def get_gemini_reply(prompt):
    try:
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
 
        headers = {
            "Content-Type": "application/json",
            "X-goog-api-key": GEMINI_API_KEY
        }
 
        data = {
            "contents": [
                {"parts": [{"text": prompt}]}
            ]
        }
 
        response = requests.post(url, headers=headers, json=data)
 
        if response.status_code == 200:
            result = response.json()
            return result["candidates"][0]["content"]["parts"][0]["text"]
 
        print("[!] Gemini API error:", response.text)
        return "אירעה שגיאה בעת יצירת התגובה."
 
    except Exception as e:
        print(f"[!] Error contacting Gemini API: {e}")
        return "שגיאה פנימית בתקשורת עם Gemini."
 
# --- הפעלת הבוט ---
def main():
    print("Starting Gemini Email Bot...")
 
    threads = load_threads()
    emails = get_unread_emails()
 
    if not emails:
        print("No new emails.")
        return
 
    for msg in emails:
        print(f"[📩] New email from {msg['from']}")
 
        # --- בניית השרשור המסומן ---
        gemini_prompt, thread_id = build_thread_for_gemini(msg, threads)
 
        # --- שליחת השרשור לג'מיני לקבלת תשובה ---
        gemini_reply = get_gemini_reply(gemini_prompt)
 
        # --- שמירת תגובת ג'מיני בשרשור ---
        threads[thread_id].append({
            "from": "gemini",
            "body": gemini_reply
        })
 
        # --- שליחת המייל למשתמש ---
        send_email(
            msg["from"],
            f"Re: {msg['subject']}",
            gemini_reply,
            msg["message_id"]
        )
 
    # --- שמירה עדכנית של השרשורים ---
    save_threads(threads)
 
if __name__ == "__main__":
    main()
                      
