param([string]$Title, [string]$Message, [ValidateSet('Warning','Information')][string]$Kind = 'Warning')
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$icon = New-Object System.Windows.Forms.NotifyIcon
$context = New-Object System.Windows.Forms.ApplicationContext
$timer = New-Object System.Windows.Forms.Timer
try {
    $icon.Icon = if ($Kind -eq 'Warning') { [System.Drawing.SystemIcons]::Warning } else { [System.Drawing.SystemIcons]::Information }
    $icon.Text = 'Campus network helper'
    $icon.Visible = $true
    $icon.BalloonTipTitle = $Title
    $icon.BalloonTipText = $Message
    $icon.BalloonTipIcon = [System.Windows.Forms.ToolTipIcon]::$Kind
    $timer.Interval = 15000
    $timer.Add_Tick({ $context.ExitThread() })
    $icon.ShowBalloonTip(10000)
    $timer.Start()
    [System.Windows.Forms.Application]::Run($context)
} finally {
    $timer.Stop()
    $timer.Dispose()
    $icon.Visible = $false
    $icon.Dispose()
    $context.Dispose()
}
