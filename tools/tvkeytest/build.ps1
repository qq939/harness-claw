# 构建遥控器按键探针 APK（无 res，aapt2 -> javac -> d8 -> zipalign -> apksigner）
$ErrorActionPreference = 'Continue'
$app = 'C:\Users\qq939\Downloads\hermitclaw\tools\tvkeytest'
$sdk = 'C:\Users\qq939\android-tools\sdk'
$jdk = 'C:\Users\qq939\android-tools\jdk-17.0.20.1+1'
$bt = Join-Path $sdk 'build-tools\34.0.0'
$jar = Join-Path $sdk 'platforms\android-34\android.jar'

$env:JAVA_HOME = $jdk
$env:PATH = "$jdk\bin;$bt;$env:PATH"

Push-Location $app
try {
    Remove-Item -Recurse -Force build -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path build, build\classes, build\dex | Out-Null

    Write-Host '== aapt2 link =='
    & "$bt\aapt2.exe" link -o build\base.apk --manifest AndroidManifest.xml -I $jar --min-sdk-version 21 --target-sdk-version 34
    if ($LASTEXITCODE -ne 0) { throw 'aapt2 link failed' }

    Write-Host '== javac =='
    $srcs = @(Get-ChildItem -Recurse java -Filter *.java | ForEach-Object { $_.FullName })
    $stubs = Join-Path $bt 'core-lambda-stubs.jar'
    $args = @('-source', '8', '-target', '8', '-encoding', 'UTF-8', '-nowarn', '-bootclasspath', "$jar;$stubs", '-d', 'build\classes') + $srcs
    & "$jdk\bin\javac.exe" @args 2>&1 | Where-Object { $_ -notmatch 'bootstrap class path' }
    if ($LASTEXITCODE -ne 0) { throw 'javac failed' }

    Write-Host '== d8 =='
    # 先打成 jar 再喂给 d8：这个版本的 d8 不认裸目录，而直接塞 class 文件列表在 PowerShell 里又被拆坏
    & "$jdk\bin\jar.exe" cf build\classes.jar -C build\classes .
    & "$jdk\bin\java.exe" -cp "$bt\lib\d8.jar" com.android.tools.r8.D8 --lib $jar --min-api 21 --output build\dex build\classes.jar
    if ($LASTEXITCODE -ne 0) { throw 'd8 failed' }

    Write-Host '== pack + align + sign =='
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

    & "$bt\zipalign.exe" -f -p 4 build\unsigned.apk build\aligned.apk
    if ($LASTEXITCODE -ne 0) { throw 'zipalign failed' }

    $ks = 'C:\Users\qq939\Downloads\hermitclaw\tmp\ocs-app\ocs.keystore'
    $signed = Join-Path $app 'build\tvkeytest.apk'
    & "$bt\apksigner.bat" sign --ks $ks --ks-pass pass:ocs123456 --key-pass pass:ocs123456 --v1-signing-enabled true --v2-signing-enabled true --out $signed build\aligned.apk
    if ($LASTEXITCODE -ne 0) { throw 'apksigner failed' }
    Write-Host "== done: $signed =="
} finally {
    Pop-Location
}
