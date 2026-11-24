param([string]$Title, [string]$Message)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$icon = New-Object System.Windows.Forms.NotifyIcon
$context = New-Object System.Windows.Forms.ApplicationContext
$timer = New-Object System.Windows.Forms.Timer
try {
    $icon.Icon = [System.Drawing.SystemIcons]::Warning
    $icon.Text = 'Campus network helper'
    $icon.Visible = $true
    $icon.BalloonTipTitle = $Title
    $icon.BalloonTipText = $Message
    $icon.BalloonTipIcon = [System.Windows.Forms.ToolTipIcon]::Warning
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
