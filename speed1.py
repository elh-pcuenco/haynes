import speedtest
import smtplib
import datetime
import os  # Securely fetch email credentials
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Function to run speed test using the speedtest module
def run_speed_test():
    try:
        st = speedtest.Speedtest()
        st.get_best_server()  # Select the best server based on ping
        
        download_speed = st.download() / 1_000_000  # Convert to Mbps
        upload_speed = st.upload() / 1_000_000  # Convert to Mbps
        ping = st.results.ping

        result = f"""
        Speed Test Results - {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

        Download Speed: {download_speed:.2f} Mbps
        Upload Speed: {upload_speed:.2f} Mbps
        Ping: {ping:.2f} ms
        """
        return result
    except Exception as e:
        return f"Speed test failed: {e}"

# Function to send an email with the speed test results
def send_email(speed_results):
    sender_email = os.getenv("EMAIL_USER")  # Use environment variable for security
    receiver_email = "pcuenco@elhaynes.org"
    app_password = os.getenv("EMAIL_PASS")  # Securely fetch email password

    if not sender_email or not app_password:
        print("Error: Email credentials not set. Please configure environment variables.")
        return

    subject = "Automated Network Speed Test Results"

    msg = MIMEMultipart()
    msg["From"] = sender_email
    msg["To"] = receiver_email
    msg["Subject"] = subject
    msg.attach(MIMEText(speed_results, "plain"))

    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(sender_email, app_password)
        server.sendmail(sender_email, receiver_email, msg.as_string())
        server.quit()
        print("Email sent successfully!")
    except Exception as e:
        print(f"Failed to send email: {e}")

# Run the script
if __name__ == "__main__":
    results = run_speed_test()
    print(results)  # Print results in case of debugging
    send_email(results)


## setx EMAIL_USER "your_email@gmail.com"
## setx EMAIL_PASS "your_app_password"
##