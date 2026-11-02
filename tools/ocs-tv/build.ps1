# Build ocs TV APK without Gradle: aapt2 -> javac -> d8 -> zipalign -> apksigner
$ErrorActionPreference = 'Continue'
$app = 'C:\Users\qq939\Downloads\hermitclaw\tmp\ocs-tv'
$sdk = 'C:\Users\qq939\android-tools\sdk'
$jdk = 'C:\Users\qq939\android-tools\jdk-17.0.20.1+1'
$bt = Join-Path $sdk 'build-tools\34.0.0'
$jar = Join-Path $sdk 'platforms\android-34\android.jar'

$env:JAVA_HOME = $jdk
$env:PATH = "$jdk\bin;$bt;$env:PATH"

Push-Location $app
try {
    Remove-Item -Recurse -Force build -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path build, build\classes, build\dex, build\gen | Out-Null

    Write-Host '== 1. aapt2 compile =='
    & "$bt\aapt2.exe" compile --dir res -o build\res.zip
    if ($LASTEXITCODE -ne 0) { throw 'aapt2 compile failed' }

    Write-Host '== 2. aapt2 link =='
    & "$bt\aapt2.exe" link -o build\base.apk --manifest AndroidManifest.xml -I $jar --min-sdk-version 21 --target-sdk-version 34 --java build\gen build\res.zip
    if ($LASTEXITCODE -ne 0) { throw 'aapt2 link failed' }

    Write-Host '== 2.5 generate ShimJs.java =='
    $js = [IO.File]::ReadAllText((Join-Path $app 'shim.js'))
    $lit = $js | ConvertTo-Json -Compress    # JSON string == Java string literal
    New-Item -ItemType Directory -Force -Path (Join-Path $app 'build\gen2\com\harness\ocs\tv') | Out-Null
    $java = "package com.harness.ocs.tv;`npublic final class ShimJs {`n    public static final String JS = $lit;`n}`n"
    [IO.File]::WriteAllText((Join-Path $app 'build\gen2\com\harness\ocs\tv\ShimJs.java'), $java, (New-Object Text.UTF8Encoding($false)))
    Write-Host '== 3. javac =='
    $stubs = Join-Path $bt 'core-lambda-stubs.jar'
    $srcs = @(Get-ChildItem -Recurse java -Filter *.java | ForEach-Object { $_.FullName }) + @(Get-ChildItem -Recurse build\gen2 -Filter *.java | ForEach-Object { $_.FullName })
    $rs = Get-ChildItem -Recurse build\gen -Filter *.java -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName }
    $args = @('-source', '8', '-target', '8', '-encoding', 'UTF-8', '-nowarn', '-Xlint:none', '-bootclasspath', "$jar;$stubs", '-d', 'build\classes') + $srcs + $rs
    & "$jdk\bin\javac.exe" @args 2>&1 | Where-Object { $_ -notmatch 'bootstrap class path' }
    if ($LASTEXITCODE -ne 0) { throw 'javac failed' }

    Write-Host '== 4. d8 =='
    $classes = Get-ChildItem -Recurse build\classes -Filter *.class | ForEach-Object { $_.FullName }
    & "$bt\d8.bat" --lib $jar --min-api 21 --output build\dex @classes
    if ($LASTEXITCODE -ne 0) { throw 'd8 failed' }

    Write-Host '== 5. pack classes.dex =='
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $out = Join-Path $app 'build\unsigned.apk'
    Copy-Item build\base.apk $out -Force
    $zip = [System.IO.Compression.ZipFile]::Open($out, 'Update')
    try {
        $entry = $zip.CreateEntry('classes.dex', [System.IO.Compression.CompressionLevel]::Optimal)
        $es = $entry.Open()
        $bytes = [System.IO.File]::ReadAllBytes((Join-Path $app 'build\dex\classes.dex'))
        $es.Write($bytes, 0, $bytes.Length)
        $es.Close()
    } finally { $zip.Dispose() }

    Write-Host '== 6. zipalign =='
    & "$bt\zipalign.exe" -f -p 4 build\unsigned.apk build\aligned.apk
    if ($LASTEXITCODE -ne 0) { throw 'zipalign failed' }

    Write-Host '== 7. sign (reuse phone keystore) =='
    $ks = 'C:\Users\qq939\Downloads\hermitclaw\tmp\ocs-app\ocs.keystore'
    $signed = Join-Path $app 'build\ocs-tv.apk'
    & "$bt\apksigner.bat" sign --ks $ks --ks-pass pass:ocs123456 --key-pass pass:ocs123456 --v1-signing-enabled true --v2-signing-enabled true --out $signed build\aligned.apk
    if ($LASTEXITCODE -ne 0) { throw 'apksigner failed' }

    & "$bt\apksigner.bat" verify --print-certs $signed
    Write-Host "== done: $signed =="
    'size: {0:N2} MB' -f ((Get-Item $signed).Length / 1MB)
} finally {
    Pop-Location
}
