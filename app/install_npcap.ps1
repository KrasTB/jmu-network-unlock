$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
try {
    $npcapLibrary = Join-Path $env:SystemRoot 'System32\Npcap\wpcap.dll'
    if (-not (Test-Path -LiteralPath $npcapLibrary)) {
        $answer = [System.Windows.Forms.MessageBox]::Show(
            "需要先安装 Npcap。是否从官网下载并打开官方安装器？`r`n`r`n安装时启用 WinPcap API 兼容模式；普通权限使用时不要限制为仅管理员访问。`r`n下载需要可用的互联网连接，也可先自行从 npcap.com 安装。",
            '安装 Npcap', 'YesNo', 'Information')
        if ($answer -ne [System.Windows.Forms.DialogResult]::Yes) { exit 0 }
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $downloadDirectory = Join-Path ([IO.Path]::GetTempPath()) ('jmu-npcap-' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $downloadDirectory | Out-Null
        $installer = Join-Path $downloadDirectory 'npcap-1.90.exe'
        Invoke-WebRequest -Uri 'https://npcap.com/dist/npcap-1.90.exe' -OutFile $installer -UseBasicParsing -TimeoutSec 90
        $expectedHash = '682B57E1C05EF375931975C9D6DED40888F4BFDF9F4B11571E654F962F1199B6'
        $actualHash = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash
        $signature = Get-AuthenticodeSignature -LiteralPath $installer
        if ($actualHash -ne $expectedHash -or $signature.Status -ne 'Valid' -or
            $signature.SignerCertificate.Subject -notmatch '(^|,\s*)CN=Nmap Software LLC(,|$)') {
            throw 'Npcap 安装包校验未通过，已停止运行。请从 npcap.com 核对下载。'
        }
        $installation = Start-Process -FilePath $installer -Wait -PassThru -WindowStyle Normal
        if ($installation.ExitCode -eq 3010) {
            [System.Windows.Forms.MessageBox]::Show('Npcap 安装要求重启电脑，请重启后再打开助手。', '安装完成', 'OK', 'Information') | Out-Null
            exit 0
        }
        if ($installation.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $npcapLibrary)) {
            throw 'Npcap 尚未完成安装。请确认安装成功后重新打开助手。'
        }
    }
} catch {
    [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'JMU 夜间联网', 'OK', 'Error') | Out-Null
    exit 1
}
