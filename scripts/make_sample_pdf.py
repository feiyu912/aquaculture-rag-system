"""Generate a synthetic Chinese PDF used only for developing the RAG pipeline.

The text is illustrative, not an authoritative aquaculture reference.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

FONT = "STSong-Light"
pdfmetrics.registerFont(UnicodeCIDFont(FONT))

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "samples" / "aquaculture_sample.pdf"

styles = getSampleStyleSheet()
title_style = ParagraphStyle(
    "CJKTitle", parent=styles["Title"], fontName=FONT, fontSize=20, leading=28, alignment=TA_CENTER
)
subtitle_style = ParagraphStyle(
    "CJKSub", parent=styles["Normal"], fontName=FONT, fontSize=10, leading=16,
    alignment=TA_CENTER, textColor=colors.HexColor("#5b6b62"),
)
h1_style = ParagraphStyle(
    "CJKH1", parent=styles["Heading1"], fontName=FONT, fontSize=14, leading=22,
    textColor=colors.HexColor("#126b4e"), spaceBefore=10, spaceAfter=6,
)
body_style = ParagraphStyle(
    "CJKBody", parent=styles["BodyText"], fontName=FONT, fontSize=10.5, leading=18,
    firstLineIndent=21, spaceAfter=4,
)
bullet_style = ParagraphStyle(
    "CJKBullet", parent=body_style, firstLineIndent=0, leftIndent=14, bulletIndent=4,
)
note_style = ParagraphStyle(
    "CJKNote", parent=body_style, fontSize=9, textColor=colors.HexColor("#7a5b00"),
    backColor=colors.HexColor("#fff8e6"), borderPadding=6, firstLineIndent=0,
)

PAGES: list[list[object]] = [
    [
        Paragraph("水产养殖水质管理示例资料", title_style),
        Spacer(1, 4 * mm),
        Paragraph("系统演示用合成资料 · 不作为养殖依据", subtitle_style),
        Spacer(1, 8 * mm),
        Paragraph("一、养殖水质基本指标", h1_style),
        Paragraph(
            "水质是水产养殖管理的核心。日常监测通常关注溶解氧、酸碱度、氨氮、亚硝酸盐、"
            "水温和透明度等指标。不同品种、不同养殖阶段和不同养殖模式的要求并不相同，"
            "应结合当地技术规范和实际养殖条件调整。",
            body_style,
        ),
        Paragraph("常见指标的参考范围如下，仅用于系统演示：", body_style),
        Paragraph("• 溶解氧：保持在 5 mg/L 以上，低氧时需及时增氧。", bullet_style),
        Paragraph("• 酸碱度：多数养殖水体适宜范围约为 7.5 至 8.5。", bullet_style),
        Paragraph("• 氨氮：宜控制在 0.2 mg/L 以下，过高会增加水产动物应激。", bullet_style),
        Paragraph("• 亚硝酸盐：宜控制在 0.1 mg/L 以下，需关注转化过程。", bullet_style),
        Paragraph("• 透明度：一般可参考 30 至 40 cm，视品种和养殖模式调整。", bullet_style),
        Spacer(1, 4 * mm),
        Paragraph(
            "注意：以上数值是示例资料中的通用参考，不能替代具体品种的养殖技术规范，"
            "也不能作为用药或诊断依据。",
            note_style,
        ),
    ],
    [
        Paragraph("二、中华绒螯蟹养殖要点", h1_style),
        Paragraph(
            "中华绒螯蟹喜欢水质清新、溶氧充足、水草丰富的环境。养殖池塘通常需要保持一定的"
            "水草覆盖，为蜕壳和栖息提供隐蔽场所。水草不足时，蟹类更容易发生相互残杀，"
            "蜕壳期间的成活率也可能下降。",
            body_style,
        ),
        Paragraph(
            "投喂应坚持定时、定点、定质、定量的原则。饲料种类可以包括配合饲料、小鱼虾和"
            "植物性饵料。高温季节应减少残饵，避免残饵腐败导致氨氮和亚硝酸盐升高。",
            body_style,
        ),
        Paragraph("蜕壳期管理建议：", h1_style),
        Paragraph("• 保持溶解氧稳定，避免剧烈换水造成应激。", bullet_style),
        Paragraph("• 适当补充钙、镁等矿物质，但应按产品说明和技术规范使用。", bullet_style),
        Paragraph("• 减少人为惊扰，及时清除残饵和死蟹。", bullet_style),
        Paragraph("• 发现软壳蟹时，不宜强行分拣或长时间离水。", bullet_style),
        Spacer(1, 4 * mm),
        Paragraph(
            "以上管理建议来自示例资料，实际生产应结合池塘条件、密度、水草和天气情况综合判断。",
            note_style,
        ),
    ],
    [
        Paragraph("三、凡纳滨对虾养殖要点", h1_style),
        Paragraph(
            "凡纳滨对虾又称南美白对虾，是我国重要的海水和咸淡水养殖品种。养殖过程中需要"
            "关注盐度、水温、溶解氧和氨氮等指标。苗种下塘前应进行水质调理和试水，"
            "避免盐度或温度突变造成应激。",
            body_style,
        ),
        Paragraph(
            "示例资料给出的参考范围为：水温 25 至 30 摄氏度，盐度 10 至 25，溶解氧保持在"
            " 5 mg/L 以上。实际养殖中应根据苗种来源、淡化程度和当地气候进行调整。",
            body_style,
        ),
        Paragraph("四、水质异常的处理原则", h1_style),
        Paragraph(
            "发现水质指标异常时，首先应复测确认，排除仪器误差和采样误差。随后分析可能的"
            "原因，例如投喂过量、藻类死亡、底质恶化或天气突变。处理措施通常包括增氧、"
            "换水、调整投喂和控制有机物输入。",
            body_style,
        ),
        Paragraph(
            "不建议在未确认病因的情况下盲目使用消毒剂或抗生素。涉及用药时，应遵循当地"
            "水产养殖用药规范，并咨询执业兽医或水产技术推广人员。",
            note_style,
        ),
    ],
    [
        Paragraph("五、日常监测记录表", h1_style),
        Paragraph(
            "下表为示例记录表，用于说明结构化表格在知识库中的表示方式。实际记录应包含"
            "塘口编号、采样时间、天气和测定方法等信息。",
            body_style,
        ),
        Spacer(1, 3 * mm),
        Table(
            [
                ["日期", "溶解氧(mg/L)", "酸碱度", "氨氮(mg/L)", "备注"],
                ["示例 1", "6.2", "8.0", "0.08", "晴，正常投喂"],
                ["示例 2", "4.1", "7.8", "0.25", "阴，开启增氧机"],
                ["示例 3", "5.5", "8.2", "0.12", "雨后，减少投喂"],
            ],
            colWidths=[28 * mm, 34 * mm, 24 * mm, 32 * mm, 44 * mm],
            style=TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), FONT),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e6f2ec")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#126b4e")),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b9c9c0")),
                    ("ALIGN", (1, 1), (-1, -1), "CENTER"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            ),
        ),
        Spacer(1, 6 * mm),
        Paragraph("六、术语说明", h1_style),
        Paragraph("• 溶解氧：水中游离氧的浓度，单位通常为 mg/L。", bullet_style),
        Paragraph("• 氨氮：水中以铵离子和游离氨形式存在的氮，是水质监测的重要指标。", bullet_style),
        Paragraph("• 亚硝酸盐：氮循环中间产物，浓度过高会对水产动物产生不良影响。", bullet_style),
        Paragraph("• 蜕壳：甲壳类动物生长过程中脱去旧壳、形成新壳的过程。", bullet_style),
        Spacer(1, 6 * mm),
        Paragraph("— 示例资料结束 —", subtitle_style),
    ],
]


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        leftMargin=22 * mm,
        rightMargin=22 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        title="水产养殖水质管理示例资料",
        author="Aquaculture RAG demo",
    )
    story: list[object] = []
    for index, page in enumerate(PAGES):
        story.extend(page)
        if index < len(PAGES) - 1:
            story.append(PageBreak())
    doc.build(story)
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()