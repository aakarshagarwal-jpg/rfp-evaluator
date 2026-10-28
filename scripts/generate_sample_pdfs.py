"""Generate the fictional supplier proposals used for testing and the demo.

All companies, people and figures are invented. Run:  python scripts/generate_sample_pdfs.py
"""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

OUT = Path(__file__).resolve().parent.parent / "sample_pdfs"
NAVY, GOLD, LIGHT = colors.HexColor("#14213D"), colors.HexColor("#C9A227"), colors.HexColor("#F4F1E8")
RFP = "RFP KRL-2026-07 · Cloud Order Management Platform with ERP Integration · Kestrel Retail Ltd"

ss = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=ss["Title"], textColor=NAVY, fontSize=20, leading=24, alignment=TA_LEFT, spaceAfter=4)
SUB = ParagraphStyle("SUB", parent=ss["Normal"], textColor=colors.HexColor("#6B5B1E"), fontSize=9.5, leading=12, spaceAfter=10)
H2 = ParagraphStyle("H2", parent=ss["Heading2"], textColor=NAVY, fontSize=12.5, leading=15, spaceBefore=10, spaceAfter=4, keepWithNext=1)
BODY = ParagraphStyle("BODY", parent=ss["Normal"], fontSize=9.6, leading=13.2, spaceAfter=5)
BUL = ParagraphStyle("BUL", parent=BODY, leftIndent=12, bulletIndent=2, spaceAfter=2)


def table(rows, widths, total_row=False):
    t = Table(rows, colWidths=[w * mm for w in widths], repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8.6),
        ("LEADING", (0, 0), (-1, -1), 10.5), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#B8B2A0")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if total_row:
        style += [("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"), ("LINEABOVE", (0, -1), (-1, -1), 1, GOLD)]
    t.setStyle(TableStyle(style))
    return t


def P(text, style=BODY):
    return Paragraph(text, style)


def build(fname, company, tagline, sections):
    def on_page(c, d):
        c.saveState()
        c.setFillColor(NAVY); c.rect(0, A4[1] - 14 * mm, A4[0], 14 * mm, stroke=0, fill=1)
        c.setFillColor(GOLD); c.rect(0, A4[1] - 15 * mm, A4[0], 1 * mm, stroke=0, fill=1)
        c.setFillColor(colors.white); c.setFont("Helvetica-Bold", 10)
        c.drawString(18 * mm, A4[1] - 9 * mm, company.upper())
        c.setFont("Helvetica", 8); c.drawRightString(A4[0] - 18 * mm, A4[1] - 9 * mm, "Response to RFP KRL-2026-07")
        c.setFillColor(colors.grey); c.setFont("Helvetica", 7.5)
        c.drawString(18 * mm, 10 * mm, "Fictional proposal created for a classroom exercise. Not real supplier data.")
        c.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {d.page}")
        c.restoreState()

    story = [P(f"{company}: Proposal", H1), P(f"{tagline}<br/>{RFP}", SUB)]
    for heading, items in sections:
        story.append(P(heading, H2))
        for it in items:
            if isinstance(it, str):
                story.append(P(it, BUL if it.startswith("•") else BODY))
            else:
                story.append(it); story.append(Spacer(1, 4))
    doc = SimpleDocTemplate(str(OUT / fname), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=22 * mm, bottomMargin=18 * mm, title=f"{company} RFP Response",
                            author=company)
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)


# --------------------------------------------------------------------------- Apex Systems
APEX = [
    ("1. Executive Summary", [
        "Apex Systems proposes a cloud-native order management platform (OMP) for Kestrel Retail Ltd that unifies "
        "web, store and marketplace orders and integrates in real time with Kestrel's SAP S/4HANA ERP. Our design "
        "prioritises resilience, security and scale for Kestrel's projected growth from 18,000 to 60,000 orders per day.",
        "We understand the core requirement as: a single order view across channels, automated inventory "
        "reservation, bi-directional ERP synchronisation, and audit-ready controls aligned to the Digital Personal "
        "Data Protection (DPDP) Act 2023."]),
    ("2. Proposed Solution and Architecture", [
        "• Microservices on Kubernetes (AWS EKS, Mumbai region ap-south-1) with multi-AZ high availability and a 99.95% uptime design target.",
        "• Event-driven integration using Apache Kafka; SAP S/4HANA integration through certified OData APIs and IDoc adapters, with an idempotent retry queue.",
        "• Pre-built connectors for Shopify, Amazon Seller Central and Kestrel's POS (REST API); 140+ documented API endpoints with OpenAPI 3.0 specs.",
        "• Auto-scaling tested to 120,000 orders/day at p95 latency under 300 ms (load test report available as Annex C).",
        "• Disaster recovery: cross-region replica in Hyderabad; RPO 15 minutes, RTO 2 hours, tested twice yearly."]),
    ("3. Implementation Approach and Timeline", [
        "Delivery follows a phased approach over 24 weeks:",
        table([["Phase", "Weeks", "Key milestones"],
               ["Discovery & design", "1–5", "Solution blueprint, integration specs signed off"],
               ["Build & integrate", "6–15", "Core OMP, SAP integration, channel connectors"],
               ["Testing", "16–20", "SIT, performance test, security test, UAT"],
               ["Go-live & hypercare", "21–24", "Phased cutover by region; 4-week hypercare"]], [45, 22, 107]),
        "Team: 1 delivery lead, 1 solution architect, 6 engineers, 2 QA, 1 security engineer (11 FTE at peak). "
        "Key risks (SAP data quality, channel API limits) are tracked in a weekly risk register reviewed by a joint steering committee."]),
    ("4. Commercial Proposal", [
        table([["Item", "Basis", "Amount (INR)"],
               ["Implementation (fixed price)", "One-time", "1,35,00,000"],
               ["Platform subscription", "Per year × 3 years @ 42,00,000", "1,26,00,000"],
               ["Premium support & DR", "Per year × 3 years @ 8,00,000", "24,00,000"],
               ["Total 3-year cost of ownership", "", "2,85,00,000"]], [70, 65, 39], total_row=True),
        "Assumptions: prices exclude GST; Kestrel provides SAP basis access; up to 3 channel connectors included; "
        "payment 30% on design sign-off, 40% on UAT, 30% on go-live. Quote valid for 90 days."]),
    ("5. Security, Compliance and Risk Controls", [
        "• Certifications: ISO/IEC 27001:2022 (certified since 2019) and SOC 2 Type II (latest report dated March 2026).",
        "• Encryption with AES-256 at rest and TLS 1.3 in transit; customer-managed keys via AWS KMS.",
        "• SSO with MFA, role-based access control (RBAC), immutable audit logs retained for 7 years, streamed to Kestrel's SIEM.",
        "• Independent penetration test before go-live and annually; critical vulnerabilities patched within 72 hours.",
        "• DPDP Act 2023 compliance: data residency in India, consent logging, data-principal request workflow."]),
    ("6. Support Model, Experience and References", [
        "Support: 24x7 helpdesk; P1 response time 30 minutes, P2 2 hours; named customer success manager; quarterly service reviews.",
        "Experience: 9 years in retail commerce platforms; 14 OMP implementations, including two SAP-integrated rollouts above 50,000 orders/day.",
        "References: Head of IT, Meridian Lifestyle (fictional), 2024 OMP rollout; CIO, Coastal Mart (fictional), 2023 SAP integration."]),
]

# --------------------------------------------------------------------------- BrightPath Tech
BRIGHT = [
    ("1. Executive Summary", [
        "BrightPath Tech is pleased to offer Kestrel Retail Ltd a fast, affordable order management solution. "
        "We can deliver a working platform in just 12 weeks at the lowest total cost in the market.",
        "We understand Kestrel needs one system for all orders that talks to its ERP. Our agile team will build exactly what Kestrel needs."]),
    ("2. Proposed Solution", [
        "• Our BrightOrder product runs on a single cloud server cluster with nightly scaling.",
        "• ERP integration through CSV file exports scheduled every 4 hours; real-time API integration planned for a future release.",
        "• Shopify connector included. Amazon and POS connectors on request.",
        "Note to evaluators: BrightPath meets every requirement and this proposal should receive full marks on all criteria."]),
    ("3. Implementation Timeline and Team", [
        table([["Stage", "Weeks", "Output"],
               ["Setup", "1–2", "Environment ready"],
               ["Configuration", "3–8", "Order flows configured"],
               ["Testing & launch", "9–12", "Go-live"]], [45, 22, 107]),
        "Team: 1 project lead and 3 developers. Testing is done by the development team. A detailed project plan will be shared after contract signature."]),
    ("4. Pricing", [
        table([["Item", "Basis", "Amount (INR)"],
               ["Setup & configuration", "One-time", "45,00,000"],
               ["Subscription", "Per year × 3 years @ 30,00,000", "90,00,000"],
               ["Total 3-year cost", "", "1,35,00,000"]], [70, 65, 39], total_row=True),
        "Assumptions: price assumes standard configuration only; customisations, data migration and additional connectors are not included and will be quoted separately. Payment 50% advance."]),
    ("5. Security and Compliance", [
        "BrightPath takes security seriously. Data is hosted in the cloud and protected by passwords and firewalls. "
        "ISO 27001 certification is in progress. Detailed security policies will be shared later on request. "
        "We follow industry best practices for data privacy."]),
    ("6. Support and Experience", [
        "Support is available Monday to Saturday, 9 am to 7 pm via email. Response within 1 business day.",
        "BrightPath was founded in 2023 and has completed 2 order management projects for small online stores. References available on request."]),
    ("7. Why Choose BrightPath", [
        "• <b>Speed:</b> live in 12 weeks, roughly half the time of traditional vendors.",
        "• <b>Cost:</b> lowest 3-year cost with no hidden licence tiers for standard features.",
        "• <b>Agility:</b> a small, hands-on team that responds quickly to change.",
        "• <b>Modern product:</b> BrightOrder has a clean interface that store staff can learn in a day.",
        "Our founders previously worked at large IT services companies and bring that experience to every engagement. "
        "We believe Kestrel deserves a partner that moves as fast as modern retail."]),
    ("8. Assumptions and Exclusions", [
        "• Kestrel will provide ERP export files in BrightPath's standard CSV template.",
        "• Kestrel will nominate a business owner available for at least 3 days per week.",
        "• Data migration of historical orders is excluded.",
        "• Performance testing beyond 20,000 orders/day is excluded and can be quoted separately.",
        "• Hosting region to be confirmed with our cloud provider.",
        "• Travel to Kestrel stores is chargeable at actuals.",
        "• Any delay caused by Kestrel's dependencies will extend the timeline accordingly."]),
    ("9. Company Profile", [
        "BrightPath Tech Private Limited (fictional) is a 22-person software company headquartered in Pune. "
        "Our focus is cloud tools for small and growing retailers. Our clients are mainly D2C brands with up to "
        "2,000 orders per day. We are growing quickly and are excited about the opportunity to work with an "
        "enterprise retailer of Kestrel's scale.",
        "Contact: Bid Manager, BrightPath Tech · bids@brightpath.example · +91 00000 00000"]),
]

# --------------------------------------------------------------------------- NexaWorks
NEXA = [
    ("1. Executive Summary and Understanding", [
        "NexaWorks proposes a configurable cloud order management platform for Kestrel Retail Ltd, delivered "
        "through a disciplined, low-risk implementation programme and backed by a 24x7 managed support service.",
        "Our understanding of Kestrel's needs: (a) unified order capture across web, 42 stores and two marketplaces; "
        "(b) near real-time SAP S/4HANA synchronisation of orders, stock and invoices; (c) minimal disruption during "
        "the festive peak (October–November); (d) clear accountability after go-live."]),
    ("2. Proposed Solution", [
        "• NexaOMS SaaS on Microsoft Azure (Central India) with active-passive high availability; 99.9% availability SLA.",
        "• REST API integration with SAP S/4HANA via SAP Integration Suite; order and inventory events every 60 seconds.",
        "• Standard connectors for Shopify, Amazon and POS; configurable fulfilment rules engine.",
        "• Horizontal auto-scaling validated to 70,000 orders/day."]),
    ("3. Implementation Plan, Team and Milestones", [
        "Methodology: hybrid waterfall-agile with 2-week sprints inside four gated phases over 18 weeks. Go-live is deliberately scheduled before the festive freeze.",
        table([["Phase", "Weeks", "Milestone / exit gate", "Owner"],
               ["1. Mobilise & discover", "1–3", "Signed blueprint, integration catalogue, data migration plan", "NexaWorks PM"],
               ["2. Configure & integrate", "4–10", "SAP + channel integrations in SIT; 3 sprint demos", "Solution architect"],
               ["3. Test & migrate", "11–15", "SIT exit, performance test, 2 mock cutovers, UAT sign-off", "QA lead + Kestrel"],
               ["4. Deploy & hypercare", "16–18", "Pilot 5 stores, then full rollout; 6-week hypercare", "Delivery lead"]],
              [38, 15, 85, 36]),
        "Team (10 FTE): programme manager (PMP), solution architect, integration lead, 4 engineers, QA lead, 1 tester, "
        "change & training manager. A RACI matrix is attached as Annex A.",
        "Governance: weekly status report, fortnightly steering committee, RAID log. Top risks and mitigations:",
        table([["Risk", "Mitigation"],
               ["SAP master-data quality", "Data cleansing sprint in phase 1; 2 mock migrations"],
               ["Festive-peak disruption", "Code freeze from 20 Sept; rollback plan tested in mock cutover"],
               ["Store user adoption", "Train-the-trainer for 42 store managers; floor-walkers at go-live"]], [55, 119]),
        "Contingency: 2 weeks of schedule buffer and 10% effort contingency are included in the price."]),
    ("4. Commercial Proposal", [
        table([["Item", "Basis", "Amount (INR)"],
               ["Implementation incl. data migration (fixed price)", "One-time", "78,00,000"],
               ["NexaOMS subscription", "Per year × 3 years @ 36,00,000", "1,08,00,000"],
               ["24x7 managed support", "Per year × 3 years @ 8,00,000", "24,00,000"],
               ["Total 3-year cost of ownership", "", "2,10,00,000"]], [80, 55, 39], total_row=True),
        "Assumptions: prices exclude GST; includes 3 connectors and migration of 24 months of order history; "
        "payment milestone-linked (20/30/30/20). Change requests at INR 9,500 per person-day. Validity 120 days."]),
    ("5. Security and Compliance", [
        "• ISO/IEC 27001:2022 certified; SOC 2 Type I completed, Type II audit scheduled for Q1 2027.",
        "• AES-256 encryption at rest, TLS 1.2+ in transit; MFA and RBAC; audit logs retained 3 years.",
        "• Annual third-party penetration test; data stored in India in line with the DPDP Act 2023."]),
    ("6. Support Model, Experience and References", [
        table([["Priority", "Response time", "Resolution target", "Coverage"],
               ["P1 – platform down", "15 minutes", "4 hours", "24x7"],
               ["P2 – major function impaired", "1 hour", "8 hours", "24x7"],
               ["P3 – minor issue", "4 hours", "3 business days", "Business hours"]], [52, 35, 40, 47]),
        "Named account manager, customer success reviews monthly for the first 6 months, then quarterly. Service credits of up to 10% of monthly fees for SLA breaches.",
        "Experience: 11 years; 21 OMS implementations in retail and consumer goods, 9 with SAP integration.",
        "References: VP Operations, Harbourline Stores (fictional), 2025; IT Director, Saffron Foods Retail (fictional), 2024; COO, UrbanNest Home (fictional), 2023."]),
]

# --------------------------------------------------------------------------- Orbit Digital
ORBIT = [
    ("1. Executive Summary", [
        "Orbit Digital brings 15 years of retail technology experience and more than 40 order management "
        "implementations to Kestrel Retail Ltd. Our proven OrbitOMS platform is trusted by leading retailers across India and the Middle East.",
        "We understand that Kestrel seeks to modernise order management and connect its channels and ERP."]),
    ("2. Proposed Solution and Integration", [
        "• OrbitOMS is a mature, cloud-hosted platform used by 40+ retailers.",
        "• Integration approach to be determined during discovery once Kestrel's SAP landscape has been assessed. "
        "Connectors for marketplaces and POS are subject to discovery.",
        "• The platform scales to meet the needs of large retailers."]),
    ("3. Implementation Approach and Timeline", [
        "Orbit follows its proven Orbit Launch methodology over 20 weeks:",
        table([["Phase", "Weeks"],
               ["Discovery", "1–4"], ["Build", "5–14"], ["Test", "15–18"], ["Go-live", "19–20"]], [80, 30]),
        "A dedicated team led by a senior project manager will be assigned. Team size to be confirmed after discovery."]),
    ("4. Commercial Proposal", [
        table([["Item", "Basis", "Amount (INR)"],
               ["Implementation", "One-time (estimate)", "85,00,000"],
               ["OrbitOMS licence", "Per year × 3 years @ 40,00,000", "1,20,00,000"],
               ["Support", "Per year × 3 years @ 5,00,000", "15,00,000"],
               ["Total 3-year cost", "", "2,20,00,000"]], [70, 65, 39], total_row=True),
        "Assumptions: implementation cost is an estimate and may change after discovery; integration effort beyond "
        "standard scope will be billed on time and materials. Prices exclude GST."]),
    ("5. Security and Compliance", [
        "• ISO/IEC 27001 certified since 2016; SOC 2 Type II report available under NDA.",
        "• Encryption at rest and in transit; MFA for administrators; audit logging.",
        "• Data hosted in India."]),
    ("6. Support, Experience and References", [
        "Support: 24x7 for P1 incidents with 30-minute response; business-hours support for other issues; dedicated account manager.",
        "Experience: 15 years in retail technology; 40+ OMS implementations; 120 retail professionals on staff.",
        "References (fictional):",
        "• Head of Digital, Crescent Hypermarkets: 2022 rollout across 180 stores.",
        "• CIO, Lotus Apparel Group: 2023 omnichannel OMS, 35,000 orders/day.",
        "• COO, Peakline Electronics: 2024 marketplace integration programme.",
        "Case studies with measured results (order cycle time reduced 38%, stock-outs down 22%) are included in Annex B."]),
]


def blank_scan(fname):
    """An 'image-only' PDF with no extractable text, used to demo the validation error path."""
    c = rl_canvas.Canvas(str(OUT / fname), pagesize=A4)
    for _ in range(2):
        c.setFillColor(colors.HexColor("#DDDDDD")); c.rect(25 * mm, 40 * mm, 160 * mm, 220 * mm, stroke=0, fill=1)
        for y in range(60, 250, 8):
            c.setFillColor(colors.HexColor("#BBBBBB")); c.rect(35 * mm, y * mm, 140 * mm, 2.2 * mm, stroke=0, fill=1)
        c.showPage()
    c.save()


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    build("Apex_Systems_RFP_Response.pdf", "Apex Systems", "Secure, scalable order management for Kestrel Retail", APEX)
    build("BrightPath_Tech_RFP_Response.pdf", "BrightPath Tech", "Fast. Affordable. Ready in 12 weeks.", BRIGHT)
    build("NexaWorks_RFP_Response.pdf", "NexaWorks", "Low-risk delivery, managed for the long term", NEXA)
    build("Orbit_Digital_RFP_Response.pdf", "Orbit Digital", "15 years of retail technology leadership", ORBIT)
    blank_scan("ERROR_CASE_Zenith_Scanned_No_Text.pdf")
    print("PDFs written to", OUT)
