# Runs the Gatekeeper worker every US trading evening through Windows Task Scheduler.
#   powershell -ExecutionPolicy Bypass -File scripts\worker_task.ps1            # show what it would do
#   powershell -ExecutionPolicy Bypass -File scripts\worker_task.ps1 -Install   # create or replace the task
#   powershell -ExecutionPolicy Bypass -File scripts\worker_task.ps1 -Remove    # delete it
# Monday to Friday at 18:00 IST it starts the worker for 9.5 hours (to 03:30 IST), which covers the
# session and the 16:10 NY journal in both summer and winter time. Only while you're logged in.
param([switch]$Install, [switch]$Remove, [string]$At = "18:00")

$name = "Gatekeeper worker"
$root = Split-Path -Parent $PSScriptRoot
$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uv) { Write-Error "uv not found on PATH"; exit 1 }

if ($Remove) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed '$name' (if it existed)."
    exit 0
}

$action = New-ScheduledTaskAction -Execute $uv -Argument "run python -m worker --run-for 34200 --quiet" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 10)

if (-not $Install) {
    Write-Host "Would create '$name': Mon-Fri at $At, in $root"
    Write-Host "  $uv run python -m worker --run-for 34200 --quiet   (log: data\worker.log)"
    Write-Host "Run again with -Install to create it."
    exit 0
}
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "Created '$name': Mon-Fri at $At. Check it in Task Scheduler, or: Get-ScheduledTask -TaskName '$name'"
