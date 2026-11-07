#Requires -RunAsAdministrator
<#
.SYNOPSIS
    给 hermit.dimond.top 宿主机装好 SSH 服务 + 写入两个 agent 的授权公钥。

.DESCRIPTION
    做的事（幂等，可反复跑）：
      1. 没有 sshd 就装 OpenSSH Server（Windows 可选功能），设成自动启动并启动
      2. 缺 sshd_config 就写一份最小可用配置（含 admin 组专用授权文件那一段）
      3. 缺主机密钥就 ssh-keygen -A
      4. 放行防火墙 22 端口
      5. 把两个 agent 公钥写进
           %ProgramData%\ssh\administrators_authorized_keys   （管理员账号登录时 sshd 只认这个）
           %USERPROFILE%\.ssh\authorized_keys                 （普通账号用）
         并把 admin 文件的 ACL 修正成只允许 SYSTEM + Administrators
      6. 重启 sshd，检查服务状态 + 22 端口监听

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\install_agent_keys.ps1
    powershell -ExecutionPolicy Bypass -File .\install_agent_keys.ps1 -DryRun
#>
[CmdletBinding()]
param(
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin -and -not $DryRun) {
    Write-Host "需要管理员权限，正在提权（UAC 弹窗请点「是」）..." -ForegroundColor Yellow
    try {
        Start-Process powershell -Verb RunAs -ErrorAction Stop -ArgumentList @(
            '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`""
        )
        Write-Host "已在新窗口继续执行，本窗口可以关掉。" -ForegroundColor Green
    } catch {
        Write-Host "提权被拒绝：$($_.Exception.Message)" -ForegroundColor Red
        Write-Host "请手动以管理员身份运行： $PSCommandPath" -ForegroundColor Red
        exit 1
    }
    exit 0
}

# ---------------------------------------------------------------------------
# 要授权的公钥（想加第三个就往数组里加一行）
# ---------------------------------------------------------------------------
$PublicKeys = @(
    # 本机 agent（我自己）
    'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOxkOJyvWXGXoLvyZIxCwB/c/dD6879Cpv7EFl8PI1AU harness-agent@hermit'
    # 另一个 agent
    'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEiKs4bL6Qxj97ClbAgTAIMGoyUk1rkLFeqv05+oIDeS hatch'
)

$SshDir     = Join-Path $env:ProgramData 'ssh'
$AdminKeys  = Join-Path $SshDir 'administrators_authorized_keys'
$UserKeys   = Join-Path $env:USERPROFILE '.ssh\authorized_keys'
$SshdConfig = Join-Path $SshDir 'sshd_config'

# ---------------------------------------------------------------------------
# 1. 安装 / 启动 sshd（失败不抛异常，返回 $false，后面照常写 key）
# ---------------------------------------------------------------------------
function Wait-SshdService([int]$seconds) {
    for ($i = 0; $i -lt $seconds; $i++) {
        $s = Get-Service -Name sshd -ErrorAction SilentlyContinue
        if ($s) { return $s }
        Start-Sleep -Seconds 1
    }
    return $null
}

function Register-SshdService {
    # 极少数机器装了 OpenSSH 但没注册服务（或者被清理过）：用自带 exe 手动注册
    $exe = Join-Path $env:WINDIR 'System32\OpenSSH\sshd.exe'
    if (-not (Test-Path $exe)) { $exe = Join-Path $env:ProgramFiles 'OpenSSH\sshd.exe' }
    if (-not (Test-Path $exe)) { return $null }
    Write-Host "  sshd.exe 在但服务没注册，手动注册服务…" -ForegroundColor Yellow
    & sc.exe create sshd binPath= "`"$exe`"" start= auto DisplayName= "OpenSSH SSH Server" | Out-Null
    & sc.exe description sshd "OpenSSH SSH Server" | Out-Null
    return (Wait-SshdService 5)
}

function Ensure-Sshd {
    $svc = Get-Service -Name sshd -ErrorAction SilentlyContinue
    if (-not $svc) {
        Write-Host "  未发现 sshd 服务，安装 OpenSSH Server…" -ForegroundColor Yellow
        if ($DryRun) {
            Write-Host "[DryRun] 会执行 Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0" -ForegroundColor Cyan
            return $true
        }
        $cap = Get-WindowsCapability -Online -Name 'OpenSSH.Server*' -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($cap -and $cap.State -ne 'Installed') {
            try {
                Add-WindowsCapability -Online -Name $cap.Name | Out-Null
            } catch {
                Write-Warning "  Add-WindowsCapability 失败：$($_.Exception.Message)"
            }
        }
        # 装完后服务注册有延迟，轮询 30 秒；还不行就看 exe 在不在、手动注册
        $svc = Wait-SshdService 30
        if (-not $svc) { $svc = Register-SshdService }
        if (-not $svc) {
            Write-Host "  自动安装失败。手动装法（管理员）：" -ForegroundColor Red
            Write-Host "    Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0" -ForegroundColor Yellow
            Write-Host "  或：设置 -> 应用 -> 可选功能 -> 添加功能 -> OpenSSH 服务器" -ForegroundColor Yellow
            Write-Host "  装完重跑本脚本即可（密钥部分不受影响）" -ForegroundColor Yellow
            return $false
        }
        Write-Host "  OpenSSH Server 安装完成" -ForegroundColor Green
    } else {
        Write-Host "  已安装 sshd（状态：$($svc.Status)）" -ForegroundColor Green
    }

    if ($DryRun) {
        Write-Host "[DryRun] 会把 sshd 设为自动启动并启动（需要管理员）" -ForegroundColor Cyan
        return $true
    }

    try {
        Set-Service -Name sshd -StartupType Automatic
        $agentSvc = Get-Service -Name ssh-agent -ErrorAction SilentlyContinue
        if ($agentSvc -and $agentSvc.Status -ne 'Running') { Start-Service ssh-agent -ErrorAction SilentlyContinue }
        Start-Service sshd -ErrorAction SilentlyContinue
        Write-Host "  sshd 已设为自动启动并启动" -ForegroundColor Green
        return $true
    } catch {
        Write-Warning "  启动 sshd 失败：$($_.Exception.Message)"
        return $false
    }
}

# ---------------------------------------------------------------------------
# 2. 配置 / 主机密钥 / 防火墙
# ---------------------------------------------------------------------------
function Ensure-SshdConfig {
    if (-not (Test-Path $SshdConfig)) {
        Write-Host "  没有 sshd_config，写一份最小配置" -ForegroundColor Yellow
        if ($DryRun) { return }
        $cfg = @"
Port 22
PubkeyAuthentication yes
PasswordAuthentication yes
AuthorizedKeysFile .ssh/authorized_keys
Subsystem sftp sftp-server.exe

Match Group administrators
       AuthorizedKeysFile __PROGRAMDATA__/ssh/administrators_authorized_keys
"@
        $enc = New-Object System.Text.UTF8Encoding($false)
        [System.IO.File]::WriteAllLines($SshdConfig, ($cfg -split "`r?`n"), $enc)
    }
}

function Ensure-HostKeys {
    if ($DryRun) { return }
    if (Test-Path (Join-Path $SshDir 'ssh_host_ed25519_key')) { return }
    $kg = Join-Path $env:ProgramFiles 'OpenSSH\ssh-keygen.exe'
    if (-not (Test-Path $kg)) { $kg = 'ssh-keygen.exe' }
    Write-Host "  生成主机密钥…" -ForegroundColor Yellow
    & $kg -A | Out-Null
}

function Ensure-Firewall {
    $name = 'OpenSSH-Server-In-TCP'
    if (Get-NetFirewallRule -Name $name -ErrorAction SilentlyContinue) {
        Write-Host "  防火墙规则已存在（$name）" -ForegroundColor Green
        return
    }
    if ($DryRun) { Write-Host "[DryRun] 会新建防火墙规则放行 TCP 22" -ForegroundColor Cyan; return }
    New-NetFirewallRule -Name $name -DisplayName 'OpenSSH Server (sshd)' -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 | Out-Null
    Write-Host "  已放行防火墙 TCP 22" -ForegroundColor Green
}

# ---------------------------------------------------------------------------
# 3. 授权公钥
# ---------------------------------------------------------------------------
function Get-KeyFingerprint([string]$line) {
    $parts = $line.Trim() -split '\s+'
    if ($parts.Count -ge 2) { return "$($parts[0]) $($parts[1])" }
    return $line.Trim()
}

function Merge-Keys([string]$path, [string[]]$keys) {
    $existing = @()
    if (Test-Path $path) {
        try {
            $existing = @(Get-Content -LiteralPath $path -Encoding UTF8 -ErrorAction Stop | Where-Object { $_.Trim() -ne '' })
        } catch {
            Write-Warning "读不到 $path（通常是没提权）——按空文件处理，后面会重写"
            $existing = @()
        }
    }
    $seen = New-Object 'System.Collections.Generic.HashSet[string]'
    foreach ($l in $existing) { [void]$seen.Add((Get-KeyFingerprint $l)) }

    $added = @()
    foreach ($k in $keys) {
        $fp = Get-KeyFingerprint $k
        if (-not $seen.Contains($fp)) {
            $existing += $k
            [void]$seen.Add($fp)
            $added += $k
        }
    }

    if ($DryRun) {
        Write-Host "[DryRun] $path" -ForegroundColor Cyan
        Write-Host "         现有 $($existing.Count - $added.Count) 行，将新增 $($added.Count) 行"
        foreach ($a in $added) { Write-Host "         + $a" -ForegroundColor DarkGray }
        return
    }

    $dir = Split-Path -Parent $path
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    if (Test-Path $path) {
        $bak = "$path.bak.$(Get-Date -Format 'yyyyMMdd-HHmmss')"
        Copy-Item -LiteralPath $path -Destination $bak -Force
        Write-Host "  备份: $bak" -ForegroundColor DarkGray
    }
    $enc = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllLines($path, [string[]]$existing, $enc)
    Write-Host "  已写入 $path（共 $($existing.Count) 行，新增 $($added.Count)）" -ForegroundColor Green
}

function Fix-AdminAcl([string]$path) {
    if ($DryRun) { Write-Host "[DryRun] 会修 ACL：去掉继承，只留 SYSTEM + Administrators" -ForegroundColor Cyan; return }
    & icacls $path /inheritance:r | Out-Null
    & icacls $path /grant '*S-1-5-18:(F)' | Out-Null
    & icacls $path /grant '*S-1-5-32-544:(F)' | Out-Null
    & icacls $path /setowner '*S-1-5-32-544' | Out-Null
    Write-Host "  ACL 已修正（SYSTEM + Administrators）" -ForegroundColor Green
}

# ---------------------------------------------------------------------------
# 执行
# ---------------------------------------------------------------------------
Write-Host "=== 1. SSH 服务 ===" -ForegroundColor Yellow
$svcOk = Ensure-Sshd
Ensure-SshdConfig
Ensure-HostKeys
Ensure-Firewall

Write-Host "=== 2. 写入管理员授权文件 ===" -ForegroundColor Yellow
Merge-Keys -path $AdminKeys -keys $PublicKeys
if (-not $DryRun) { Fix-AdminAcl -path $AdminKeys }

Write-Host "=== 3. 写入当前用户授权文件 ===" -ForegroundColor Yellow
Merge-Keys -path $UserKeys -keys $PublicKeys

if (-not $DryRun -and $svcOk) {
    Write-Host "=== 4. 重启 sshd 并检查 ===" -ForegroundColor Yellow
    try {
        Restart-Service sshd
        Start-Sleep -Seconds 2
        Get-Service sshd | Format-Table Name, Status, StartType -AutoSize

        $ok = $false
        for ($i = 0; $i -lt 10; $i++) {
            $listen = @(Get-NetTCPConnection -LocalPort 22 -State Listen -ErrorAction SilentlyContinue).Count
            if ($listen -gt 0) { $ok = $true; break }
            Start-Sleep -Seconds 1
        }
        if ($ok) {
            Write-Host "  22 端口监听: 是" -ForegroundColor Green
        } else {
            Write-Host "  22 端口监听: 否（看 C:\ProgramData\ssh\logs\sshd.log）" -ForegroundColor Red
        }
    } catch {
        Write-Warning "  重启 sshd 失败：$($_.Exception.Message)"
    }
} elseif (-not $DryRun) {
    Write-Host "=== 4. sshd 没跑起来，跳过重启检查 ===" -ForegroundColor Yellow
    Write-Host "  密钥已写好；装完 OpenSSH Server 后再跑一次本脚本就会自动启动" -ForegroundColor Yellow
}

$who = $env:USERNAME
Write-Host ""
Write-Host "完成。用这两把私钥验证（登录名 $who）：" -ForegroundColor Yellow
Write-Host "  ssh -i <harness-agent 私钥> -p 18022 $who@dimond.top"
Write-Host "  ssh -i <hatch 私钥>         -p 18022 $who@dimond.top"
Write-Host "（本机直连则去掉 -p 18022；公网 18022 若不通，先确认 frp 映射）"
