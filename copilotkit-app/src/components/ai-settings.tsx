"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, LoaderCircle, Save, Settings2, TestTube2, XCircle } from "lucide-react";
import { useT } from "@/hooks/use-language";
import { researchRequest } from "@/components/workbench-panels";

type Provider = "dashscope" | "deepseek" | "glm";
type Profile = { provider: Provider; label: string; model: string; base_url: string; temperature: number; timeout: number;
  credential_configured: boolean; suggested_models: string[]; api_key?: string };
type Snapshot = { ai: Profile; profiles: Record<Provider, Profile> };
type TestResult = { ok: boolean; code?: string; reply?: string; elapsed_ms?: number };
const failures: Record<string, string> = {
  missing_key: "请填写 API key，或先在服务端 .env 中配置对应密钥。",
  authentication: "认证失败，请检查当前提供商的 API key。",
  permission: "访问被拒绝，请检查账户权限和模型访问权限。",
  model_not_found: "未找到模型或接口，请检查模型名称与 Base URL。",
  rate_limit: "请求被限流或额度不足，请检查账户额度后重试。",
  timeout: "测试超时（最多等待 20 秒），请稍后重试。",
  connection: "无法连接模型服务，请检查 Base URL 和网络。",
  invalid_request: "服务商拒绝了请求，请检查模型名称、地址和生成参数。",
  provider_error: "模型服务暂不可用，请稍后重试。",
  empty_reply: "模型返回了空回复，请检查模型设置后重试。",
  unexpected: "连接测试失败，请检查设置后重试。",
};

export function AISettingsPanel() {
  const t = useT();
  const [profiles, setProfiles] = useState<Snapshot["profiles"] | null>(null);
  const [provider, setProvider] = useState<Provider>("dashscope");
  const [active, setActive] = useState<Provider>("dashscope");
  const [busy, setBusy] = useState<"save" | "test" | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [result, setResult] = useState<TestResult | null>(null);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    researchRequest<Snapshot>("settings", "GET", undefined, controller.signal).then(snapshot => {
      setProfiles(snapshot.profiles); setProvider(snapshot.ai.provider); setActive(snapshot.ai.provider); setError("");
    }).catch(() => { if (!controller.signal.aborted) setError("无法读取 AI 设置，请重试。"); });
    return () => controller.abort();
  }, [retry]);
  const profile = profiles?.[provider];
  function update(change: Partial<Profile>) {
    if (!profiles || !profile) return;
    setProfiles({ ...profiles, [provider]: { ...profile, ...change } });
    setNotice(""); setError(""); setResult(null);
  }
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!profile || busy) return;
    const operation = (event.nativeEvent as SubmitEvent).submitter?.getAttribute("value") === "test" ? "test" : "save";
    setBusy(operation); setError(""); setNotice(""); setResult(null);
    try {
      if (operation === "test") {
        setResult(await researchRequest<TestResult>("settings/ai/test", "POST", profile));
      } else {
        const saved = await researchRequest<Profile>("settings/ai", "PUT", profile);
        setProfiles(current => current && { ...current, [provider]: saved });
        setActive(provider); setNotice("设置已保存，后续调用将使用此提供商。");
      }
    } catch (err) { setError(err instanceof Error ? err.message : "请求失败，请稍后重试。"); }
    finally { setBusy(null); }
  }
  return <div className="workbench-page">
    <span className="section-eyebrow">PREFERENCES</span><h1>{t("AI 设置")}</h1>
    {!profiles && !error && <p role="status">{t("正在读取设置…")}</p>}
    {!profiles && error && <div role="alert" className="error-banner">{t(error)} <button className="chat-config-toggle" onClick={() => setRetry(value => value + 1)}>{t("重试")}</button></div>}
    {profile && <form className="finance-card workbench-form ai-settings-form" onSubmit={submit}>
      <div className="section-title"><Settings2 size={18} /><h2>{t("模型连接")}</h2><span>{t(provider === active ? "当前使用中" : "保存后启用")}</span></div>
      <fieldset disabled={!!busy}>
        <label>{t("提供商")}<select value={provider} onChange={event => {
          setProvider(event.target.value as Provider); setNotice(""); setError(""); setResult(null);
        }}>
          <option value="dashscope">DashScope Qwen</option><option value="deepseek">DeepSeek</option><option value="glm">GLM / Zhipu AI</option>
        </select></label>
        <div className="form-grid">
          <label>{t("模型名称")}<input required list="provider-models" maxLength={150} value={profile.model} onChange={event => update({ model: event.target.value })} />
            <datalist id="provider-models">{profile.suggested_models.map(model => <option key={model} value={model} />)}</datalist></label>
          <label>Base URL<input required type="url" value={profile.base_url} onChange={event => update({ base_url: event.target.value })} /></label>
        </div>
        <label>API key<input type="password" autoComplete="new-password" maxLength={500} spellCheck={false} value={profile.api_key ?? ""}
          placeholder={t(profile.credential_configured ? "已配置，留空保留现有密钥" : "输入当前提供商的 API key")}
          onChange={event => update({ api_key: event.target.value })} /></label>
        <p className="field-note">{t(profile.credential_configured ? "此提供商的服务端密钥已配置。" : "此提供商尚未配置密钥。")}{" "}{t("密钥保存在本机服务端 .env，不会回传到页面。留空时保留已有密钥。")}</p>
        <div className="form-grid">
          <label>{t("温度")}<input required type="number" min={0} max={2} step={0.1} value={profile.temperature} onChange={event => update({ temperature: Number(event.target.value) })} /></label>
          <label>{t("超时（秒）")}<input required type="number" min={10} max={600} value={profile.timeout} onChange={event => update({ timeout: Number(event.target.value) })} /></label>
        </div>
      </fieldset>
      <p className="field-note">{t("测试仅用当前表单发送一句“你好”，不保存、不切换使用中的模型。保存后，后续对话与研究调用将使用此配置。")}</p>
      {error && <p className="error-banner" role="alert">{t(error)}</p>}
      {result && <div className={`ai-test-result ${result.ok ? "success" : "failure"}`} role={result.ok ? "status" : "alert"}>
        {result.ok ? <CheckCircle2 size={18} /> : <XCircle size={18} />}<div><strong>{t(result.ok ? "连接测试成功" : "连接测试失败")}</strong>
          <p>{result.ok ? result.reply : t(failures[result.code ?? "unexpected"] ?? failures.unexpected)}</p>
          {result.elapsed_ms !== undefined && <small>{t("响应耗时")}: {(result.elapsed_ms / 1000).toFixed(2)}s</small>}
        </div>
      </div>}
      <div className="workbench-actions ai-settings-actions">
        <span role="status">{t(notice)}</span>
        <button type="submit" value="test" className="chat-config-toggle" disabled={!!busy}>{busy === "test" ? <LoaderCircle size={16} className="spin" /> : <TestTube2 size={16} />}{t(busy === "test" ? "测试中…" : "测试连接")}</button>
        <button type="submit" value="save" className="primary-button" disabled={!!busy}>{busy === "save" ? <LoaderCircle size={16} className="spin" /> : <Save size={16} />}{t(busy === "save" ? "保存中…" : "保存并启用")}</button>
      </div>
    </form>}
  </div>;
}
