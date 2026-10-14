<#
.SYNOPSIS
Registers a Task Scheduler task that runs run_daily.py every morning, then
checks it with a test run that posts nothing.

.DESCRIPTION
Run from PowerShell opened with "Run as administrator", in the repo folder:

    powershell -ExecutionPolicy Bypass -File windows\install-task.ps1

The task runs as you, whether or not you're signed in; wakes the PC if it's
asleep (when the power plan allows wake timers); and runs as soon as it can
after a missed start. To change the time, run it again with -Time, for
example -Time 06:30; it replaces the task. To remove the task:

    Unregister-ScheduledTask -TaskName "Discord daily readings and saints" -Confirm:$false
#>
param(
    [string]$Time = "07:00",  # 24-hour HH:mm, local time
    [string]$TaskName = "Discord daily readings and saints"
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $repo "run_daily.py"

$launcher = Get-Command py.exe -ErrorAction SilentlyContinue
if (-not $launcher) {
    throw "The Python launcher (py.exe) wasn't found. Install Python 3.9 or newer from python.org."
}

& $launcher.Source -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)"
if ($LASTEXITCODE -ne 0) { throw "Python 3.9 or newer is required." }
# The task uses this exact python.exe, because py.exe finds Python through
# per-user registry settings that may not be loaded when you're signed out.
$python = (& $launcher.Source -3 -c "import sys; print(sys.executable)").Trim()

# Python on Windows has no built-in time zone data for zoneinfo.
& $python -m pip install --quiet --upgrade tzdata
if ($LASTEXITCODE -ne 0) { throw "Installing the tzdata package failed." }

if (-not (Test-Path (Join-Path $repo ".env"))) {
    throw "No .env file. Copy .env.example to .env and fill in both webhook URLs."
}

$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew

function Invoke-SetupCheck {
    # Runs run_daily.py --dry-run the same way the real task runs, so the
    # account, Python, tzdata, .env, and internet access are all exercised.
    $checkName = "$TaskName (setup check)"
    $action = New-ScheduledTaskAction -Execute $python -Argument "`"$runner`" --dry-run" -WorkingDirectory $repo
    Register-ScheduledTask -TaskName $checkName -Action $action -Principal $principal -Settings $settings -Force | Out-Null
    try {
        Start-ScheduledTask -TaskName $checkName
        $deadline = (Get-Date).AddMinutes(3)
        do {
            Start-Sleep -Seconds 2
            $state = (Get-ScheduledTask -TaskName $checkName).State
            $result = (Get-ScheduledTaskInfo -TaskName $checkName).LastTaskResult
            # 267011 (0x41303) means the task hasn't run yet.
        } while (($state -eq "Running" -or $result -eq 267011) -and (Get-Date) -lt $deadline)
    }
    finally {
        Unregister-ScheduledTask -TaskName $checkName -Confirm:$false
    }
    return $result
}

$result = Invoke-SetupCheck
if ($result -ne 0) {
    throw "The setup check failed (result $result). See logs\daily.log in the repo folder."
}
Write-Host "Setup check passed."

# Start tomorrow so registering after today's time doesn't count as a missed run.
$start = (Get-Date).Date.AddDays(1).Add([TimeSpan]::Parse($Time))
$trigger = New-ScheduledTaskTrigger -Daily -At $start
$action = New-ScheduledTaskAction -Execute $python -Argument "`"$runner`"" -WorkingDirectory $repo
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal `
    -Settings $settings -Description "Posts the GOA daily readings and saints to Discord." -Force | Out-Null

Write-Host "Installed '$TaskName'. It runs daily at $Time, starting $($start.ToString('dddd, MMMM d'))."
