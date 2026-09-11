<template>
  <div class="ent-mini" :class="{ 'is-dark': darkMode, 'in-window': miniWindow }">
    <template v-if="view === 'home'">
      <header class="ent-mini__head">
        <div class="ent-mini__user">
          <span class="ent-mini__avatar"><ShieldCheck :size="16" :stroke-width="1.8" /></span>
          <div class="ent-mini__who">
            <strong>{{ terminalName || "企业终端" }}</strong>
            <small>{{ enterpriseName ? (enterpriseName + " · " + levelText) : "未绑定企业" }}</small>
          </div>
        </div>
        <div class="ent-mini__btns">
          <button type="button" class="ent-mini__gear" @click="view = 'settings'" aria-label="设置">
            <Settings :size="16" :stroke-width="1.8" />
          </button>
        </div>
      </header>
      <div class="ent-mini__body">
        <section class="ent-mini__quota">
          <div class="ent-mini__quota-head"><span>{{ quotaTitle }}</span><strong>{{ quotaRight }}</strong></div>
          <div class="ent-mini__bar"><i :style="{ width: quotaPct + '%' }"></i></div>
          <div class="ent-mini__quota-sub">{{ quotaSub }}</div>
        </section>
        <section class="ent-mini__sec">
          <div class="ent-mini__sec-title">安全概况</div>
          <div class="ent-mini__row"><span>防护模块</span><strong>{{ modulesText }}</strong></div>
          <div class="ent-mini__row"><span>审计事件</span><strong>{{ auditText }}</strong></div>
        </section>
        <section class="ent-mini__sec">
          <div class="ent-mini__sec-title">连接与同步</div>
          <div class="ent-mini__row"><span>服务状态</span><strong :class="online ? 'ok' : 'bad'">{{ servicesText }}</strong></div>
          <div class="ent-mini__row"><span>配置版本</span><strong>{{ configText }}</strong></div>
          <div class="ent-mini__row"><span>同步状态</span><strong>{{ syncText }}</strong></div>
        </section>
        <p class="ent-mini__note">{{ noteText }}</p>
      </div>
    </template>
    <template v-else>
      <header class="ent-mini__head">
        <div class="ent-mini__user">
          <button type="button" class="ent-mini__backbtn" @click="view = 'home'" aria-label="返回">
            <ArrowLeft :size="16" :stroke-width="1.8" />
          </button>
          <div class="ent-mini__who">
            <strong>设置</strong>
            <small>{{ terminalName || "企业终端" }}</small>
          </div>
        </div>
      </header>
      <div class="ent-mini__body ent-mini__body--scroll">
        <section class="ent-mini__sec">
          <div class="ent-mini__sec-title">通用</div>
          <div class="ent-mini__srow">
            <div class="ent-mini__srow-text"><strong>一键同步</strong><small>立即刷新用量、配置与连接状态</small></div>
            <button type="button" class="ent-mini__act" @click="syncNow">同步</button>
          </div>
          <div class="ent-mini__srow">
            <div class="ent-mini__srow-text"><strong>请求提权</strong><small>向企业管理员申请更高配额</small></div>
            <button type="button" class="ent-mini__act" @click="requestElevation">申请</button>
          </div>
        </section>
        <section class="ent-mini__sec">
          <div class="ent-mini__sec-title">管理员</div>
          <div class="ent-mini__srow">
            <div class="ent-mini__srow-text"><strong>打开企业后台 <em>管理员</em></strong><small>在系统浏览器中打开管理控制台</small></div>
            <button type="button" class="ent-mini__act" @click="openAdmin">打开</button>
          </div>
        </section>
        <section class="ent-mini__sec">
          <div class="ent-mini__sec-title">本机</div>
          <div class="ent-mini__row"><span>终端</span><strong>{{ terminalName || "--" }}</strong></div>
          <div class="ent-mini__row"><span>企业</span><strong>{{ enterpriseName || "--" }}</strong></div>
          <div class="ent-mini__row"><span>配置版本</span><strong>{{ configText }}</strong></div>
          <div class="ent-mini__srow ent-mini__srow--dev">
            <div class="ent-mini__srow-text"><strong>回个人版</strong><small>开发期临时入口</small></div>
            <button type="button" class="ent-mini__act" @click="emit('back-personal')">返回</button>
          </div>
        </section>
        <p v-if="promoteMsg" class="ent-mini__promote">{{ promoteMsg }}</p>
      </div>
    </template>
  </div>
</template>
<script setup>
import { computed, onMounted, ref } from "vue";
const emit = defineEmits(["back-personal"]);
import { ShieldCheck, Settings, ArrowLeft } from "lucide-vue-next";
const props = defineProps({ darkMode: { type: Boolean, default: false }, miniWindow: { type: Boolean, default: false } });
const view = ref("home");
const enterpriseName = ref(""); const terminalName = ref(""); const level = ref("member");
const levelText = computed(() => ({ member: "成员", admin: "管理员", owner: "所有者" }[level.value] || level.value));
const online = ref(false); const servicesText = ref("检查中…");
const usageTokens = ref(null); const auditN = ref(0);
const quota = ref(null);
const modulesText = ref("--"); const auditText = ref("--");
const configText = ref("--"); const syncText = ref("未同步"); const noteText = ref("正在连接企业同步状态…");
const promoteMsg = ref("");
const quotaTitle = computed(() => {
  if (!quota.value) return "累计用量";
  const t = String(quota.value.quota_type || "");
  if (t === "rpm" || t === "rpd") return "请求次数配额（" + (t === "rpm" ? "每分钟" : "每天") + "）";
  return "Token 配额（" + (t === "tpm" ? "每分钟" : "每天") + "）";
});
const quotaPct = computed(() => {
  if (!quota.value || !(quota.value.limit_value > 0) || quota.value.used == null) return 0;
  return Math.min(100, Math.round((quota.value.used / quota.value.limit_value) * 100));
});
const quotaRight = computed(() => {
  if (!quota.value || quota.value.used == null) return usageTokens.value != null ? (fmt(usageTokens.value) + " tokens") : "--";
  const unit = (String(quota.value.quota_type).charAt(0) === "t") ? " tokens" : " 次";
  return fmt(quota.value.used) + " / " + fmt(quota.value.limit_value) + unit;
});
const quotaSub = computed(() => {
  if (!quota.value || quota.value.used == null || !(quota.value.limit_value > 0)) {
    return "已用 " + (usageTokens.value != null ? fmt(usageTokens.value) + " tokens" : "--") + " · 审计 " + auditN.value + " 条 · 配额由企业管理员分配";
  }
  const left = quota.value.limit_value - quota.value.used;
  const unit = (String(quota.value.quota_type).charAt(0) === "t") ? " tokens" : " 次";
  return "还剩 " + fmt(Math.max(0, left)) + unit + " · 已用 " + quotaPct.value + "%";
});
function fmt(n){ try{ return Number(n).toLocaleString("en-US"); }catch(e){ return String(n); } }
async function probe(url){ try{ const r = await fetch(url,{cache:"no-store"}); return r.ok; }catch(e){ return false; } }
async function refresh(manual){
  try{
    const s = await (await fetch("http://127.0.0.1:8000/v1/local/enterprise/status")).json();
    const d = s.data || {};
    enterpriseName.value = d.enterprise_name || "";
    terminalName.value = d.terminal_name || "";
    level.value = d.level || "member";
    auditN.value = d.audit_events_local || 0;
    const curs = d.cursors || {};
    if (curs.token_usage_total != null) usageTokens.value = curs.token_usage_total;
    if (d.quota || curs.quota) quota.value = d.quota || curs.quota;
    if (curs.config_applied_version != null) configText.value = "v" + curs.config_applied_version;
    else configText.value = curs.last_report_at || curs.last_heartbeat_at || "--";
  }catch(e){}
  try{
    const resp = await fetch("http://127.0.0.1:8000/v1/remote/status");
    if(resp.ok){
      const r = await resp.json().catch(() => null);
      if(r && r.data){
        if(r.data.enterprise_name) enterpriseName.value = r.data.enterprise_name;
        if(r.data.terminal_name) terminalName.value = r.data.terminal_name;
        if(r.data.level) level.value = r.data.level;
        if(r.data.totals && r.data.totals.token_usage_total != null) usageTokens.value = r.data.totals.token_usage_total;
        if(r.data.quota) quota.value = r.data.quota;
        noteText.value = r.data.bound ? "守护在后台运行，用量与配置自动同步。" : ("未接入企业版：" + (r.data.note || "请先用注册码绑定") + "，守护仍在后台运行。");
      }
    }else{ noteText.value = "企业同步接口不可达：请确认 8000 已启动，守护仍在后台运行。"; }
  }catch(e){ noteText.value = "企业同步接口不可达：请确认 8000 已启动，守护仍在后台运行。"; }
  try{
    const cfg = await (await fetch("http://127.0.0.1:8000/v1/local/config")).json();
    const snap = (cfg.data && cfg.data.snapshot) || {};
    const mods = snap.modules || cfg.data.modules || {};
    const keys = Object.keys(mods);
    if(keys.length){ const on = keys.filter(k => mods[k] && mods[k].enabled !== false).length; modulesText.value = on + " / " + keys.length + " 运行中"; }
    else modulesText.value = "--";
  }catch(e){ modulesText.value = "--"; }
  auditText.value = auditN.value + " 条";
  try{
    const fa = await probe("http://127.0.0.1:8000/health");
    const oc = await probe("http://127.0.0.1:18789/health");
    // Step 5：新链路下 Bridge(:18080)不再拉起，不再计入 online；老链路过渡时可恢复三探针。
    const legacy = await probe("http://127.0.0.1:18080/health");
    if (legacy) {
      online.value = fa && oc && legacy;
      servicesText.value = "F:" + (fa ? "ok" : "down") + " O:" + (oc ? "ok" : "down") + " B:ok(legacy)";
    } else {
      online.value = fa && oc;
      servicesText.value = "F:" + (fa ? "ok" : "down") + " O:" + (oc ? "ok" : "down");
    }
  }catch(e){ online.value=false; servicesText.value="8000 down"; }
  if(manual){ const t = new Date(); syncText.value = "已同步 " + String(t.getHours()).padStart(2,"0") + ":" + String(t.getMinutes()).padStart(2,"0") + ":" + String(t.getSeconds()).padStart(2,"0"); }
}
function syncNow(){ syncText.value = "同步中…"; refresh(true); }
function requestElevation(){
  promoteMsg.value = "提权申请请联系企业管理员审批（终端" + (terminalName.value || "本机") + "，累计 " + (usageTokens.value != null ? fmt(usageTokens.value) + " tokens" : "用量待统计") + "），也可在企业后台提交。";
}
function openAdmin(){
  try{ window.electronAPI && window.electronAPI.openExternal && window.electronAPI.openExternal("http://127.0.0.1:8080"); }
  catch(e){ try{ window.open("http://127.0.0.1:8080", "_blank"); }catch(e2){} }
}
onMounted(() => { refresh(false); setInterval(() => refresh(false), 15000); });
defineExpose({ refresh });
</script>
<style scoped>
.ent-mini{position:fixed;right:18px;bottom:18px;width:330px;border:1px solid #e8e3df;border-radius:16px;background:#fcfaf8;box-shadow:0 18px 50px rgba(55,42,30,.14);z-index:80;overflow:hidden;font-family:"MiSans","PingFang SC",-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif;color:#26251e}
.ent-mini.in-window{position:static;width:100%;height:100%;display:flex;flex-direction:column;border:0;border-radius:0;box-shadow:none}
.ent-mini.in-window .ent-mini__head{-webkit-app-region:drag;user-select:none;cursor:move}
.ent-mini.in-window .ent-mini__btns,.ent-mini.in-window .ent-mini__btns button,.ent-mini__backbtn{-webkit-app-region:no-drag}
.ent-mini__head{display:flex;justify-content:space-between;align-items:center;gap:8px;min-height:64px;padding:10px 14px;border-bottom:1px solid #f0efed;background:rgba(252,250,248,.9)}
.ent-mini__user{display:flex;align-items:center;gap:11px;min-width:0}
.ent-mini__avatar{display:flex;align-items:center;justify-content:center;width:34px;height:34px;flex:0 0 34px;color:#f56b1f;background:#fff3eb;border:1px solid #ffd9c3;border-radius:12px}
.ent-mini__who{display:flex;flex-direction:column;gap:2px;min-width:0}
.ent-mini__who strong{display:block;font-size:14px;font-weight:700;color:#26251e;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ent-mini__who small{font-size:11px;color:#8d8984;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ent-mini__btns{display:flex;gap:6px}
.ent-mini__gear{display:flex;align-items:center;justify-content:center;width:30px;height:30px;border:1px solid #e7e5e4;border-radius:8px;color:#78716c;background:#fff;cursor:pointer}
.ent-mini__gear:hover{color:#f56b1f;border-color:#f1b18c}
.ent-mini__backbtn{display:flex;align-items:center;justify-content:center;width:30px;height:30px;flex:0 0 30px;border:1px solid #e7e5e4;border-radius:8px;color:#78716c;background:#fff;cursor:pointer}
.ent-mini__backbtn:hover{color:#f56b1f;border-color:#f1b18c}
.ent-mini__body{padding:6px 14px 12px;font-size:12px}
.ent-mini__body--scroll{flex:1;overflow-y:auto;min-height:0}
.ent-mini__quota{padding:10px 0 8px;border-bottom:1px dashed #eeeae7}
.ent-mini__quota-head{display:flex;justify-content:space-between;align-items:baseline;gap:8px;margin-bottom:8px}
.ent-mini__quota-head span{color:#8d8984}
.ent-mini__quota-head strong{color:#26251e;font-weight:700;font-size:12px}
.ent-mini__bar{height:8px;border-radius:99px;background:#f0efed;overflow:hidden}
.ent-mini__bar i{display:block;height:100%;width:0;border-radius:99px;background:linear-gradient(90deg,#f59e0b,#f56b1f);transition:width .4s ease}
.ent-mini__quota-sub{margin-top:6px;font-size:11px;color:#8d8984}
.ent-mini__sec{padding:8px 0;border-bottom:1px dashed #eeeae7}
.ent-mini__sec:last-of-type{border-bottom:0}
.ent-mini__sec-title{font-size:11px;font-weight:700;color:#a3a09c;letter-spacing:.06em;margin-bottom:4px}
.ent-mini__row{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:7px 0;border-bottom:1px dashed #eeeae7}
.ent-mini__row:last-child{border-bottom:0}
.ent-mini__row span{color:#8d8984}
.ent-mini__row strong{color:#26251e;font-weight:600}
.ent-mini__row strong.ok{color:#19855e}
.ent-mini__row strong.bad{color:#d95e55}
.ent-mini__srow{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:9px 0;border-bottom:1px dashed #eeeae7}
.ent-mini__srow:last-child{border-bottom:0}
.ent-mini__srow-text{display:flex;flex-direction:column;gap:2px;min-width:0}
.ent-mini__srow-text strong{font-size:12px;font-weight:600;color:#26251e}
.ent-mini__srow-text strong em{font-style:normal;font-size:10px;font-weight:700;color:#f56b1f;background:#fff3eb;border:1px solid #ffd9c3;border-radius:6px;padding:0 5px;margin-left:4px}
.ent-mini__srow-text small{font-size:11px;color:#8d8984}
.ent-mini__srow--dev .ent-mini__srow-text strong{color:#a3a09c}
.ent-mini__act{flex:0 0 auto;padding:6px 14px;border:1px solid #f1b18c;border-radius:8px;color:#b94a15;background:#fffaf7;font-size:12px;cursor:pointer}
.ent-mini__act:hover{background:#f56b1f;border-color:#f56b1f;color:#fff}
.ent-mini__promote{margin:8px 0 0;padding:8px 10px;font-size:11px;line-height:1.6;color:#b94a15;background:#fff7ed;border:1px solid #fed7aa;border-radius:8px}
.ent-mini__note{margin:8px 0 0;font-size:11px;line-height:1.6;color:#8d8984}
.is-dark{background:#141416;color:#f4f4f5;border-color:#3f3f46}
.is-dark .ent-mini__head{background:rgba(20,20,22,.95);border-color:#2a2a2e}
.is-dark .ent-mini__who strong{color:#f4f4f5}
.is-dark .ent-mini__who small{color:#a1a1aa}
.is-dark .ent-mini__gear,.is-dark .ent-mini__backbtn{background:#1c1c1f;border-color:#3f3f46;color:#d4d4d8}
.is-dark .ent-mini__row,.is-dark .ent-mini__quota,.is-dark .ent-mini__sec,.is-dark .ent-mini__srow{border-color:#2a2a2e}
.is-dark .ent-mini__row span,.is-dark .ent-mini__quota-head span,.is-dark .ent-mini__srow-text small{color:#a1a1aa}
.is-dark .ent-mini__row strong,.is-dark .ent-mini__quota-head strong,.is-dark .ent-mini__srow-text strong{color:#e4e4e7}
.is-dark .ent-mini__bar{background:#27272a}
.is-dark .ent-mini__quota-sub,.is-dark .ent-mini__note{color:#8e8e93}
.is-dark .ent-mini__act{background:#2a1f18;border-color:#7c2d12;color:#fdba74}
.is-dark .ent-mini__act:hover{background:#f56b1f;border-color:#f56b1f;color:#fff}
.is-dark .ent-mini__promote{background:#2a1f18;border-color:#7c2d12;color:#fdba74}
</style>
