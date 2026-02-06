#!/usr/bin/env python3
"""
Kyocera Printer Health Monitor (Net-SNMP Version, Color Flag)
Works on Python 3.12+ with ZERO pip installs.

Checks:
  ✔ Printer offline
  ✔ Toner low / empty
  ✔ Paper tray low / empty
Sends email alerts via Gmail SMTP.
"""

import subprocess
import smtplib
from email.mime.text import MIMEText
from datetime import datetime

# ======================================================
# CONFIGURATION
# ======================================================

# (IP, Friendly Name, is_color, tray(s)_to_ignore)
PRINTERS = [
    ("192.168.200.67", "georgia-kyocera-bw-2nd-floor", False, []),
    ("192.168.200.70", "georgia-kyocera-bw-5th-floor", False, []),
    ("192.168.200.68", "georgia-kyocera-bw-3rd-floor", False, []),
    ("192.168.200.69", "georgia-kyocera-bw-4th-floor", False, []),
    ("192.168.201.68", "georgia-kyocera-c-main-office", False, [2]), # Ignore tray 2 for this printer.
    ("192.168.200.66", "georgia-kyocera-c-4th-floor-pd1", True, [])
]

COMMUNITY = "public"

SMTP_USER = "pcuenco@elhaynes.org"
SMTP_PASS = "kxlx jvvg zehn rnaj"
MAIL_FROM = SMTP_USER
MAIL_TO = "ga-print-unofficial@elhaynes.org"

SUBJECT_PREFIX = "[GA - PRINTER ALERT]"

# ======================================================
# OIDs
# ======================================================

OID_PRINTER_STATUS = "1.3.6.1.2.1.25.3.5.1.1.1"
OID_TONER_BASE     = "1.3.6.1.2.1.43.11.1.1.9.1"  # .1 K, .2 C, .3 M, .4 Y
OID_TRAY_BASE      = "1.3.6.1.2.1.43.8.2.1.10.1"   # .1 tray1, .2 tray2 ...

TONER_LABELS = {
    1: "Black",
    2: "Cyan",
    3: "Magenta",
    4: "Yellow"
}

# ======================================================
# Helper: SNMP GET via net-snmp CLI
# ======================================================

def snmp_get(ip, oid):
    try:
        result = subprocess.run(
            ["snmpget", "-v2c", "-c", COMMUNITY, ip, oid],
            capture_output=True, text=True, timeout=2
        )
        if result.returncode != 0:
            return None

        line = result.stdout.strip()
        if "=" not in line:
            return None

        # Value is after the last colon
        value_part = line.split(":", 1)[-1].strip()

        try:
            return int(value_part)
        except ValueError:
            return value_part

    except Exception:
        return None

# ======================================================
# Check a single printer
# ======================================================

def check_printer(ip: str, is_color: bool, ignored_trays):
    problems = []

    # ------------------------
    # 1. Offline detection
    # ------------------------
    status = snmp_get(ip, OID_PRINTER_STATUS)
    if status is None:
        problems.append("OFFLINE (no SNMP response)")
        return problems

    if status == 5:
        problems.append("Printer reports DOWN")
#    elif status == 3:
#        problems.append("Printer WARNING state")

    # ------------------------
    # 2. Toner checks
    # ------------------------
    if is_color:
        toner_indices = (1, 2, 3, 4)  # K, C, M, Y
    else:
        toner_indices = (1,)          # Black only

    for t in toner_indices:
        oid = f"{OID_TONER_BASE}.{t}"
        level = snmp_get(ip, oid)

        if level is None:
            continue

        label = TONER_LABELS.get(t, f"Toner{t}")

        # Kyocera codes:
        # -3 = empty / not present
        # -2 = low
        if str(level) == "-3":
            problems.append(f"{label} TONER EMPTY")
        elif str(level) == "-2":
            problems.append(f"{label} TONER LOW")
        else:
            try:
                pct = int(level)
                if pct < 10:
                    problems.append(f"{label} toner <10% ({pct}%)")
            except ValueError:
                pass

    # ------------------------
    # 3. Paper tray levels
    # ------------------------
    for tray in range(1, 6):
    # Skip trays that are intentionally unused for this printer
        if tray in ignored_trays:
            continue

        oid = f"{OID_TRAY_BASE}.{tray}"
        level = snmp_get(ip, oid)

        if level is None:
            continue

        if str(level) == "-3":
            problems.append(f"Tray {tray} EMPTY")
        elif str(level) == "-2":
            problems.append(f"Tray {tray} LOW PAPER")


    return problems

# ======================================================
# Email sender
# ======================================================

def send_email(subject, body):
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = MAIL_FROM
    msg["To"] = MAIL_TO

    with smtplib.SMTP("smtp.gmail.com", 587) as s:
        s.starttls()
        s.login(SMTP_USER, SMTP_PASS)
        s.sendmail(MAIL_FROM, [MAIL_TO], msg.as_string())

# ======================================================
# Main logic
# ======================================================

def main():
    alerts = []

    for ip, name, is_color, ignored_trays in PRINTERS:
        issues = check_printer(ip, is_color, ignored_trays)
        if issues:
            alerts.append(f"{name} ({ip}):\n  - " + "\n  - ".join(issues))

    if alerts:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        body = (
            "Kyocera Printer Health Alert\n\n"
            + "\n\n".join(alerts)
            + f"\n\nTimestamp: {timestamp}\n"
        )
        subject = f"{SUBJECT_PREFIX} Issues Detected - {datetime.now().strftime('%H:%M:%S')}"
        send_email(subject, body)
        print("Alert email sent.")
    else:
        print("All printers healthy.")

if __name__ == "__main__":
    main()
