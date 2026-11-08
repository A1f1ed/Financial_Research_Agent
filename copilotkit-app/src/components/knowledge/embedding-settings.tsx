"use client";

import { useEffect, useState } from "react";
import { Database, LoaderCircle, Save, TestTube2 } from "lucide-react";
import { researchRequest } from "@/components/workbench-panels";
import { useDocumentCopy } from "@/components/documents/shared";

type Config = { provider: "dashscope" | "deepseek" | "glm"; model: string; base_url: string; dimensions: number; timeout: number;
  credential_configured: boolean; verified: boolean; test: { status?: string; checked_at?: string; dimensions?: number; error_type?: string } };

export function EmbeddingSettingsPanel() {
  const c = useDocumentCopy(); const [config, setConfig] = useState<Config | null>(null); const [key, setKey] = useState("");
  const [busy, setBusy] = useState(""); const [error, setError] = useState(""); const [notice, setNotice] = useState(""); const [dirty, setDirty] = useState(false);
  useEffect(() => { const controller = new AbortController();
    void researchRequest<Config>("knowledge/embedding", "GET", undefined, controller.signal).then(setConfig).catch(err => { if (!controller.signal.aborted) setError(String(err)); });
    return () => controller.abort();
  }, []);
  async function act(action: "save" | "test") {
    if (!config) return; setBusy(action); setError(""); setNotice("");
    try {
      const value = await researchRequest<Config>(`knowledge/embedding${action === "test" ? "/test" : ""}`, action === "test" ? "POST" : "PUT",
        action === "test" ? {} : { provider: config.provider, model: config.model, base_url: config.base_url, dimensions: config.dimensions, timeout: config.timeout, ...(key.trim() ? { api_key: key.trim() } : {}) });
      setConfig(value); setKey(""); setDirty(false);
      setNotice(action === "save" ? "saved" : value.verified ? "success" : "failed");
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setBusy(""); }
  }
  function update(values: Partial<Config>) { setConfig(current => current && { ...current, ...values }); setDirty(true); setNotice(""); }
  return <section className="finance-card embedding-settings">
    <h2><Database size={19} /> {c("Embedding capability", "Embedding 检索能力")}</h2>
    <p className="muted">{c("Separate from the chat model. A successful greeting test does not enable semantic retrieval. The capability test sends only two short sample phrases.", "与对话模型独立。普通问候测试不能证明语义检索可用；此测试仅发送两段简短示例。")}</p>
    {error && <p role="alert" className="error-banner">{error}</p>}
    {!config ? <p role="status">{c("Loading capability settings…", "正在读取能力设置…")}</p> : <form onSubmit={event => { event.preventDefault(); void act("save"); }}>
      <fieldset disabled={!!busy}><div className="form-grid">
        <label>{c("Provider", "提供商")}<select value={config.provider} onChange={event => update({ provider: event.target.value as Config["provider"] })}><option value="dashscope">DashScope Qwen</option><option value="deepseek">DeepSeek</option><option value="glm">GLM / Zhipu</option></select></label>
        <label>{c("Embedding model", "Embedding 模型")}<input required maxLength={150} value={config.model} onChange={event => update({ model: event.target.value })} /></label>
        <label className="document-wide">{c("API base URL", "API 基础地址")}<input required type="url" value={config.base_url} onChange={event => update({ base_url: event.target.value })} /></label>
        <label>{c("Vector dimensions", "向量维度")}<input required type="number" min={64} max={4096} value={config.dimensions} onChange={event => update({ dimensions: Number(event.target.value) })} /></label>
        <label>{c("Timeout (seconds)", "超时（秒）")}<input required type="number" min={5} max={60} value={config.timeout} onChange={event => update({ timeout: Number(event.target.value) })} /></label>
        <label className="document-wide">{c("Dedicated key (optional)", "独立密钥（可选）")}<input type="password" autoComplete="new-password" value={key} onChange={event => { setKey(event.target.value); setDirty(true); }} placeholder={config.credential_configured ? c("Configured · leave blank to retain", "已配置，留空保留") : c("Reuse saved provider key, or enter a dedicated key", "复用已保存的提供商密钥，或填写独立密钥")} /></label>
      </div></fieldset>
      <p className="field-note">{c("Provider selection does not imply embedding support. Enter a supported model and matching base URL; save and test explicitly. Model or dimension changes require new indices.", "选择提供商不代表其支持 embedding。请填写支持的模型和对应地址，并保存、测试；模型或维度变化需要建立新索引。")}</p>
      <div className="workbench-actions"><span className="status-badge">{dirty ? c("Unsaved changes", "有未保存修改") : config.verified ? c("Verified", "已验证") : c("Not verified", "未验证")}</span>
        <button type="button" className="chat-config-toggle" disabled={!!busy || dirty} onClick={() => void act("test")}>{busy === "test" ? <LoaderCircle size={15} className="spin" /> : <TestTube2 size={15} />}{c("Test saved capability", "测试已保存能力")}</button>
        <button type="submit" className="primary-button" disabled={!!busy}><Save size={15} />{c("Save embedding settings", "保存检索能力设置")}</button></div>
      {notice && <p className={notice === "failed" ? "error-banner" : "field-note"} role={notice === "failed" ? "alert" : "status"}>{notice === "saved" ? c("Saved. Test this capability before hybrid indexing.", "已保存。混合索引前请测试此能力。") : notice === "success" ? c("Embedding test passed: two valid vectors with the configured dimension.", "Embedding 测试成功：已返回两个符合配置维度的有效向量。") : c(`Embedding test failed (${config.test.error_type || "Unknown"}). Check key, model, dimensions and endpoint.`, `Embedding 测试失败（${config.test.error_type || "Unknown"}）。请检查密钥、模型、维度与地址。`)}</p>}
    </form>}
  </section>;
}
