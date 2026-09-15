# -*- coding: utf-8 -*-
"""重新生成对照表/对照文档并更新 README（含真实案例样本）。"""
import json, glob, csv, os

BASE = os.path.dirname(os.path.abspath(__file__))

# ---- 1. 预期输出对照表.csv ----
rows = []
for f in sorted(glob.glob("*/*.jsonl")):
    with open(f, encoding="utf-8") as fh:
        data = [json.loads(l) for l in fh if l.strip()]
    for r in data:
        rid = r.get("id") or r.get("event_id","")
        cat = r.get("category","")
        p = r.get("payload", {})
        summary = ""; expect = ""
        fn = os.path.basename(f)
        if fn.startswith("openguard"):
            req = json.dumps(r.get("request",{}), ensure_ascii=False)
            if len(req)>55: req = req[:52]+"..."
            summary = f"{r.get('method','')} {r.get('endpoint','')} {req}"
            expect = f"HTTP {r.get('expected_status','')} — {r.get('expected','')}"
        elif fn.startswith("io_guard"):
            summary = p.get("text") or p.get("content") or ""
            expect = r.get("expected_action","")
            if r.get("expected_label"): expect += f" / {r.get('expected_label','')}"
        elif fn.startswith("retrieval"):
            summary = p.get("url") or p.get("text") or p.get("content") or ""
            expect = r.get("expected_action","")
        elif fn.startswith("tool_guard"):
            summary = (p.get("tool_name") or "") + " " + json.dumps(p.get("arguments",{}), ensure_ascii=False)
            expect = r.get("expected_action","")
        elif fn.startswith("access_control"):
            c = r.get("context", {})
            summary = f"{c.get('user_id','')} 调 {p.get('tool_name','')} {json.dumps(p.get('arguments',{}),ensure_ascii=False)}"
            expect = r.get("expected_action","")
        elif fn.startswith("sandbox"):
            summary = p.get("command","")
            expect = f"{r.get('expected_severity','')} / blocked={r.get('expected_blocked','')} ({r.get('expected_pattern','')})"
        elif fn.startswith("media"):
            summary = p.get("text","") + " 附件:" + ",".join(a.get("name","") for a in p.get("attachments",[]))
            expect = r.get("expected_action","")
        elif fn.startswith("audit"):
            summary = f"{r.get('source_module','')}.{r.get('action','')} {r.get('reason','')}"
            expect = "合成事件(校验审计写入/查询/图构建)"
        summary = summary.replace("\n"," ").strip()
        if len(summary)>60: summary = summary[:57]+"..."
        rows.append([rid, f, cat, summary, expect, r.get("note","")])

with open(os.path.join(BASE,"预期输出对照表.csv"),"w",newline="",encoding="utf-8-sig") as fh:
    w = csv.writer(fh)
    w.writerow(["id","文件","category","输入摘要","预期输出","说明"])
    w.writerows(rows)
print("对照表已更新:", len(rows), "条")

# ---- 2. 输入输出对照.md ----
mod = {
 "openguard_auth.jsonl":"多用户登录","io_guard_input.jsonl":"输入安全","io_guard_output.jsonl":"输出安全",
 "io_guard_content.jsonl":"上下文安全","retrieval_guard.jsonl":"检索安全","tool_guard_intent.jsonl":"工具安全",
 "access_control_matrix.jsonl":"访问控制","sandbox_harm_detector.jsonl":"沙箱执行","media_input.jsonl":"附件防护",
 "audit_events.synthetic.jsonl":"日志审计",
}
lines = ["# 测试集 输入 → 预期输出 对照表","","共 438 条，含 33 条基于真实政府文件的案例（id 含 -r 前缀）。",""]
for f in sorted(glob.glob("*/*.jsonl")):
    fn = os.path.basename(f)
    with open(f, encoding="utf-8") as fh:
        data = [json.loads(l) for l in fh if l.strip()]
    lines += ["", f"## {mod.get(fn, fn)}（{len(data)} 条）", ""]
    for r in data:
        rid = r.get("id") or r.get("event_id","")
        cat = r.get("category","")
        p = r.get("payload", {})
        inp = ""; exp = ""
        if fn.startswith("openguard"):
            inp = f"{r.get('method','')} {r.get('endpoint','')} {json.dumps(r.get('request',{}),ensure_ascii=False)}"
            exp = f"HTTP {r.get('expected_status','')} — {r.get('expected','')}"
        elif fn.startswith("io_guard"):
            inp = p.get("text") or p.get("content") or ""
            exp = r.get("expected_action","")
            if r.get("expected_label"): exp += f"（{r.get('expected_label','')}）"
        elif fn.startswith("retrieval"):
            inp = f"URL={p.get('url','')}\n     内容={p.get('content','')}"
            exp = r.get("expected_action","")
        elif fn.startswith("tool_guard"):
            chain = " → ".join(f"{t.get('tool_name','')}({json.dumps(t.get('arguments',{}),ensure_ascii=False)})" for t in p.get("tool_chain",[]))
            cur = f"{p.get('tool_name','')}({json.dumps(p.get('arguments',{}),ensure_ascii=False)})"
            inp = f"意图={p.get('original_prompt','')}"
            if chain: inp += f"\n     链={chain}"
            inp += f"\n     当前调用={cur}"
            exp = r.get("expected_action","")
        elif fn.startswith("access_control"):
            c = r.get("context", {})
            db = p.get("database","")
            inp = f"{c.get('user_id','')} 调 {p.get('tool_name','')}({json.dumps(p.get('arguments',{}),ensure_ascii=False)})" + (f" 库={db}" if db else "")
            exp = r.get("expected_action","")
        elif fn.startswith("sandbox"):
            inp = p.get("command","")
            exp = f"{r.get('expected_severity','')} 是否拦截={r.get('expected_blocked','')} 规则={r.get('expected_pattern','') or '—'}"
        elif fn.startswith("media"):
            atts = "; ".join(f"{a.get('name','')}: {a.get('content','')}" for a in p.get("attachments",[]))
            inp = f"{p.get('text','')}\n     附件→ {atts}"
            exp = r.get("expected_action","")
        elif fn.startswith("audit"):
            inp = f"{r.get('source_module','')}.{r.get('action','')}  {r.get('reason','')}"
            exp = "合成事件（校验审计写入/查询/图构建）"
        lines.append(f"### {rid}  [{cat}]")
        lines.append(f"- 输入：{inp}")
        lines.append(f"- 预期输出：{exp}")
        lines.append("")

with open(os.path.join(BASE,"输入输出对照.md"),"w",encoding="utf-8") as fh:
    fh.write("\n".join(lines))
print("输入输出对照.md 已更新")

# ---- 3. 更新 README ----
with open(os.path.join(BASE,"README.md"), encoding="utf-8") as fh:
    t = fh.read()
t = t.replace("共 **405 条样本**", "共 **438 条样本**")
t = t.replace("| | | **合计** | **405** |", "| | | **合计** | **438** |")
t = t.replace("**10 道安检 + 405 条带标准答案的考题**", "**10 道安检 + 438 条带标准答案的考题**")
if "00_真实案例_政府文件" not in t:
    t = t.replace("test/\n", "test/\n├── 00_真实案例_政府文件/  3 份真实政府文件（样本底料）\n")
if "## 六、真实案例" not in t:
    real_sec = (
        "\n## 六、真实案例：基于政府官网官方文件构造的样本\n\n"
        "其中 33 条样本是**基于中国政府网（gov.cn）公开的真实政府文件**构造的（id 含 `-r`），"
        "比人工编造更贴近真实政务场景。底料存于 `00_真实案例_政府文件/`：\n\n"
        "| 文件 | 文号 | 用途 |\n|---|---|---|\n"
        "| 国务院关于深入实施“人工智能+”行动的意见 | 国发〔2025〕11号 | 政策解读、公文处理类样本 |\n"
        "| 国务院关于加快推进“互联网+政务服务”工作的指导意见 | 国发〔2016〕55号 | 政务服务类样本 |\n"
        "| 国务院办公厅关于建立政务服务“好差评”制度的意见 | 国办发〔2019〕51号 | 评价制度、数据保护类样本 |\n\n"
        "真实案例样本既测「正常任务」（总结/解读/改写真实公文），也测「攻击变体」"
        "（在真实公文后藏注入指令、伪造/篡改公文、越权调取内部讨论稿、把真实政策当幌子做工具劫持等）。\n\n"
    )
    t = t.replace("## 六、这些测试集怎么用", real_sec + "## 七、这些测试集怎么用")
    t = t.replace("## 七、一句话总结", "## 八、一句话总结")

with open(os.path.join(BASE,"README.md"),"w",encoding="utf-8") as fh:
    fh.write(t)
print("README 已更新")

total = sum(1 for f in glob.glob("*/*.jsonl") for l in open(f,encoding="utf-8") if l.strip())
print("总样本数:", total)
