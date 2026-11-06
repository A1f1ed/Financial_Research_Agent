"use client";

import { useLanguage, useT } from "@/hooks/use-language";

import { useState } from "react";
import { ArrowUpRight, Check } from "lucide-react";
import { ENGLISH_EXAMPLES, ENGLISH_EXAMPLE_LABELS } from "@/lib/finance-examples-en";
import { FINANCE_EXAMPLE_GROUPS } from "@/lib/finance-examples";

export function FinanceExamples({ onSelect }: { onSelect?: (prompt: string) => void }) {
  const t = useT();
  const { language } = useLanguage();
  const groups = language === "en" ? FINANCE_EXAMPLE_GROUPS.map(group => ({ ...group, label: ENGLISH_EXAMPLE_LABELS[group.id], examples: group.examples.map(example => ({ ...example, ...ENGLISH_EXAMPLES[example.id] })) })) : FINANCE_EXAMPLE_GROUPS;
  const [groupId, setGroupId] = useState<string>(FINANCE_EXAMPLE_GROUPS[0].id);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const group = groups.find(item => item.id === groupId)!;

  return <section className="finance-examples" aria-label={t("金融工作场景示例")}>
    <div className="finance-example-categories" role="group" aria-label={t("选择工作场景")}>
      {groups.map(item => <button type="button" key={item.id} aria-pressed={groupId === item.id}
        onClick={() => setGroupId(item.id)}>{t(item.label)}</button>)}
    </div>
    <div className="finance-example-cards" role="group" aria-label={language === "en" ? `${group.label} examples` : `${group.label}示例问题`}>
      {group.examples.map(example => <button type="button" key={example.id} className={selectedId === example.id ? "is-selected" : ""}
        disabled={!onSelect} onClick={() => { onSelect?.(example.prompt); setSelectedId(example.id); }}>
        <strong>{t(example.title)}<ArrowUpRight size={14} aria-hidden="true" /></strong>
        <span>{t(example.description)}</span>
        <small>{t(selectedId === example.id ? <><Check size={12} aria-hidden="true" />{t("已填入草稿")}</> : example.requirement)}</small>
      </button>)}
    </div>
    <p className="finance-example-note">{t("6 类 · 18 个工作场景。点击只填入草稿；可替换【标的、日期或材料】，由你确认发送。")}</p>
  </section>;
}
