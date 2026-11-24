param([switch]$Inventory)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
try {
    # Some USB drivers do not report HardwareInterface/Physical consistently.
    $adapters = @(Get-NetAdapter -ErrorAction Stop | ForEach-Object {
        $adapter = $_
        $medium = [int]$adapter.NdisPhysicalMedium
        $wireless = ($medium -in @(1, 9) -or [int]$adapter.InterfaceType -eq 71 -or
            $adapter.MediaType -match '802\.11|Wireless' -or
            $adapter.InterfaceDescription -match 'Wi-Fi|WiFi|Wireless|WLAN|Bluetooth')
        $virtual = ($adapter.Virtual -eq $true -or [int]$adapter.InterfaceType -in @(24, 131) -or
            $adapter.InterfaceDescription -match 'TAP|Virtual|VPN|VMware|Hyper-V|Loopback|Tunnel|ZeroTier|Radmin|Tailscale|WAN Miniport')
        $selectable = -not $wireless -and -not $virtual
        $wired = ($selectable -and ($adapter.MediaType -eq '802.3' -or $medium -eq 14 -or
            [int]$adapter.InterfaceType -eq 6))
        $ip = @(Get-NetIPAddress -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue |
            Where-Object { $_.AddressState -eq 'Preferred' -and -not $_.SkipAsSource -and $_.IPAddress -notmatch '^(169\.254\.|127\.)' } |
            Sort-Object IPAddress | Select-Object -First 1)
        [pscustomobject]@{
            name = [string]$adapter.Name
            description = [string]$adapter.InterfaceDescription
            status = [string]$adapter.Status
            wired = [bool]$wired
            selectable = [bool]$selectable
            device = '\Device\NPF_{' + ([guid]$adapter.InterfaceGuid).ToString().ToUpperInvariant() + '}'
            ip = $(if ($ip.Count) { [string]$ip[0].IPAddress } else { '' })
        }
    })
    if ($Inventory) {
        $route = Find-NetRoute -RemoteIPAddress 223.5.5.5 -ErrorAction SilentlyContinue | Select-Object -First 1
        $supp = Get-Process jmusupplicant -ErrorAction SilentlyContinue | Select-Object -First 1
        [pscustomobject]@{
            adapters = $adapters
            default_alias = $(if ($route) { [string]$route.InterfaceAlias } else { '' })
            supp = $(if ($supp) { $supp.StartTime.ToString('HH:mm:ss') } else { '' })
        } | ConvertTo-Json -Depth 4 -Compress
    } else {
        $ready = @($adapters | Where-Object { $_.wired -and $_.status -eq 'Up' })
        if ($ready.Count -eq 1) { $ready[0].device } else { exit 2 }
    }
} catch {
    [Console]::Error.WriteLine('Adapter enumeration failed.')
    exit 1
}
