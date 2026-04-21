import smtplib
from email.message import EmailMessage

def send_email(receiver_email: str, message_text: str):

    msg = EmailMessage()
    msg.set_content(message_text) 
    msg['Subject'] = 'Система оповещения школы 2120'
    msg['From'] = "danialgatalskij@gmail.com"
    msg['To'] = receiver_email

    server = smtplib.SMTP("smtp.gmail.com", 587)
    server.starttls()

    try:
        server.login("danialgatalskij@gmail.com", "ahiyguadofhztuly")
        server.send_message(msg) 
        print("Письмо отправлено!")
    except Exception as e:
        print(f"Ошибка: {e}")
    finally:
        server.quit()