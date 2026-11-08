"""Portable Markdown/JSON/PDF research exports, using actual saved run data."""
from io import BytesIO
from xml.sax.saxutils import escape
from .research_models import ROLES

LABELS = {**ROLES, "bull": "多头研究员", "bear": "空头研究员", "risk": "风险审查"}


def markdown(report):
    config, assessment = report["config"], report.get("assessment") or {}
    evidence = report.get("evidence", {})
    lines = [f"# {report['symbol']} 金融研究报告", "",
        f"- 分析截止日：{report['as_of']}（市场当地日期）",
        f"- 生成时间：{report['created_at']}", f"- 运行状态：{report['status']}",
        f"- 研究深度：{config['depth']}", f"- 分析师：{', '.join(LABELS.get(a,a) for a in config['analysts'])}",
        f"- 用户问题：{config['question']}", f"- 报告编号：{report['id']}", "",
        "## 执行摘要", assessment.get("summary", "报告尚未完成。"), "",
        f"研究倾向：{assessment.get('stance', '尚未形成')}；风险级别：{assessment.get('risk_level', '无法判断')}", "",
        f"证据覆盖：{report.get('evidence_coverage', '未计算')}%（不是模型预测概率）", ""]
    sections = (("key_points", "核心观点"), ("catalysts", "观察催化剂"), ("risks", "风险因素"),
                ("valuation_scenarios", "估值场景与假设"), ("invalidation_conditions", "结论失效条件"))
    if report.get("workflow"):
        lines = [f"# {report['symbol']}", "", f"- 生成时间：{report['created_at']}", f"- 运行状态：{report['status']}",
                 f"- 报告编号：{report['id']}", "", "## 摘要", assessment.get("summary", "简报尚未完成。"), ""]
        sections = (("key_points", "观察记录"),)
    for field, title in sections:
        lines += [f"## {title}"] + [f"- {s}" for s in assessment.get(field, [])] + [""]
        if field == "valuation_scenarios" and not assessment.get(field):
            lines += ["证据或估值输入不足，未生成目标价。", ""]
    metrics = evidence.get("metrics", {})
    if metrics:
        lines += ["## 代码计算指标", f"最近交易日：{metrics.get('last_session')}；收盘：{metrics.get('close')}；币种按证券挂牌市场。",
            "未复权日线；以下结果不是总回报。"]
        for k, v in metrics.items():
            lines.append(f"- {k}: {v}")
        lines += [""]
    for role, finding in report.get("findings", {}).items():
        lines += [f"## {LABELS.get(role, role)}", finding["summary"], f"研究倾向：{finding['stance']}", "",
                  *[f"- {v}" for v in finding.get("findings", [])], "",
                  "风险：", *[f"- {v}" for v in finding.get("risks", [])], "",
                  "待验证/数据缺口：", *[f"- {v}" for v in finding.get("missing", [])], ""]
    lines += ["## 来源与证据"]
    for source in evidence.get("sources", []):
        lines += [f"### [{source['id']}] {source['title']}", f"- 来源：{source['provider']}"]
        if source.get("event_date"):
            lines.append(f"- 事件日：{source['event_date']}")
        lines += [f"- 发布时间/交易日：{source.get('published_at') or '未知'}", f"- 链接：{source['url']}"]
        if source.get("filing_url"):
            lines.append(f"- 公告佐证：{source['filing_url']}")
        if source.get("document_id"):
            lines += [f"- 固定文档：{source['document_id']} · 文件 v{source['document_version']} · 元数据修订 {source['metadata_revision']} · PDF 第 {source['page_number']} 页",
                f"- 原件 SHA256：{source['document_sha256']}",
                f"- App 内原页：/evidence/{source['knowledge_search_id']}/{source['knowledge_citation_id']}"]
        lines += [source["content"], ""]
    pinned=evidence.get("knowledge_scope")
    if pinned:
        lines += ["## 提交时固定的知识资料范围",f"- 固定时间：{pinned['pinned_at']}",
            f"- 截止日/市场：{pinned['cutoff']['as_of']} / {pinned['cutoff']['market']}",
            f"- 当时符合：{pinned['eligible_count']}；排除：{pinned['excluded_count']}",
            *[f"- {item['title']} · v{item['version']} / metadata {item['metadata_revision']} · {item.get('exclusion') or 'eligible_at_submission'}" for item in pinned["documents"]],""]
    lines += ["## 数据限制", *[f"- {v}" for v in evidence.get("gaps", [])], "",
              evidence.get("methodology", ""), "", "## 方法与运行记录"]
    for stage in report["stages"]:
        lines.append(f"- {LABELS.get(stage['id'], stage['id'])}: {stage['status']} - {stage.get('detail', '')}")
    lines += ["", "本报告用于研究与学习，不构成个性化投资建议。结论基于报告列明的证据与假设，不自动执行交易。"]
    return "\n".join(lines)


def pdf(report):
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.pagesizes import A4
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=45, rightMargin=45, topMargin=52, bottomMargin=48,
                            title=f"{report['symbol']} Research {report['as_of']}", author="Aperture Research")
    normal = ParagraphStyle("body", fontName="STSong-Light", fontSize=10, leading=17, wordWrap="CJK",
                            textColor=colors.HexColor("#243247"), spaceAfter=7, splitLongWords=True)
    story = []
    for line in markdown(report).splitlines():
        if not line.strip():
            story.append(Spacer(1, 5))
            continue
        level = len(line) - len(line.lstrip("#")) if line.startswith("#") else 0
        style = ParagraphStyle(f"heading{level}", parent=normal, fontSize={1:20, 2:14, 3:11}.get(level,10),
            leading={1:29, 2:23, 3:18}.get(level,17), spaceBefore=12 if level else 0, keepWithNext=bool(level))
        text = line.lstrip("# ") if level else line
        # Escape all external strings; no raw user/provider HTML enters report markup.
        story.append(Paragraph(escape(text), style))
    def page_number(canvas, document):
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#748095"))
        canvas.drawString(45, 28, f"APERTURE / {report['symbol']} / {report['as_of']}")
        canvas.drawRightString(A4[0] - 45, 28, str(document.page))
    doc.build(story, onFirstPage=page_number, onLaterPages=page_number)
    return buffer.getvalue()
