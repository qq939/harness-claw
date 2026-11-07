#Requires -RunAsAdministrator
<#
.SYNOPSIS
    给 hermit.dimond.top 宿主机安装/更新 SSH 授权公钥（两个 agent 的 key）。

.DESCRIPTION
    这台机器是 hermit.dimond.top 的宿主机，公网通过 dimond.top:18022 进 SSH（frp -> 本机 22）。
    Windows OpenSSH 的规则：
      · 账号属于 Administrators 组 → 只认 %ProgramData%\ssh\administrators_authorized_keys
      · 普通账号                     → 认 %USERPROFILE%\.ssh\authorized_keys
    所以脚本两个文件都写，并把 administrators_authorized_keys 的 ACL 修成
    「只有 SYSTEM 和 Administrators」，否则 sshd 会直接忽略这个文件（StrictModes）。
    幂等：重复跑不会产生重复行，写之前自动备份。

.EXAMPLE
    # 以管理员身份打开 PowerShell，然后：
    powershell -ExecutionPolicy Bypass -File .\install_agent_keys.ps1
    # 只看看会写什么、不改系统：
    powershell -ExecutionPolicy Bypass -File .\install_agent_keys.ps1 -DryRun
#>
[CmdletBinding()]
param(
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin -and -not $DryRun) {
    Write-Host "需要管理员权限：右键 PowerShell -> 以管理员身份运行，或：" -ForegroundColor Red
    Write-Host "  Start-Process powershell -Verb RunAs -ArgumentList '-ExecutionPolicy','Bypass','-File','$PSCommandPath'"
    exit 1
}

# ---------------------------------------------------------------------------
# 要授权的公钥（想加第三个就直接往数组里加一行）
# ---------------------------------------------------------------------------
$PublicKeys = @(
    # 本机 agent（我自己）
    'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOxkOJyvWXGXoLvyZIxCwB/c/dD6879Cpv7EFl8PI1AU harness-agent@hermit'
    # 另一个 agent
    'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEiKs4bL6Qxj97ClbAgTAIMGoyUk1rkLFeqv05+oIDeS hatch'
)

$AdminKeys = Join-Path $env:ProgramData 'ssh\administrators_authorized_keys'
$UserKeys  = Join-Path $env:USERPROFILE '.ssh\authorized_keys'

function Get-KeyFingerprint([string]$line) {
    # 用 "类型 + base64" 判重（注释可能不同）
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

    # 必须无 BOM，sshd 对 BOM 敏感
    $enc = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllLines($path, [string[]]$existing, $enc)
    Write-Host "  已写入 $path（共 $($existing.Count) 行，新增 $($added.Count)）" -ForegroundColor Green
}

function Fix-AdminAcl([string]$path) {
    if ($DryRun) { Write-Host "[DryRun] 会修 ACL：去掉继承，只留 SYSTEM + Administrators" -ForegroundColor Cyan; return }
    # 用 well-known SID，避免中文/英文系统组名差异
    & icacls $path /inheritance:r | Out-Null
    & icacls $path /grant '*S-1-5-18:(F)' | Out-Null        # SYSTEM
    & icacls $path /grant '*S-1-5-32-544:(F)' | Out-Null    # Administrators
    & icacls $path /setowner '*S-1-5-32-544' | Out-Null
    Write-Host "  ACL 已修正（SYSTEM + Administrators）" -ForegroundColor Green
}

Write-Host "=== 1. 写入管理员授权文件 ===" -ForegroundColor Yellow
Merge-Keys -path $AdminKeys -keys $PublicKeys
if (-not $DryRun) { Fix-AdminAcl -path $AdminKeys }

Write-Host "=== 2. 写入当前用户授权文件（非管理员登录用）===" -ForegroundColor Yellow
Merge-Keys -path $UserKeys -keys $PublicKeys

if (-not $DryRun) {
    Write-Host "=== 3. 重启 sshd 并检查 ===" -ForegroundColor Yellow
    Restart-Service sshd
    Start-Sleep -Seconds 1
    Get-Service sshd | Format-Table Name, Status, StartType -AutoSize
    $listen = (Get-NetTCPConnection -LocalPort 22 -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count
    if ($listen -gt 0) {
        Write-Host "  22 端口监听: 是"
    } else {
        Write-Host "  22 端口监听: 否（检查 sshd 服务）" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "完成。用这两把私钥验证：" -ForegroundColor Yellow
Write-Host "  ssh -i <harness-agent 私钥> -p 18022 qq939@dimond.top"
Write-Host "  ssh -i <hatch 私钥>         -p 18022 qq939@dimond.top"
Write-Host "（本机直连则去掉 -p 18022）"
