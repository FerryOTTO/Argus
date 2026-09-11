<template>
  <div class="module-config" :class="{ 'is-dark': darkMode }">
    <div class="module-config__header">
      <div><h2>{{ title }}</h2><p>{{ subtitle }}</p></div>
      <div class="module-config__actions">
        <span v-if="status" class="module-config__status">{{ status }}</span>
        <button type="button" :disabled="loading || saving" @click="load">重新读取</button>
        <button type="button" class="primary" :disabled="loading || saving" @click="save">{{ saving ? "保存中" : "保存到本地" }}</button>
      </div>
    </div>
    <div v-if="loading" class="module-config__tip">正在读取本地真实配置…</div>
    <div v-else-if="error" class="module-config__tip is-error">{{ error }}<button type="button" @click="load">重试</button></div>
    <template v-else>
      <section v-for="card in cards" :key="card.id" class="module-config__card">
        <header><strong>{{ card.title }}</strong><span>{{ card.desc }}</span></header>
        <div class="module-config__grid">
          <label v-for="f in card.fields" :key="f.key" class="cfg-field" :class="'cfg-'+f.type">
            <span class="cfg-label">{{ f.label }}<em v-if="f.desc">{{ f.desc }}</em></span>
            <input v-if="f.type==='text'" v-model="form[f.key]" type="text" :placeholder="f.placeholder||''" />
            <input v-else-if="f.type==='password'" v-model="form[f.key]" type="password" placeholder="留空=不覆盖本地密钥" />
            <input v-else-if="f.type==='number'" v-model.number="form[f.key]" type="number" :min="f.min" :max="f.max" :step="f.step||1" />
            <button v-else-if="f.type==='bool'" type="button" class="cfg-toggle" :class="{ on: form[f.key] }" @click="form[f.key]=!form[f.key]"><i></i>{{ form[f.key] ? "开" : "关" }}</button>
            <select v-else-if="f.type==='select'" v-model="form[f.key]"><option v-for="o in f.options" :key="o.value" :value="o.value">{{ o.label }}</option></select>
            <textarea v-else-if="f.type==='textarea'" v-model="form[f.key]" rows="5"></textarea>
            <textarea v-else-if="f.type==='rules'" v-model="form[f.key]" rows="10" spellcheck="false" class="cfg-rules"></textarea>
            <textarea v-else-if="f.type==='tags'" v-model="tagsText[f.key]" rows="3" placeholder="一行一条"></textarea>
          </label>
        </div>
      </section>
      <p class="module-config__foot">写入本地真实文件（modules.yaml / default_policy.json / whitelist.yaml / users.txt 等），先备份 .bak。Tool Guard 密钥留空不覆盖。</p>
    </template>
  </div>
</template>
<script setup>
import { computed, reactive, ref, watch } from "vue";
const props = defineProps({ module: { type: String, default: "content" }, darkMode: { type: Boolean, default: false } });
const loading = ref(true); const saving = ref(false); const error = ref(""); const status = ref("");
const form = reactive({}); const tagsText = reactive({});
const initialLevel = ref("");
const META = {
  content: { title: "内容检测配置", subtitle: "IO Guard 输入/上下文 + 检测策略 + Retrieval Guard（照搬企业后台分组，直连本地文件）" },
  access: { title: "访问控制配置", subtitle: "模块开关 + 策略风险联动 + users.txt / resources.txt（可视化编辑原文）" },
  tools: { title: "工具检测配置", subtitle: "Tool Guard 意图裁判 + OpenClaw 集成参数" },
  sandbox: { title: "沙箱安全配置", subtitle: "沙箱接入 + 人工复核兜底" },
  audit: { title: "审计日志配置", subtitle: "审计模块开关 + 正文存储策略" },
};
const title = computed(() => (META[props.module] || META.content).title);
const subtitle = computed(() => (META[props.module] || META.content).subtitle);
const ON_OFF = [{label:"allow 放行",value:"allow"},{label:"block 拦截",value:"block"},{label:"ignore 忽略",value:"ignore"}];
function F(key,label,type,extra){ return Object.assign({key,label,type}, extra||{}); }
const CARDS = {
  content: [
    { id:"io", title:"IO Guard 模块开关", desc:"对应 modules.yaml", fields:[F("modules.io_guard_input.enabled","启用输入检测","bool"),F("modules.io_guard_input.on_error","输入异常兜底","select",{options:ON_OFF}),F("modules.io_guard_input.media_extraction","附件媒体抽取","bool"),F("modules.io_guard_context.enabled","启用上下文复检","bool"),F("modules.io_guard_context.on_error","复检异常兜底","select",{options:ON_OFF})] },
    { id:"dt", title:"判定阈值与语义检测", desc:"对应 default_policy.json", fields:[F("io_guard_policy.decision_thresholds.rewrite","rewrite 阈值","number",{min:0,max:1,step:0.05}),F("io_guard_policy.decision_thresholds.block","block 阈值","number",{min:0,max:1,step:0.05}),F("io_guard_policy.semantic_detection.enabled","语义检测","bool"),F("io_guard_policy.semantic_detection.detector_threshold","通用命中阈值","number",{min:0,max:1,step:0.05}),F("io_guard_policy.question_decomposition.enabled","长问题分解","bool"),F("io_guard_policy.question_decomposition.min_chars","触发最小长度","number",{min:1}),F("io_guard_policy.question_decomposition.max_parts","最大拆分","number",{min:1,max:16}),F("io_guard_policy.question_decomposition.strategy","分解策略","text"),F("io_guard_policy.semantic_detection.backend","检测后端","text"),F("io_guard_policy.semantic_detection.model_dir","模型目录","text"),F("io_guard_policy.semantic_detection.policy_score","语义权重","number",{min:0,max:1,step:0.05}),F("io_guard_policy.semantic_detection.threshold_overrides.input","input阈值覆盖","number",{min:0,max:1,step:0.0025}),F("io_guard_policy.semantic_detection.threshold_overrides.output","output阈值覆盖","number",{min:0,max:1,step:0.0025}),F("io_guard_policy.semantic_detection.threshold_overrides.content","content阈值覆盖","number",{min:0,max:1,step:0.0025})] },
    { id:"me", title:"附件媒体抽取（含OCR）", desc:"对应 default_policy.json media_extraction（照搬终端管理）", fields:[F("io_guard_policy.media_extraction.enabled","抽取总开关","bool"),F("io_guard_policy.media_extraction.max_file_bytes","单附件上限(字节)","number",{min:1048576,step:1048576}),F("io_guard_policy.media_extraction.max_text_chars","抽取文本上限(字符)","number",{min:1000}),F("io_guard_policy.media_extraction.max_attachments","单请求附件上限","number",{min:1,max:20}),F("io_guard_policy.media_extraction.remote.max_bytes","远程附件上限(字节)","number",{min:1048576,step:1048576}),F("io_guard_policy.media_extraction.remote.timeout_ms","远程下载超时(ms)","number",{min:500}),F("io_guard_policy.media_extraction.ocr.enabled","启用OCR","bool"),F("io_guard_policy.media_extraction.ocr.lang","OCR语言","text"),F("io_guard_policy.media_extraction.ocr.device","OCR设备","select",{options:[{label:"CPU",value:"cpu"},{label:"CUDA",value:"cuda"}]}),F("io_guard_policy.media_extraction.ocr.max_images","单请求OCR图片上限","number",{min:1,max:16})] },
    { id:"ret", title:"Retrieval Guard", desc:"whitelist.yaml / b_injection / c_prompt", fields:[F("modules.retrieval_guard.enabled","总开关","bool"),F("modules.retrieval_guard.model_path","PIGuard模型目录","text"),F("modules.retrieval_guard.on_error","异常兜底","select",{options:ON_OFF}),F("retrieval.injection.threshold","注入拦截阈值","number",{min:0,max:1,step:0.01}),F("retrieval.injection.window_size","滑窗大小","number",{min:1}),F("retrieval.injection.step","滑窗步长","number",{min:1}),F("retrieval.whitelist.trusted","白名单 trusted","tags"),F("retrieval.whitelist.blocked","黑名单 blocked","tags"),F("retrieval.prompt_wrap.random_length","随机序列长度","number",{min:1}),F("retrieval.prompt_wrap.self_reminder","行为契约文案","textarea"),F("retrieval.prompt_wrap.post_prompting","后置指令文案","textarea")] },
  ],
  access: [
    { id:"mod", title:"模块开关", desc:"modules.yaml", fields:[F("modules.access_control.enabled","启用访问控制","bool"),F("modules.access_control.on_error","异常兜底","select",{options:ON_OFF})] },
    { id:"pol", title:"策略与风险联动", desc:"access_local.json（对应 ARGUS_*）", fields:[F("access.default_user_level","默认用户等级","select",{options:[{label:"公开 public",value:"public"},{label:"内部 internal",value:"internal"},{label:"秘密 secret",value:"secret"},{label:"绝密 top_secret",value:"top_secret"}]}),F("access.mode","策略模型","select",{options:[{label:"RBAC",value:"rbac"},{label:"MAC",value:"mac"},{label:"Hybrid",value:"hybrid"}]}),F("access.block_unknown_users","拦截未知用户","bool"),F("access.risk_link_enabled","风险联动","bool"),F("access.risk_window_seconds","风险滑窗(秒)","number",{min:30}),F("access.risk_threshold","高风险阈值","number",{min:0,max:1,step:0.05}),F("access.risk_probe_block_count","试探拦截数","number",{min:1}),F("access.risk_escalation_threshold","升级阈值","number",{min:0,max:1,step:0.05}),F("access.quarantine_enabled","启用隔离","bool"),F("access.quarantine_block_count","隔离触发数","number",{min:1}),F("access.quarantine_risk_threshold","隔离风险阈值","number",{min:0,max:1,step:0.05}),F("access.quarantine_long_window_seconds","长窗时长(秒)","number",{min:60}),F("access.quarantine_long_window_count","长窗触发数","number",{min:1})] },
    { id:"rules", title:"规则文件原文", desc:"resources.txt 整体替换（用户规则只保留在服务端）", fields:[F("access_rules.resources","resources.txt","rules")] },
  ],
  tools: [
    { id:"tg", title:"Tool Guard 裁判", desc:"modules.yaml + 运行期热更新", fields:[F("modules.tool_guard.enabled","启用","bool"),F("modules.tool_guard.on_error","LLM 异常兜底","select",{options:[{label:"block 拦截",value:"block"},{label:"allow 放行",value:"allow"}]}),F("modules.tool_guard.base_url","LLM Base URL","text"),F("modules.tool_guard.api_key","LLM API Key","password"),F("modules.tool_guard.model","模型名","text"),F("modules.tool_guard.timeout_seconds","超时(秒)","number",{min:1}),F("modules.tool_guard.block_threshold","block 阈值","number",{min:0,max:1,step:0.05}),F("modules.tool_guard.review_threshold","review 阈值","number",{min:0,max:1,step:0.05})] },
    { id:"fetch", title:"fetch_guard 抓取前置判定", desc:"modules.tool_guard.fetch_guard（照搬终端管理）", fields:[F("modules.tool_guard.fetch_guard.enabled","启用fetch_guard","bool"),F("modules.tool_guard.fetch_guard.shell_tools","shell工具名单","tags"),F("modules.tool_guard.fetch_guard.url_tools","URL导航工具","tags")] },
    { id:"it", title:"OpenClaw 集成", desc:"integration_local.json", fields:[F("integration.argus_url","Argus 地址","text"),F("integration.timeout_ms","超时(ms)","number",{min:1000}),F("integration.fail_mode","失败模式","select",{options:[{label:"closed",value:"closed"},{label:"open",value:"open"}]}),F("integration.enable_media_check","附件送检","bool"),F("integration.api_token_env","API令牌环境变量名","text"),F("integration.media_root","附件根目录","text"),F("integration.protected_tools","保护工具","tags")] },
  ],
  sandbox: [
    { id:"sb", title:"沙箱接入", desc:"modules.yaml sandbox 段", fields:[F("modules.sandbox.enabled","启用沙箱","bool"),F("modules.sandbox.mode","接入方式","select",{options:[{label:"mcp",value:"mcp"}]}),F("modules.sandbox.url","Sandbox MCP 地址","text")] },
    { id:"hr", title:"人工复核", desc:"human_review 段", fields:[F("modules.human_review.unsupported_action","不支持动作兜底","select",{options:[{label:"block 拦截",value:"block"},{label:"allow 放行",value:"allow"}]})] },
  ],
  audit: [
    { id:"au", title:"审计模块", desc:"modules.yaml + policy audit 段", fields:[F("modules.audit.enabled","启用审计","bool"),F("modules.audit.on_error","异常兜底","select",{options:ON_OFF}),F("io_guard_policy.audit.content_storage","正文存储","select",{options:[{label:"sanitized 脱敏",value:"sanitized"},{label:"full 全量",value:"full"},{label:"none 不存",value:"none"}]}),F("io_guard_policy.audit.max_content_chars","截断上限","number",{min:100})] },
  ],
};
const cards = computed(() => CARDS[props.module] || CARDS.content);
function getPath(obj, path){ return path.split(".").reduce((a,k)=> (a && typeof a==="object" ? a[k] : undefined), obj); }
function setPath(obj, path, val){ const ks=path.split("."); let c=obj; for(let i=0;i<ks.length-1;i++){ if(typeof c[ks[i]]!=="object"||!c[ks[i]]) c[ks[i]]={}; c=c[ks[i]]; } c[ks[ks.length-1]]=val; }
async function load(){
  loading.value=true; error.value=""; status.value="";
  try{
    const r = await fetch("http://127.0.0.1:8000/v1/local/config"); if(!r.ok) throw new Error("HTTP "+r.status);
    const snap = (await r.json()).data;
    for(const k of Object.keys(form)) delete form[k]; for(const k of Object.keys(tagsText)) delete tagsText[k];
    for(const card of cards.value) for(const f of card.fields){
      let v = getPath(snap, f.key);
      if(f.type==="tags"){ tagsText[f.key] = Array.isArray(v) ? v.join("\n") : ""; form[f.key]=v||[]; }
      else form[f.key] = v;
      if(f.key==="access.default_user_level") initialLevel.value = v || "secret";
    }
  }catch(e){ error.value = "读取失败：" + (e.message||e) + "，确认 8000 服务已启动"; }
  finally{ loading.value=false; }
}
function buildPayload(){
  const p={};
  for(const card of cards.value) for(const f of card.fields){
    let v = f.type==="tags" ? String(tagsText[f.key]||"").split("\n").map(s=>s.trim()).filter(Boolean) : form[f.key];
    if(f.key==="modules.tool_guard.api_key" && !v) continue;
    setPath(p, f.key, v);
  }
  return p;
}
async function save(){
  saving.value=true; status.value="";
  { const order={public:1,internal:2,secret:3,top_secret:4}; const nl=form["access.default_user_level"]; if(nl && (order[nl]||0) > (order[initialLevel.value]||0)){ if(!confirm("调高默认等级会放宽拦截,确定吗?")){ saving.value=false; return; } } }
  try{
    const r = await fetch("http://127.0.0.1:8000/v1/local/config",{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify(buildPayload())});
    if(!r.ok) throw new Error("HTTP "+r.status);
    const d = await r.json(); if(form["access.default_user_level"]) initialLevel.value = form["access.default_user_level"]; status.value = "已保存：" + (d.data.applied||[]).join("、");
  }catch(e){ error.value = "保存失败：" + (e.message||e); }
  finally{ saving.value=false; }
}
watch(() => props.module, load, { immediate: true });
</script>
<style scoped>
.module-config{padding:22px;max-width:1080px;margin:0 auto}
.module-config__header{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;margin-bottom:16px}
.module-config__header h2{font-size:18px;font-weight:800}
.module-config__header p{font-size:12px;color:#71717a;margin-top:4px}
.module-config__actions{display:flex;gap:8px;align-items:center}
.module-config__actions button{border:1px solid #e4e4e7;border-radius:10px;padding:7px 12px;font-size:12px;background:#fff}
.module-config__actions button.primary{background:#18181b;color:#fff;border-color:#18181b}
.module-config__status{font-size:12px;color:#15803d}
.module-config__tip{border:1px dashed #d4d4d8;border-radius:12px;padding:18px;font-size:13px;color:#52525b;background:#fafafa}
.module-config__tip.is-error{color:#b91c1c;border-color:#fecaca;background:#fef2f2}
.module-config__card{border:1px solid #e4e4e7;border-radius:16px;background:#fff;padding:16px;margin-bottom:14px}
.module-config__card header{margin-bottom:12px}
.module-config__card header strong{font-size:14px}
.module-config__card header span{display:block;font-size:11px;color:#8e8e93;margin-top:2px}
.module-config__grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px}
.cfg-field{display:flex;flex-direction:column;gap:6px;border:1px solid #f1f1f3;border-radius:12px;padding:10px;background:#fcfcfc}
.cfg-field.cfg-textarea,.cfg-field.cfg-rules,.cfg-field.cfg-tags{grid-column:1/-1}
.cfg-label{font-size:12px;font-weight:600}
.cfg-label em{display:block;font-style:normal;font-weight:400;font-size:11px;color:#8e8e93;margin-top:2px}
.cfg-field input,.cfg-field select,.cfg-field textarea{border:1px solid #e4e4e7;border-radius:8px;padding:7px 9px;font-size:12px;width:100%;background:#fff}
.cfg-rules{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:11px}
.cfg-toggle{display:inline-flex;align-items:center;gap:8px;border:1px solid #e4e4e7;border-radius:999px;padding:5px 12px;font-size:12px;background:#fff;width:fit-content}
.cfg-toggle i{width:28px;height:16px;border-radius:999px;background:#d4d4d8;position:relative;display:inline-block}
.cfg-toggle i::after{content:"";position:absolute;top:2px;left:2px;width:12px;height:12px;border-radius:50%;background:#fff}
.cfg-toggle.on i{background:#16a34a}
.cfg-toggle.on i::after{left:14px}
.module-config__foot{font-size:11px;color:#8e8e93;margin:8px 2px 30px}
.is-dark .module-config__card,.is-dark .module-config__actions button,.is-dark .cfg-field input,.is-dark .cfg-field select,.is-dark .cfg-field textarea{background:#18181b;color:#f4f4f5;border-color:#3f3f46}
.is-dark .cfg-field{background:#101013}
.is-dark .module-config__card{background:#141416}
.is-dark .module-config__tip{background:#141416;color:#d4d4d8}
</style>
