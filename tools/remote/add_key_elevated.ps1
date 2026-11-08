$ErrorActionPreference = 'Stop'
$log = 'C:\Users\qq939\Downloads\hermitclaw\tools\remote\add_key.log'
function L($m) { "$([DateTime]::Now.ToString('HH:mm:ss')) $m" | Tee-Object -FilePath $log -Append | Out-Null }
try {
    $f = 'C:\ProgramData\ssh\administrators_authorized_keys'
    $k = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINr5x2h+qKNBG1azfrVAVMH969dEhvY2D+InVYR+KTVp agent@dcf09edbad48'
    $t = if (Test-Path $f) { [IO.File]::ReadAllText($f) } else { '' }
    if ($t -notmatch 'KTVp') {
        [IO.File]::WriteAllText($f, ($t.TrimEnd() + "`r`n" + $k + "`r`n"), (New-Object Text.UTF8Encoding($false)))
        L "appended remote card key, size=$((Get-Item $f).Length)"
    } else {
        L 'key already present'
    }
    icacls $f /inheritance:r /grant '*S-1-5-18:F' /grant '*S-1-5-32-544:F' | Out-Null
    L 'acl ok'
    L 'DONE'
} catch {
    L "FAIL: $($_.Exception.Message)"
    exit 1
}
