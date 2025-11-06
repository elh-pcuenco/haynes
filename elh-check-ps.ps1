<#
    Remote Print Queue Monitor w/ Gmail SMTP (App Password, Plain Text Email)

    - Polls a Windows print server for queue health
    - Sends a plain-text summary email if anything needs attention
    - Designed to be run from ANY machine that:
        * can reach the print server
        * has rights to query printers/queues
        * can send mail via Gmail SMTP with an app password

    Save as: C:\scripts\elh-check-ps.ps1
#>

### =========================
### CONFIGURATION
### =========================
$PrintServerName   = $env:COMPUTERNAME           # <-- change to the print server hostname or leave as $env:COMPUTERNAME if running locally
$JobThreshold      = 10

# Gmail SMTP auth
$GmailUser         = "pcuenco@elhaynes.org"
$GmailAppPassword  = "kxlx jvvg zehn rnaj" 

# Email headers
$FromAddress       = $GmailUser
$ToAddress         = "signal-unofficial@elhaynes.org"
$SubjectPrefix     = "[KS - PRINT ALERT]"

### =========================
### HELPER: SEND EMAIL VIA GMAIL (PLAIN TEXT)
### =========================
function Send-GmailMailPlainText {
    param(
        [Parameter(Mandatory)][string]$From,
        [Parameter(Mandatory)][string]$To,
        [Parameter(Mandatory)][string]$Subject,
        [Parameter(Mandatory)][string]$Body,
        [Parameter(Mandatory)][string]$SmtpUser,
        [Parameter(Mandatory)][string]$SmtpPass
    )

    $mail = New-Object System.Net.Mail.MailMessage
    $mail.From = $From
    $mail.To.Add($To)
    $mail.Subject = $Subject
    $mail.IsBodyHtml = $false
    $mail.Body = $Body

    $smtp = New-Object System.Net.Mail.SmtpClient("smtp.gmail.com", 587)
    $smtp.EnableSsl = $true
    $smtp.Credentials = New-Object System.Net.NetworkCredential($SmtpUser, $SmtpPass)

    $smtp.Send($mail)

    $mail.Dispose()
    $smtp.Dispose()
}

### =========================
### COLLECT REMOTE PRINTER / QUEUE STATUS
### =========================

# Try to get all printers from the remote print server
try {
    $printers = Get-Printer -ComputerName $PrintServerName -ErrorAction Stop
}
catch {
    Write-Error "Failed to query printers on $PrintServerName. $_"
    exit 1
}

$alerts = @()

foreach ($printer in $printers) {
    $printerName        = $printer.Name
    $printerShare       = $printer.ShareName
    $printerErrorState  = $printer.PrinterStatus
    $printerWorkOffline = $printer.WorkOffline
    $printerComment     = $printer.Comment

    # Normalize status to string so we can compare it
    $statusText = "$printerErrorState".Trim()

    $jobCount        = 0
    $jobPreviewLines = @()

    try {
        $jobs = Get-PrintJob -ComputerName $PrintServerName -PrinterName $printerName -ErrorAction Stop
        $jobCount = ($jobs | Measure-Object).Count

        $jobPreviewLines = $jobs |
            Select-Object -First 5 JobId, UserName, Document, PagesPrinted, TotalPages, SubmittedTime |
            ForEach-Object {
                "    JobId {0} | {1} | {2} | {3}/{4} pages | {5}" -f `
                    $_.JobId,
                    $_.UserName,
                    $_.Document,
                    $_.PagesPrinted,
                    $_.TotalPages,
                    $_.SubmittedTime
            }
    }
    catch {
        # Couldn't query jobs; leave $jobCount at 0, that's fine.
        $jobs = @()
    }

    # Decide if this printer is actually a problem.
    $problems = @()

    # Condition 1: queue backlog
    if ($jobCount -gt $JobThreshold) {
        $problems += "High queue depth ($jobCount jobs > $JobThreshold)"
    }

    # Condition 2: offline / unhealthy
    # Rule you asked for:
    #   - If status is literally "Normal", DO NOT complain about status.
    #   - Otherwise, complain if WorkOffline is True OR status is something other than Normal.
    if ($statusText -ne "Normal") {
        if ($printerWorkOffline -eq $true) {
            $problems += "Printer not healthy (Status=$statusText, WorkOffline=$printerWorkOffline)"
        } else {
            # If it's not Normal AND not explicitly offline, it could be things like "Error", "Offline", etc.
            # We still want to flag that so you see it.
            $problems += "Printer not healthy (Status=$statusText)"
        }
    }

    # If status is Normal AND there is no backlog, then $problems might incorrectly have that last line.
    # Let's clean that logic up by removing false positives:
    if ($statusText -eq "Normal" -and $jobCount -le $JobThreshold -and $printerWorkOffline -ne $true) {
        # In this case we consider it healthy; wipe the problems.
        $problems = @()
    }

    # Only add this printer to the alert list if there are problems left
    if ($problems.Count -gt 0) {

        $alertText = @()
        $alertText += "PrinterName : $printerName"
        $alertText += "ShareName   : $printerShare"
        $alertText += "Comment     : $printerComment"
        $alertText += "JobCount    : $jobCount"
        $alertText += "Status      : $statusText"
        $alertText += "WorkOffline : $printerWorkOffline"
        $alertText += "Problems    : " + ($problems -join "; ")

        if ($jobPreviewLines.Count -gt 0) {
            $alertText += "Top Jobs:"
            $alertText += $jobPreviewLines
        }

        $alertText += ""
        $alerts += ($alertText -join "`r`n")
    }
}


### =========================
### IF THERE ARE PROBLEMS, SEND EMAIL
### =========================

if ($alerts.Count -gt 0) {

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

    # Build the plain text body
    $bodyLines = @()
    $bodyLines += "Print Queue Monitor Alert"
    $bodyLines += "Server     : $PrintServerName"
    $bodyLines += "Timestamp  : $timestamp"
    $bodyLines += "Threshold  : $JobThreshold jobs"
    $bodyLines += ""
    $bodyLines += "StatusCode key:"
    $bodyLines += "    3 = Idle"
    $bodyLines += "    4 = Printing"
    $bodyLines += "    5 = Warmup"
    $bodyLines += "Anything else, or WorkOffline=True, is treated as unhealthy."
    $bodyLines += ""
    $bodyLines += "---- Problem Printers ----"
    $bodyLines += ""

    # add each printer block separated by a line
    $bodyLines += ($alerts -join "`r`n-------------------------`r`n")

    $bodyLines += ""
    $bodyLines += "End of report."

    $finalBody = $bodyLines -join "`r`n"

    $subject = "$SubjectPrefix $PrintServerName print queue issues detected"

    try {
        Send-GmailMailPlainText `
            -From      $FromAddress `
            -To        $ToAddress `
            -Subject   $subject `
            -Body      $finalBody `
            -SmtpUser  $GmailUser `
            -SmtpPass  $GmailAppPassword
    }
    catch {
        Write-Error "Failed to send alert email via Gmail SMTP: $_"
    }

}
else {
    # No alert-worthy printers/queues
    # Write-Output "$(Get-Date) - All printers on $PrintServerName healthy."
}