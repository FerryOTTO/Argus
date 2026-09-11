// OpenClaw 模型跟随切换：企业版 <-> 个人版（开发）
//
// 约定：
// - 企业版：OpenClaw 的 deepseek 提供商改走企业网关（remote.json 里终端 LLM 凭据的 base_url + api_key），
//   可用模型收敛为网关允许范围；切回个人版时原样还原。
// - 个人版快照只存一份 sidecar（openclaw.json.argus-personal.json），首次切换时生成，
//   之后不再覆盖；另兼容此前一次手工切换留下的 openclaw.json.pre-ent-switch.bak。
const fs = require('fs')
const path = require('path')

const ENTERPRISE_BASE_URL = 'http://127.0.0.1:8080/v1'
const ENTERPRISE_MODEL = 'deepseek/deepseek-v4-flash'
const PERSONAL_SIDECAR = 'openclaw.json.argus-personal.json'
const LEGACY_MANUAL_BAK = 'openclaw.json.pre-ent-switch.bak'

function readJson(filePath) {
  const raw = fs.readFileSync(filePath, 'utf8').replace(/^\uFEFF/, '')
  return JSON.parse(raw)
}

function writeJson(filePath, obj) {
  fs.writeFileSync(filePath, `${JSON.stringify(obj, null, 2)}\n`, 'utf8')
}


function getPrimary(cfg) {
  if (!cfg || typeof cfg !== 'object') return null
  const m = cfg.agents && cfg.agents.defaults && cfg.agents.defaults.model
  return (m && m.primary) || null
}

function setPrimary(cfg, value) {
  if (!cfg || typeof cfg !== 'object') return
  cfg.agents = cfg.agents || {}
  cfg.agents.defaults = cfg.agents.defaults || {}
  cfg.agents.defaults.model = cfg.agents.defaults.model || {}
  cfg.agents.defaults.model.primary = value
}

function getDeepseek(cfg) {
  if (!cfg || typeof cfg !== 'object') return null
  cfg.models = cfg.models || {}
  cfg.models.providers = cfg.models.providers || {}
  cfg.models.providers.deepseek = cfg.models.providers.deepseek || {}
  return cfg.models.providers.deepseek
}

// 确保个人版快照存在（只建一次）。返回快照路径或 null。
function ensurePersonalSnapshot(openclawConfigPath) {
  const dir = path.dirname(openclawConfigPath)
  const sidecar = path.join(dir, PERSONAL_SIDECAR)
  if (fs.existsSync(sidecar)) return sidecar
  const legacy = path.join(dir, LEGACY_MANUAL_BAK)
  try {
    if (fs.existsSync(legacy)) {
      // 之前手工切换时备份的就是真正的个人版原文，直接沿用。
      fs.copyFileSync(legacy, sidecar)
    } else {
      fs.copyFileSync(openclawConfigPath, sidecar)
    }
    return sidecar
  } catch {
    return null
  }
}

// 切到企业版：deepseek 走企业网关。幂等（已在网关上则只返回 unchanged）。
function switchToEnterprise(openclawConfigPath, remoteJsonPath) {
  if (!openclawConfigPath || !fs.existsSync(openclawConfigPath)) {
    return { ok: false, reason: 'openclaw_config_missing' }
  }
  let llm = null
  try {
    const remote = readJson(remoteJsonPath)
    llm = remote && remote.llm
  } catch {
    llm = null
  }
  if (!llm || !llm.api_key) {
    // 终端尚未注册（无 LLM 凭据）：不碰 OpenClaw 配置。
    return { ok: false, reason: 'no-llm-credential' }
  }
  const baseUrl = String(llm.base_url || ENTERPRISE_BASE_URL).trim() || ENTERPRISE_BASE_URL
  let cfg
  try {
    cfg = readJson(openclawConfigPath)
  } catch {
    return { ok: false, reason: 'openclaw_config_invalid' }
  }
  const ds = getDeepseek(cfg)
  if (!ds) return { ok: false, reason: 'openclaw_config_invalid' }
  if (ds.baseUrl === baseUrl && ds.apiKey === llm.api_key) {
    ensurePersonalSnapshot(openclawConfigPath)
    if (getPrimary(cfg) === ENTERPRISE_MODEL) {
      return { ok: true, unchanged: true, baseUrl }
    }
    setPrimary(cfg, ENTERPRISE_MODEL)
    try {
      writeJson(openclawConfigPath, cfg)
    } catch {
      return { ok: false, reason: 'write_failed' }
    }
    return { ok: true, unchanged: false, baseUrl, primary: ENTERPRISE_MODEL }
  }
  const backup = ensurePersonalSnapshot(openclawConfigPath)
  if (!backup) return { ok: false, reason: 'backup_failed' }
  ds.baseUrl = baseUrl
  ds.apiKey = llm.api_key
  ds.api = ds.api || 'openai-completions'
  setPrimary(cfg, ENTERPRISE_MODEL)
  try {
    writeJson(openclawConfigPath, cfg)
  } catch {
    return { ok: false, reason: 'write_failed' }
  }
  return { ok: true, unchanged: false, baseUrl, backup, primary: ENTERPRISE_MODEL }
}

// 切回个人版：按快照还原 deepseek 提供商整段。幂等。
function switchToPersonal(openclawConfigPath) {
  if (!openclawConfigPath || !fs.existsSync(openclawConfigPath)) {
    return { ok: false, reason: 'openclaw_config_missing' }
  }
  const dir = path.dirname(openclawConfigPath)
  const sidecar = path.join(dir, PERSONAL_SIDECAR)
  if (!fs.existsSync(sidecar)) {
    // 快照丢了就别乱动：宁可不动，不可写错。
    return { ok: false, reason: 'no-personal-backup' }
  }
  let cfg
  let snap
  try {
    cfg = readJson(openclawConfigPath)
    snap = readJson(sidecar)
  } catch {
    return { ok: false, reason: 'openclaw_config_invalid' }
  }
  const ds = getDeepseek(cfg)
  const snapDs = snap && snap.models && snap.models.providers && snap.models.providers.deepseek
  if (!ds || !snapDs) return { ok: false, reason: 'openclaw_config_invalid' }
  const snapPrimary = (snap && snap.agents && snap.agents.defaults && snap.agents.defaults.model && snap.agents.defaults.model.primary) || null
  const primaryNeedsRestore = Boolean(snapPrimary) && getPrimary(cfg) !== snapPrimary
  if (ds.baseUrl === snapDs.baseUrl && ds.apiKey === snapDs.apiKey && !primaryNeedsRestore) {
    return { ok: true, unchanged: true, baseUrl: ds.baseUrl }
  }
  cfg.models.providers.deepseek = snapDs
  if (snapPrimary) setPrimary(cfg, snapPrimary)
  try {
    writeJson(openclawConfigPath, cfg)
  } catch {
    return { ok: false, reason: 'write_failed' }
  }
  return { ok: true, unchanged: false, baseUrl: snapDs.baseUrl }
}

module.exports = {
  ENTERPRISE_BASE_URL,
  ENTERPRISE_MODEL,
  PERSONAL_SIDECAR,
  switchToEnterprise,
  switchToPersonal,
}

