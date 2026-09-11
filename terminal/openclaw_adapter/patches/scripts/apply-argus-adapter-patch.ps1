# Argus Adapter compatibility patch for OpenClaw 2026.6.11.
# Makes before_agent_run event.prompt rewrites become the model input.

param(
  [string]$OpenClawRoot = ""
)

$ErrorActionPreference = "Stop"

if (-not $OpenClawRoot) {
  $npmRoot = (& npm.cmd root -g).Trim()
  if (-not $npmRoot) {
    throw "Unable to resolve the global npm root."
  }
  $OpenClawRoot = Join-Path $npmRoot "openclaw"
}

$dist = Join-Path $OpenClawRoot "dist"
if (-not (Test-Path -LiteralPath $dist)) {
  throw "OpenClaw dist directory not found: $dist"
}

$patchFile = Join-Path $PSScriptRoot "..\openclaw-2026.6.11-before-agent-run-prompt-consume.patch"
if (-not (Test-Path -LiteralPath $patchFile)) {
  throw "Patch file not found: $patchFile"
}

$hookMarker = "runBeforeAgentRun"
$constMarker = "const promptForModel = buildCurrentInboundPrompt"
$letMarker = "let promptForModel = buildCurrentInboundPrompt"
$patchedMarker = "const beforeRunEvent = {"

$candidates = @(
  Get-ChildItem -LiteralPath $dist -Filter "selection-*.js" -File |
    Where-Object {
      $text = Get-Content -LiteralPath $_.FullName -Raw -Encoding UTF8
      ($text.Contains($hookMarker)) -and
        ($text.Contains($constMarker) -or $text.Contains($letMarker))
    }
)

if ($candidates.Count -ne 1) {
  throw "Expected exactly one compatible OpenClaw 2026.6.11 selection bundle, found $($candidates.Count)."
}

$target = $candidates[0].FullName
$source = Get-Content -LiteralPath $target -Raw -Encoding UTF8
if ($source.Contains($patchedMarker)) {
  Write-Output "Argus prompt rewrite patch is already applied: $target"
  exit 0
}

$oldHook = @'
							beforeRunResult = await hookRunner.runBeforeAgentRun({
								prompt: promptForModel,
								systemPrompt: systemPromptForHook,
								messages: beforeRunMessages,
								channelId: hookCtx.channelId,
								accountId: params.agentAccountId ?? void 0,
								senderId: params.senderId ?? void 0,
								senderIsOwner: params.senderIsOwner ?? void 0
							}, hookCtx);
'@

$newHook = @'
							const beforeRunEvent = {
								prompt: promptForModel,
								systemPrompt: systemPromptForHook,
								messages: beforeRunMessages,
								channelId: hookCtx.channelId,
								accountId: params.agentAccountId ?? void 0,
								senderId: params.senderId ?? void 0,
								senderIsOwner: params.senderIsOwner ?? void 0
							};
							beforeRunResult = await hookRunner.runBeforeAgentRun(beforeRunEvent, hookCtx);
							if (beforeRunEvent.prompt !== promptForModel) {
								promptForModel = beforeRunEvent.prompt;
								if (currentUserTimestampOverride) currentUserTimestampOverride = {
									...currentUserTimestampOverride,
									alternateText: promptForModel
								};
							}
'@

$lineEnding = if ($source.Contains("`r`n")) { "`r`n" } else { "`n" }
$oldHook = $oldHook -replace "`r?`n", $lineEnding
$newHook = $newHook -replace "`r?`n", $lineEnding

if (-not $source.Contains($constMarker) -or -not $source.Contains($oldHook)) {
  throw "OpenClaw bundle layout does not match the verified 2026.6.11 source."
}

$backup = "$target.argus.orig"
if (-not (Test-Path -LiteralPath $backup)) {
  Copy-Item -LiteralPath $target -Destination $backup
  Write-Output "Backup created: $backup"
}

$patched = $source.Replace($constMarker, $letMarker).Replace($oldHook, $newHook)
if ($patched -eq $source -or -not $patched.Contains($patchedMarker)) {
  throw "Patch produced no verified changes."
}

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($target, $patched, $utf8NoBom)
try {
  & node.exe --check $target
  if ($LASTEXITCODE -ne 0) {
    throw "Patched bundle failed node --check."
  }
} catch {
  Copy-Item -LiteralPath $backup -Destination $target -Force
  throw
}

Write-Output "Patch applied. Restart the OpenClaw Gateway to take effect."
