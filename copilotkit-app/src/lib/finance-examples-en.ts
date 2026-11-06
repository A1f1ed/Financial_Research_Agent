// Drafts are explicit examples, not live facts or instructions to run automatically.
export const ENGLISH_EXAMPLE_LABELS: Record<string, string> = {
  company: "Company research", statements: "Financial checks", valuation: "Peers & valuation",
  events: "Event tracking", risk: "Risk & review", deliverables: "Research deliverables",
};
export const ENGLISH_EXAMPLES: Record<string, { title: string; description: string; requirement: string; prompt: string }> = {
  "earnings-quality": {
    title: "BYD: can profit growth last?", description: "Separate growth, cash generation and one-off gains, then identify evidence gaps.", requirement: "Confirm the cutoff date first",
    prompt: "Help me assess the earnings quality of BYD (1211.HK). First confirm my information cutoff date and the financial statements and announcements available by then. Examine revenue and gross margins, operating cash flow versus net profit, receivables, inventory and one-off gains. Use a table of verified facts, calculation definitions, possible explanations and missing evidence. Align consolidated and quarterly periods. Do not substitute news summaries for statements, fill gaps with invented data, or jump to a buy/sell conclusion.",
  },
  "business-drivers": {
    title: "Has the business transition delivered revenue?", description: "Test management's growth narrative against revenue, profit and delivery evidence.", requirement: "Specify company and date",
    prompt: "For [symbol], as of [cutoff date], help me verify whether [new business / growth initiative] is delivering results. Distinguish recognized revenue, orders, nonbinding partnerships and management targets. Look for segment revenue, margins, capital expenditure and operating data. First give me a diligence checklist and required original materials. Once available, map each narrative to measurable indicators, evidence and counterevidence. Keep missing items explicitly unresolved.",
  },
  liquidity: {
    title: "Cash on hand, but refinancing risk?", description: "Check restricted cash, debt maturities and cash-flow mismatches.", requirement: "Provide statements or debt disclosures",
    prompt: "Assess short-term liquidity risks for [company / symbol] as of [date]. I will provide statements or disclosures. Separate available cash from restricted funds, and map debt due within one year, operating cash flow, committed capital expenditure and refinancing needs. Record definitions, page references and gaps. Do not infer safety from cash balances or leverage alone, or invent debt-coverage ratios.",
  },
  "profit-cash": {
    title: "Why is cash flow lagging profit?", description: "Reconcile working capital, noncash items and cash collection.", requirement: "Provide two reporting periods",
    prompt: "I will provide two periods of [company]'s income statements, cash-flow statements and working-capital notes. Investigate rising profit alongside weaker operating cash flow: receivables, inventory, prepayments, payables and noncash items. Present source data, change calculations, supported explanations and unresolved issues. Align cumulative and quarterly periods before comparing. Do not treat missing items as zero.",
  },
  periods: {
    title: "Do quarterly, YTD, YoY and QoQ figures align?", description: "Audit reporting periods, currencies and units before interpreting growth.", requirement: "Paste a table or data",
    prompt: "Audit the [company] earnings table I will paste. Check quarterly versus year-to-date figures, YoY versus QoQ changes, RMB versus HKD, and thousands versus millions. Derive quarters by subtracting cumulative figures only when reporting scope, accounting definitions and periods align; show formulas. List errors, correctable calculations and original disclosures still needed. Wait for my data first.",
  },
  adjustments: {
    title: "What is excluded from adjusted earnings?", description: "Reconcile adjustments and test whether they really are nonrecurring.", requirement: "Provide release and reconciliation",
    prompt: "Compare statutory profit, profit excluding nonrecurring items and management-adjusted profit for [company] as of [date]. Wait for my earnings release or reconciliation. List each adjustment, amount, tax treatment, cash impact, recurrence across years and source. Do not assume adjusted figures better represent sustainable earnings. End with three specific questions for the earnings call.",
  },
  peers: {
    title: "How can we compare BYD and Geely fairly?", description: "Align periods, currencies and business mix before comparing margins or multiples.", requirement: "Confirm date and peer scope",
    prompt: "Compare BYD (1211.HK) and Geely Auto (175.HK). First confirm the information cutoff and whether these companies match the business scope I want. Build a framework covering segments, sales and revenue recognition, gross margins, R&D accounting, capital expenditure, free cash flow and valuation. Align periods, currencies, consolidation and one-offs. Flag noncomparable metrics. Use verifiable evidence, leave missing values blank and avoid ranking on share price or PE alone.",
  },
  "cyclical-pe": {
    title: "Low PE: cheap, or peak-cycle earnings?", description: "Separate the earnings base, cycle position and valuation assumptions.", requirement: "Specify company and earnings data",
    prompt: "For [company / symbol] as of [date], assess the evidence needed to support a low-PE thesis. Distinguish historical, TTM and forward PE; check one-off gains, peak-cycle earnings, net debt and capital expenditure needs. Start with a framework and data requirements. Compare only verified data. Outline bull, base and bear assumptions, and do not calculate a target price without sufficient inputs.",
  },
  "valuation-review": {
    title: "Which assumptions drive this valuation?", description: "Audit inputs, formulas, sensitivities and double counting.", requirement: "Paste model assumptions and formulas",
    prompt: "I will provide inputs and formulas for a [company] valuation model. Audit forecast horizon, revenue growth, margins, capital expenditure, working capital, discount rate, terminal value and net debt. Flag inconsistent units, double counting and unsupported assumptions. Rank assumptions by their impact and propose reproducible sensitivity checks. Do not fabricate financial inputs or present model output as certain value.",
  },
  "earnings-event": {
    title: "What changed after the earnings release?", description: "Separate new facts, expectation differences and the original thesis.", requirement: "Provide release and prior thesis",
    prompt: "I will provide [company]'s latest earnings release and my prior thesis. Separate newly disclosed facts, differences versus prior expectations, management explanations and your judgments. Mark each growth driver and risk as supported, weakened or unresolved. Use a change–evidence–impact–next-check table. Do not claim an earnings beat or miss without reliable consensus data.",
  },
  "unlock-event": {
    title: "A share unlock is not a completed sale", description: "Distinguish tradable shares, sale plans, progress and actual disposals.", requirement: "Specify stock, date or announcement",
    prompt: "For [A-share symbol] as of [date], verify a share-unlock or major-shareholder-sale story. Confirm scope or ask for the announcement. Separate unlocks, sale plans, progress reports and disclosed completed sales. Record publication date, event window, share class, quantity, percentage denominator, original source and open questions. Do not equate unlocked shares with sales or add potentially overlapping disclosures.",
  },
  "conflicting-news": {
    title: "Two reports conflict. Which can we verify?", description: "Trace original disclosures, timestamps and subsequent corrections.", requirement: "Paste articles or excerpts",
    prompt: "I will paste two conflicting reports about [company / event]. Compare primary sources, publication times, citation chains, secondhand claims and corrections. Separate confirmed claims, single-source claims, contradictions and points needing original documents. Provide a verification checklist. State when originals are inaccessible; do not treat popularity as proof.",
  },
  "bear-case": {
    title: "Build the strongest counterargument", description: "Find hidden assumptions, counterevidence and invalidation conditions.", requirement: "Provide a thesis or report",
    prompt: "Challenge the [company] thesis I will provide. For each argument, identify assumptions, supporting evidence, the strongest counterevidence, alternative explanations and invalidation conditions. Separate business, financial and valuation risks from insufficient evidence. Do not invent negative facts to create artificial balance. Wait for my research materials first.",
  },
  "next-check": {
    title: "Turn “keep watching” into a testable condition", description: "Define a metric, baseline, threshold, date and verification source.", requirement: "Provide conclusion and baseline",
    prompt: "Turn the research conclusion I provide into testable conditions. Replace vague claims such as recovering demand, improving cash flow or stabilizing trends with a metric, baseline, threshold, check date, source and invalidation condition. Unsupported thresholds need my approval. Separate checks available through existing price / volume-ratio tools from financial-statement or filing checks needing manual review. Do not create tasks automatically.",
  },
  "thesis-review": {
    title: "Was the thesis wrong, or did evidence change?", description: "Review what was knowable at the time without hindsight bias.", requirement: "Provide original date, thesis and updates",
    prompt: "Review my [date] research judgment on [company]. I will provide the original thesis, evidence and later disclosures. Separate facts known then, facts available but missed, and information revealed later. Check whether original validation conditions were triggered and flag attribution that cannot be established. Use original hypothesis–later evidence–supported/refuted/unresolved–process improvement. Avoid hindsight claims that later outcomes were predictable.",
  },
  "one-page": {
    title: "Condense a report into a one-page brief", description: "Retain the thesis, evidence, disagreements, risks and next steps.", requirement: "Provide the report text",
    prompt: "Condense the report I provide into a one-page investment committee brief: research question, cutoff date, three key findings, major bull/bear disagreements, data gaps, invalidation conditions and next checks. Preserve original evidence IDs and distinguish facts, calculations and judgments. Do not add financial figures, sources or targets absent from the original. Wait for the report first.",
  },
  "management-questions": {
    title: "Five questions for the next earnings call", description: "Tie every question to a specific unresolved research issue.", requirement: "Provide recent results and open questions",
    prompt: "Help me prepare for [company]'s earnings call or management interview. Confirm the materials first. Based on the results and concerns I provide, draft five specific questions covering growth quality, margins, cash collection, capital allocation and key risks. For each, explain why it matters, existing evidence, the measurable answer sought and how to verify it later. Avoid generic strategy or confidence questions.",
  },
  "brief-draft": {
    title: "Draft a Hong Kong morning-brief workflow", description: "Specify scope, time window, deduplication and missing-data handling.", requirement: "Draft only; user creates the task",
    prompt: "Draft instructions for a Hong Kong market morning brief. Do not create a scheduled task yet. Cover representative stocks' prior completed-session performance, overnight developments, material announcements and items to verify today. Define Hong Kong time, news lookback, deduplication, sourcing and handling of holidays, delayed prices and missing data. Separate a market brief from single-stock research. List the stock universe, run time and notification preferences I must confirm.",
  },
};
