from flask import Flask, request, jsonify, send_file, render_template_string
import io
import math
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

app = Flask(__name__)

# ── SOVOS BRAND COLORS ──
NAVY      = colors.HexColor('#0A0E33')
WHITE     = colors.HexColor('#FFFFFF')
BLUE      = colors.HexColor('#0078D6')
BLUE_PALE = colors.HexColor('#E8F9FF')
BLUE_LIGHT= colors.HexColor('#F4FCFF')
GREY_LINE = colors.HexColor('#E0E0E0')
GREY_TEXT = colors.HexColor('#666666')
GREEN     = colors.HexColor('#00641F')
GREEN_BG  = colors.HexColor('#E8FFE8')
AMBER     = colors.HexColor('#FA8F2D')
AMBER_BG  = colors.HexColor('#FFF7F0')

# ── FIXED ALLOWANCES ──
TRAVEL    = 19600
MEDICAL   = 15000
MOBILE    = 12000
EDUCATION = 2400
FOOD      = 15600

def fmt_indian(n):
    n = int(round(n))
    if n == 0: return "0"
    s = str(abs(n))
    if len(s) > 3:
        last3 = s[-3:]
        rest = s[:-3]
        groups = []
        while len(rest) > 2:
            groups.append(rest[-2:])
            rest = rest[:-2]
        if rest: groups.append(rest)
        groups.reverse()
        s = ','.join(groups) + ',' + last3
    return s

def compute_salary(ctc, nps_rate=15, include_nps=False):
    basic = ctc * 0.50
    hra   = basic * 0.40
    lta   = round(ctc / 12)
    pf_wage = min(basic / 12, 15000)
    pf_emp_m = pf_wage * 0.12
    pf_emp_a = pf_emp_m * 12
    pf_ee_m  = pf_wage * 0.12
    pf_ee_a  = pf_ee_m * 12
    nps_emp_m = (basic / 12) * (nps_rate / 100) if include_nps else 0
    nps_emp_a = nps_emp_m * 12
    fixed = basic + hra + TRAVEL + MEDICAL + MOBILE + EDUCATION + FOOD + lta
    cca = max(0, ctc - fixed - pf_emp_a - nps_emp_a)
    sub = basic + hra + TRAVEL + MEDICAL + MOBILE + EDUCATION + 0 + lta + cca + FOOD
    return dict(basic=basic, hra=hra, lta=lta, cca=cca,
                pf_emp_m=pf_emp_m, pf_emp_a=pf_emp_a,
                pf_ee_m=pf_ee_m,   pf_ee_a=pf_ee_a,
                nps_emp_m=nps_emp_m, nps_emp_a=nps_emp_a, sub=sub)

def resolve_mode(ctc, mode, monthly_comm_esic, nps_rate):
    if mode == 'nps': return 'nps'
    s = compute_salary(ctc)
    gross = s['sub'] / 12 + monthly_comm_esic
    if mode == 'auto': return 'esic' if gross <= 21000 else 'no-esic'
    return mode

def generate_pdf_bytes(data):
    ctc          = float(data['ctc'])
    name         = data.get('name', '[Candidate Name]')
    role         = data.get('role', '[Role Title]')
    date_str     = data.get('date', '[Date]')
    mode         = data.get('mode', 'auto')
    comm_type    = data.get('comm_type', 'none')
    comm_amount  = float(data.get('comm_amount', 0))
    comm_pct     = data.get('comm_pct', False)
    nps_rate     = float(data.get('nps_rate', 15))
    bonus_pct    = float(data.get('bonus_pct', 8))

    # Commission
    annual_comm = (comm_amount / 100 * ctc) if comm_pct else comm_amount
    if comm_type == 'none': annual_comm = 0
    periods = {'monthly':12,'bimonthly':6,'quarterly':4,'annual':1}.get(comm_type, 1)
    comm_pp = annual_comm / periods if comm_type != 'none' else 0
    comm_inc_esic = comm_type in ('monthly','bimonthly')
    monthly_comm_esic = (comm_pp if comm_type=='monthly' else comm_pp/2) if comm_inc_esic else 0

    resolved = resolve_mode(ctc, mode, monthly_comm_esic, nps_rate)
    include_nps = (resolved == 'nps')
    sal = compute_salary(ctc, nps_rate, include_nps)

    gross_esic = sal['sub'] / 12 + monthly_comm_esic
    esic_elig  = gross_esic <= 21000
    esic_emp_m = gross_esic * 0.0325 if esic_elig else 0
    esic_ee_m  = gross_esic * 0.0075 if esic_elig else 0

    taxable = max(0, sal['sub'] - sal['pf_ee_a'] - 50000)
    tax = 0
    if taxable > 1500000:      tax = (taxable-1500000)*0.30 + 187500
    elif taxable > 1200000:    tax = (taxable-1200000)*0.20 + 127500
    elif taxable > 900000:     tax = (taxable-900000)*0.15  + 82500
    elif taxable > 600000:     tax = (taxable-600000)*0.10  + 52500
    elif taxable > 300000:     tax = (taxable-300000)*0.05
    tax_m = tax / 12
    take_home = sal['sub']/12 - sal['pf_ee_m'] - esic_ee_m - tax_m

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=20*mm, rightMargin=20*mm,
                            topMargin=15*mm, bottomMargin=25*mm)

    def ps(name, font='Helvetica', size=10, color=colors.black,
           bold=False, align=TA_LEFT, sb=0, sa=4, leading=None):
        return ParagraphStyle(name, fontName='Helvetica-Bold' if bold else font,
                              fontSize=size, textColor=color, alignment=align,
                              spaceBefore=sb, spaceAfter=sa, leading=leading or size*1.4)

    s_normal = ps('n', color=NAVY, size=10, sa=3)
    s_bold   = ps('b', color=NAVY, size=10, bold=True, sa=3)
    s_sub    = ps('s', color=BLUE, size=11, bold=True, sa=2)
    s_small  = ps('sm', color=GREY_TEXT, size=9, sa=2)
    s_right  = ps('r', color=NAVY, size=10, align=TA_RIGHT, sa=3)
    s_center = ps('c', color=NAVY, size=10, align=TA_CENTER, sa=3)
    s_muted  = ps('m', color=GREY_TEXT, size=9, sa=2)
    s_wht    = ps('w', color=WHITE, size=10, bold=True)
    s_wht_r  = ps('wr', color=WHITE, size=10, bold=True, align=TA_RIGHT)

    story = []

    # Header
    hdr = Table([[
        Paragraph('<b>SOVOS</b>', ps('logo', size=22, color=WHITE, bold=True)),
        Paragraph('Compensation Annex — India', ps('ht', size=13, color=WHITE, bold=True, align=TA_RIGHT))
    ]], colWidths=['50%','50%'])
    hdr.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1),NAVY),
        ('TOPPADDING',(0,0),(-1,-1),12),('BOTTOMPADDING',(0,0),(-1,-1),12),
        ('LEFTPADDING',(0,0),(0,-1),16),('RIGHTPADDING',(-1,0),(-1,-1),16),
    ]))
    story.append(hdr)
    story.append(Spacer(1,6*mm))

    # Candidate info
    mode_label = {'esic':'With ESIC','no-esic':'Without ESIC','nps':'With NPS'}.get(resolved,'Standard')
    info = Table([
        [ps_p('Candidate', s_muted), Paragraph(name, s_bold),
         ps_p('Date', s_muted), Paragraph(date_str, s_normal)],
        [ps_p('Role', s_muted), Paragraph(role, s_normal),
         ps_p('Structure', s_muted), Paragraph(mode_label, s_normal)],
    ], colWidths=[28*mm,67*mm,25*mm,50*mm])
    info.setStyle(TableStyle([
        ('ROWBACKGROUNDS',(0,0),(-1,-1),[BLUE_LIGHT, WHITE]),
        ('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6),
        ('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),
        ('LINEBELOW',(0,0),(-1,-1),0.5,GREY_LINE),
    ]))
    story.append(info)
    story.append(Spacer(1,5*mm))

    story.append(Paragraph('ANNEX 1 – CTC BREAKDOWN', s_sub))
    story.append(HRFlowable(width='100%', thickness=1.5, color=BLUE, spaceAfter=3))
    story.append(Spacer(1,2*mm))

    def r(label, monthly, annual, bold=False, white=False):
        fc = WHITE if white else NAVY
        fn = 'Helvetica-Bold' if bold else 'Helvetica'
        lp = ParagraphStyle('rl', fontName=fn, fontSize=10, textColor=fc)
        rp = ParagraphStyle('rr', fontName=fn, fontSize=10, textColor=fc, alignment=TA_RIGHT)
        mv = fmt_indian(monthly) if monthly else ('—' if not bold else '0')
        av = fmt_indian(annual)  if annual  else ('—' if not bold else '0')
        return [Paragraph(label, lp), Paragraph(mv, rp), Paragraph(av, rp)]

    s = sal
    rows = [
        [Paragraph('EARNINGS', ps('th',font='Helvetica-Bold',size=10,color=WHITE,bold=True)),
         Paragraph('MONTHLY',  ps('th2',font='Helvetica-Bold',size=10,color=WHITE,bold=True,align=TA_RIGHT)),
         Paragraph('ANNUALLY', ps('th3',font='Helvetica-Bold',size=10,color=WHITE,bold=True,align=TA_RIGHT))],
        r('Basic + DA',               s['basic']/12,    s['basic']),
        r('HRA',                       s['hra']/12,      s['hra']),
        r('Travelling Allowance',      TRAVEL/12,        TRAVEL),
        r('Medical Allowance',         MEDICAL/12,       MEDICAL),
        r('Mobile Reimbursement',      MOBILE/12,        MOBILE),
        r('Education Allowance',       EDUCATION/12,     EDUCATION),
        r('Statutory Bonus',           0,                0),
        r('Leave Travel Allowance',    s['lta']/12,      s['lta']),
        r('City Compensatory Allowance (CCA)', s['cca']/12, s['cca']),
        r('Food Coupon',               FOOD/12,          FOOD),
    ]
    if comm_type != 'none' and annual_comm > 0:
        fl = {'monthly':'Monthly','bimonthly':'Bi-monthly','quarterly':'Quarterly','annual':'Annual'}[comm_type]
        rows.append(r(f'Commission ({fl})', annual_comm/12, annual_comm))

    sub_idx = len(rows)
    rows.append(r('Sub Total', s['sub']/12, s['sub'], bold=True))
    rows.append(r('PF – Employer Contribution', s['pf_emp_m'], s['pf_emp_a']))
    rows.append(r('ESIC Employer', esic_emp_m if esic_elig else 0, esic_emp_m*12 if esic_elig else 0))
    if include_nps:
        rows.append(r(f'NPS – Employer Contribution ({int(nps_rate)}%)', s['nps_emp_m'], s['nps_emp_a']))
    total_idx = len(rows)
    rows.append(r('TOTAL COST TO COMPANY (CTC)', ctc/12, ctc, bold=True, white=True))

    mt = Table(rows, colWidths=[90*mm, 40*mm, 40*mm])
    ts = TableStyle([
        ('BACKGROUND',(0,0),(-1,0),BLUE),
        ('LINEBELOW',(0,0),(-1,0),1.5,WHITE),
        ('TOPPADDING',(0,0),(-1,0),10),('BOTTOMPADDING',(0,0),(-1,0),10),
        ('BACKGROUND',(0,1),(-1,-1),WHITE),
        ('LINEBELOW',(0,1),(-1,-2),0.5,GREY_LINE),
        ('TOPPADDING',(0,1),(-1,-1),7),('BOTTOMPADDING',(0,1),(-1,-1),7),
        ('LEFTPADDING',(0,0),(-1,-1),10),('RIGHTPADDING',(0,0),(-1,-1),10),
        ('LINEBEFORE',(0,0),(-1,-1),0,WHITE),('LINEAFTER',(0,0),(-1,-1),0,WHITE),
        ('BACKGROUND',(0,sub_idx),(-1,sub_idx),BLUE_PALE),
        ('LINEABOVE',(0,sub_idx),(-1,sub_idx),1,BLUE),
        ('BACKGROUND',(0,total_idx),(-1,total_idx),NAVY),
        ('LINEABOVE',(0,total_idx),(-1,total_idx),1.5,BLUE),
    ])
    mt.setStyle(ts)
    story.append(mt)
    story.append(Spacer(1,5*mm))

    # Deductions
    story.append(Paragraph('EMPLOYEE DEDUCTIONS (Monthly Estimate)', s_sub))
    story.append(HRFlowable(width='100%', thickness=1, color=BLUE, spaceAfter=3))
    ded_rows = [
        [Paragraph('Component', ps('dh',font='Helvetica-Bold',size=9,color=WHITE,bold=True)),
         Paragraph('Rate', ps('dh2',font='Helvetica-Bold',size=9,color=WHITE,bold=True,align=TA_CENTER)),
         Paragraph('Monthly', ps('dh3',font='Helvetica-Bold',size=9,color=WHITE,bold=True,align=TA_RIGHT))],
        [Paragraph('Provident Fund (Employee)', s_normal),
         Paragraph('12% of Basic (≤ ₹15,000 wage)', ps('dc',size=9,color=NAVY,align=TA_CENTER)),
         Paragraph(fmt_indian(s['pf_ee_m']), s_right)],
        [Paragraph('ESIC (Employee)', s_normal),
         Paragraph('0.75% of gross' if esic_elig else 'Exempt — gross > ₹21,000', ps('dc2',size=9,color=NAVY,align=TA_CENTER)),
         Paragraph(fmt_indian(esic_ee_m) if esic_elig else '—', s_right)],
        [Paragraph('Estimated Income Tax', s_normal),
         Paragraph('New regime FY2025-26 (indicative)', ps('dc3',size=9,color=NAVY,align=TA_CENTER)),
         Paragraph(fmt_indian(tax_m), s_right)],
    ]
    dt = Table(ded_rows, colWidths=[70*mm,65*mm,35*mm])
    dt.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),BLUE),('LINEBELOW',(0,0),(-1,0),1.5,WHITE),
        ('BACKGROUND',(0,1),(-1,-1),WHITE),('LINEBELOW',(0,1),(-1,-2),0.5,GREY_LINE),
        ('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7),
        ('LEFTPADDING',(0,0),(-1,-1),10),('RIGHTPADDING',(0,0),(-1,-1),10),
    ]))
    story.append(dt)
    story.append(Spacer(1,4*mm))

    # Take home
    th_row = Table([[Paragraph(
        f'<b>Estimated Monthly Take-Home: ₹{fmt_indian(take_home)}</b>',
        ps('thv',font='Helvetica-Bold',size=12,color=WHITE,bold=True,align=TA_CENTER)
    )]], colWidths=['100%'])
    th_row.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1),GREEN),
        ('TOPPADDING',(0,0),(-1,-1),10),('BOTTOMPADDING',(0,0),(-1,-1),10),
    ]))
    story.append(th_row)
    story.append(Spacer(1,5*mm))

    # Commission note
    if comm_type != 'none' and annual_comm > 0:
        fl = {'monthly':'monthly','bimonthly':'bi-monthly','quarterly':'quarterly','annual':'annual'}[comm_type]
        inc = comm_type in ('monthly','bimonthly')
        note_text = (f'Commission of ₹{fmt_indian(annual_comm)}/yr paid {fl}. '
                     f'{"Included in ESIC wage calculation." if inc else "Excluded from ESIC, PF and NPS calculations."} '
                     f'Commission is subject to income tax.')
        cn = Table([[Paragraph(f'<b>Commission Note:</b> {note_text}',
                               ps('cnn',size=9,color=NAVY))]], colWidths=['100%'])
        cn.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,-1),AMBER_BG),
            ('LINELEFT',(0,0),(0,-1),3,AMBER),
            ('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8),
            ('LEFTPADDING',(0,0),(-1,-1),12),
        ]))
        story.append(cn)
        story.append(Spacer(1,4*mm))

    # Notes
    story.append(Paragraph('NOTE', s_sub))
    story.append(HRFlowable(width='100%', thickness=1, color=BLUE, spaceAfter=4))
    for note in [
        'Gratuity is applicable as per the Payment of Gratuity Act, 1972.',
        'In addition to this, the company provides Health Insurance of Rs.300,000 coverage for self, spouse, and 2 children.',
        'As a part of your total benefits package, you will also be covered under Group Accidental Insurance (3x CTC) and Group Term Life Insurance (2x CTC).',
    ]:
        story.append(Paragraph(f'• {note}', s_normal))
    story.append(Spacer(1,4*mm))

    # Bonus
    story.append(Paragraph('BONUS', s_sub))
    story.append(HRFlowable(width='100%', thickness=1, color=BLUE, spaceAfter=4))
    for bp in [
        f'In addition to the above fixed CTC, you will be eligible for an annual bonus of {int(bonus_pct)}%.',
        'Details of the AIP Bonus program will be provided with your Appointment Letter.',
        "To qualify for the bonus, you must be an active employee on the company's payroll at the time of payout.",
        'This bonus will be treated as taxable income, and applicable payroll taxes will be withheld.',
    ]:
        story.append(Paragraph(f'• {bp}', s_normal))
    story.append(Spacer(1,4*mm))

    # Disclaimer
    disc = Table([[Paragraph(
        'This document is indicative only. Structure: Basic = 50% CTC, HRA = 40% Basic, LTA = CTC/12, CCA = remainder. '
        'PF capped at ₹15,000 wage. Tax estimate uses new regime FY2025-26 with standard deduction ₹50,000 only — '
        'excludes surcharge, cess and personal deductions. Verify all figures with India payroll team before issuing formal offers.',
        ps('disc',size=8,color=GREY_TEXT))]], colWidths=['100%'])
    disc.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1),BLUE_LIGHT),
        ('LINEALL',(0,0),(-1,-1),0.5,GREY_LINE),
        ('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8),
        ('LEFTPADDING',(0,0),(-1,-1),10),
    ]))
    story.append(disc)

    def footer(canvas, doc):
        canvas.saveState()
        w, h = A4
        canvas.setFillColor(NAVY)
        canvas.rect(0, 0, w, 18*mm, fill=1, stroke=0)
        canvas.setFillColor(WHITE)
        canvas.setFont('Helvetica-Bold', 11)
        canvas.drawString(20*mm, 7*mm, 'SOVOS')
        canvas.setFont('Helvetica', 8)
        canvas.drawCentredString(w/2, 7*mm, '© Sovos 2025. Proprietary and Confidential.')
        canvas.drawRightString(w - 20*mm, 7*mm, f'Page {doc.page}')
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    buf.seek(0)
    return buf

def ps_p(text, style):
    return Paragraph(f'<b>{text}</b>', style)

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/generate', methods=['POST'])
def generate():
    try:
        data = request.json
        buf = generate_pdf_bytes(data)
        name = data.get('name', 'Candidate').replace(' ', '_')
        return send_file(buf, mimetype='application/pdf',
                         as_attachment=True,
                         download_name=f'Sovos_CTC_Annex_{name}.pdf')
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/preview', methods=['POST'])
def preview():
    """Returns calculated breakdown as JSON for live preview"""
    try:
        data = request.json
        ctc         = float(data['ctc'])
        mode        = data.get('mode','auto')
        comm_type   = data.get('comm_type','none')
        comm_amount = float(data.get('comm_amount', 0))
        comm_pct    = data.get('comm_pct', False)
        nps_rate    = float(data.get('nps_rate', 15))

        annual_comm = (comm_amount/100*ctc) if comm_pct else comm_amount
        if comm_type == 'none': annual_comm = 0
        periods = {'monthly':12,'bimonthly':6,'quarterly':4,'annual':1}.get(comm_type,1)
        comm_pp = annual_comm/periods if comm_type!='none' else 0
        comm_inc_esic = comm_type in ('monthly','bimonthly')
        monthly_comm_esic = (comm_pp if comm_type=='monthly' else comm_pp/2) if comm_inc_esic else 0

        resolved = resolve_mode(ctc, mode, monthly_comm_esic, nps_rate)
        include_nps = (resolved == 'nps')
        sal = compute_salary(ctc, nps_rate, include_nps)

        gross_esic = sal['sub']/12 + monthly_comm_esic
        esic_elig  = gross_esic <= 21000
        esic_emp_m = gross_esic*0.0325 if esic_elig else 0
        esic_ee_m  = gross_esic*0.0075 if esic_elig else 0

        taxable = max(0, sal['sub'] - sal['pf_ee_a'] - 50000)
        tax = 0
        if taxable > 1500000:      tax=(taxable-1500000)*0.30+187500
        elif taxable > 1200000:    tax=(taxable-1200000)*0.20+127500
        elif taxable > 900000:     tax=(taxable-900000)*0.15+82500
        elif taxable > 600000:     tax=(taxable-600000)*0.10+52500
        elif taxable > 300000:     tax=(taxable-300000)*0.05
        tax_m = tax/12
        take_home = sal['sub']/12 - sal['pf_ee_m'] - esic_ee_m - tax_m

        return jsonify({
            'resolved_mode': resolved,
            'esic_eligible': esic_elig,
            'annual_comm': annual_comm,
            'comm_included_esic': comm_inc_esic,
            'sal': {k: round(v) for k,v in sal.items()},
            'esic_emp_m': round(esic_emp_m),
            'esic_ee_m': round(esic_ee_m),
            'take_home': round(take_home),
            'tax_m': round(tax_m),
            'gross_monthly_esic': round(gross_esic),
            'fixed': {
                'travel': TRAVEL, 'medical': MEDICAL,
                'mobile': MOBILE, 'education': EDUCATION, 'food': FOOD
            }
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── HTML TEMPLATE ────────────────────────────────────────────────────────────
HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Sovos India CTC Calculator</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700;800&family=Inter:wght@300;400;500;600&display=swap');
:root{--bg:#f4fcff;--surface:#fff;--surface2:#f4fcff;--border:#e0e0e0;--border2:#c8dff0;--text:#0a0e33;--muted:#666;--muted2:#999;--blue:#0078d6;--blue-deep:#0053a4;--blue-pale:#e8f9ff;--navy:#0a0e33;--green:#00641f;--green-pale:#e8ffe8;--amber:#fa8f2d;--amber-pale:#fff7f0;--purple:#8700a0;--red:#c35514;}
*{box-sizing:border-box;margin:0;padding:0;}
body{font-family:'Inter',sans-serif;background:var(--bg);color:var(--text);min-height:100vh;}
.header{background:var(--navy);padding:14px 28px;display:flex;align-items:center;justify-content:space-between;}
.logo{font-family:'Outfit',sans-serif;font-size:20px;font-weight:800;color:#fff;}
.header-sub{font-size:10px;color:rgba(255,255,255,.45);letter-spacing:.08em;text-transform:uppercase;margin-top:2px;}
.header-btns{display:flex;gap:10px;}
.btn{border:none;border-radius:8px;padding:10px 20px;font-family:'Outfit',sans-serif;font-size:13px;font-weight:700;cursor:pointer;transition:all .15s;}
.btn-calc{background:var(--blue);color:#fff;}
.btn-calc:hover{background:var(--blue-deep);}
.btn-pdf{background:var(--green);color:#fff;}
.btn-pdf:hover{background:#00861e;}
.btn-pdf:disabled{background:#ccc;cursor:not-allowed;}
.layout{display:grid;grid-template-columns:310px 1fr;height:calc(100vh - 63px);}
.input-panel{background:var(--surface);border-right:1px solid var(--border);padding:20px 16px;overflow-y:auto;display:flex;flex-direction:column;gap:18px;}
.section-head{font-family:'Outfit',sans-serif;font-size:11px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--blue);padding-bottom:8px;border-bottom:2px solid var(--blue-pale);margin-bottom:2px;}
.field{margin-bottom:10px;}
.field:last-child{margin-bottom:0;}
label{display:block;font-size:10px;font-weight:600;color:var(--muted);margin-bottom:4px;letter-spacing:.04em;text-transform:uppercase;}
input[type=text],input[type=number]{width:100%;background:var(--surface2);border:1px solid var(--border2);border-radius:7px;padding:8px 11px;font-family:'Inter',sans-serif;font-size:13px;color:var(--text);outline:none;transition:border-color .15s;}
input:focus{border-color:var(--blue);box-shadow:0 0 0 3px rgba(0,120,214,.1);}
input::placeholder{color:#ccc;}
.hint{font-size:10px;color:var(--muted2);margin-top:3px;line-height:1.5;}
.toggle-row{display:flex;gap:4px;flex-wrap:wrap;margin-bottom:5px;}
.toggle-btn{flex:1;min-width:48px;padding:6px 4px;background:var(--surface2);border:1px solid var(--border2);border-radius:6px;font-family:'Outfit',sans-serif;font-size:11px;font-weight:600;color:var(--muted);cursor:pointer;text-align:center;transition:all .15s;}
.toggle-btn.active{background:rgba(0,120,214,.1);border-color:var(--blue);color:var(--blue);}
.cond{display:none;}
.cond.on{display:block;}
.output-panel{overflow-y:auto;padding:22px 24px;}
.empty{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;gap:10px;opacity:.4;}
.empty .icon{font-size:40px;}
.empty p{font-size:12px;color:var(--muted2);}
.results{display:none;}
.results.on{display:block;}
.mode-badge{border-radius:10px;padding:12px 16px;margin-bottom:16px;display:flex;align-items:center;gap:12px;}
.mode-badge.esic{background:var(--green-pale);border:1px solid #b6ffa0;}
.mode-badge.no-esic{background:var(--amber-pale);border:1px solid #ffd7a5;}
.mode-badge.nps{background:#fdf0ff;border:1px solid #f0beff;}
.mdot{width:9px;height:9px;border-radius:50%;}
.esic .mdot{background:#00861e;}
.no-esic .mdot{background:var(--amber);}
.nps .mdot{background:var(--purple);}
.mode-badge h3{font-family:'Outfit',sans-serif;font-size:13px;font-weight:700;}
.esic h3{color:var(--green);}
.no-esic h3{color:var(--red);}
.nps h3{color:var(--purple);}
.mode-badge p{font-size:11px;color:var(--muted);margin-top:1px;}
.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:16px;}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:12px 14px;}
.card.accent{background:var(--blue-pale);border-color:rgba(0,120,214,.3);}
.card-label{font-size:9px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:4px;font-weight:600;}
.card-val{font-family:'Outfit',sans-serif;font-size:19px;font-weight:700;color:var(--text);}
.card.accent .card-val{color:var(--blue);}
.card-sub{font-size:10px;color:var(--muted2);margin-top:2px;}
.comm-note{border-radius:8px;padding:10px 14px;margin-bottom:16px;font-size:12px;line-height:1.6;border-left:3px solid var(--amber);background:var(--amber-pale);color:#7c4a00;}
.tbl-wrap{background:var(--surface);border:1px solid var(--border);border-radius:10px;overflow:hidden;margin-bottom:16px;}
.tbl-wrap table{width:100%;border-collapse:collapse;}
.tbl-wrap th{background:var(--blue);padding:9px 13px;font-family:'Outfit',sans-serif;font-size:9px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#fff;border-bottom:1.5px solid #fff;}
.tbl-wrap th.r{text-align:right;}
.tbl-wrap td{padding:8px 13px;border-bottom:.75px solid var(--border);font-size:12px;color:var(--muted);}
.tbl-wrap td.r{text-align:right;font-family:'Inter',monospace;color:var(--text);font-weight:500;}
.tbl-wrap tr.sub td{background:var(--blue-pale);font-weight:700;color:var(--text);}
.tbl-wrap tr.sub td.r{color:var(--blue);}
.tbl-wrap tr.emp td{background:#fafafa;}
.tbl-wrap tr.emp td.r{color:var(--blue);}
.tbl-wrap tr.tot td{background:var(--navy);color:#fff!important;font-weight:700;font-size:13px;border-top:2px solid var(--blue);}
.tbl-wrap td.green{color:var(--green)!important;}
.tbl-wrap td.amber{color:var(--amber)!important;}
.tbl-wrap td.muted{color:#ccc!important;}
.ded-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:16px;}
.ded-card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:12px 13px;}
.ded-title{font-family:'Outfit',sans-serif;font-size:9px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;margin-bottom:3px;}
.ded-who{font-size:10px;color:var(--muted2);margin-bottom:6px;}
.ded-val{font-family:'Outfit',sans-serif;font-size:15px;font-weight:700;}
.ded-annual{font-size:10px;color:var(--muted2);margin-top:2px;}
.ded-na{font-size:11px;color:#ccc;font-style:italic;margin-top:5px;}
.takehome{background:var(--navy);border-radius:12px;padding:16px 20px;margin-bottom:16px;display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;}
.th-label{font-size:9px;letter-spacing:.1em;text-transform:uppercase;color:rgba(255,255,255,.45);margin-bottom:4px;font-weight:600;}
.th-val{font-family:'Outfit',sans-serif;font-size:20px;font-weight:700;color:#fff;}
.th-val.red{color:#ffd7a5;}
.th-sub{font-size:10px;color:rgba(255,255,255,.35);margin-top:2px;}
.footnote{font-size:10px;color:var(--muted2);padding:11px 14px;background:var(--surface);border:1px solid var(--border);border-radius:8px;line-height:1.7;}
.loading{text-align:center;padding:20px;color:var(--muted);font-size:13px;}
@media(max-width:880px){.layout{grid-template-columns:1fr;height:auto;}.input-panel{border-right:none;border-bottom:1px solid var(--border);}.cards,.takehome,.ded-grid{grid-template-columns:1fr 1fr;}}
</style>
</head>
<body>
<div class="header">
  <div><div class="logo">SOVOS</div><div class="header-sub">India CTC Calculator · ESIC · PF · NPS · Commission</div></div>
  <div class="header-btns">
    <button class="btn btn-calc" onclick="doCalc()">Calculate →</button>
    <button class="btn btn-pdf" id="pdfBtn" onclick="doPDF()" disabled>⬇ Download PDF</button>
  </div>
</div>
<div class="layout">
  <div class="input-panel">
    <div>
      <div class="section-head">01 — Candidate</div>
      <div class="field"><label>Full Name</label><input type="text" id="name" placeholder="e.g. Priya Sharma"/></div>
      <div class="field"><label>Job Title / Role</label><input type="text" id="role" placeholder="e.g. Partner Account Manager"/></div>
      <div class="field"><label>Date</label><input type="text" id="date" placeholder="e.g. 01 March 2026"/></div>
    </div>
    <div>
      <div class="section-head">02 — CTC</div>
      <div class="field"><label>Annual CTC (₹)</label><input type="number" id="ctc" placeholder="e.g. 850000" min="0"/></div>
    </div>
    <div>
      <div class="section-head">03 — Structure</div>
      <div class="field">
        <label>Type</label>
        <div class="toggle-row" id="modeT">
          <button class="toggle-btn active" onclick="setMode('auto',this)">Auto</button>
          <button class="toggle-btn" onclick="setMode('esic',this)">With ESIC</button>
          <button class="toggle-btn" onclick="setMode('no-esic',this)">No ESIC</button>
          <button class="toggle-btn" onclick="setMode('nps',this)">With NPS</button>
        </div>
        <div class="hint" id="modeH">Auto-detects ESIC eligibility from gross vs ₹21,000</div>
      </div>
      <div class="cond" id="npsF">
        <div class="field"><label>NPS Rate</label>
          <div class="toggle-row">
            <button class="toggle-btn active" onclick="setNPS(15,this)">15%</button>
            <button class="toggle-btn" onclick="setNPS(10,this)">10%</button>
            <button class="toggle-btn" onclick="setNPS(14,this)">14%</button>
          </div>
        </div>
      </div>
    </div>
    <div>
      <div class="section-head">04 — Commission</div>
      <div class="field">
        <label>Frequency</label>
        <div class="toggle-row" id="commT">
          <button class="toggle-btn active" onclick="setCT('none',this)">None</button>
          <button class="toggle-btn" onclick="setCT('monthly',this)">Monthly</button>
          <button class="toggle-btn" onclick="setCT('bimonthly',this)">Bi-mo</button>
          <button class="toggle-btn" onclick="setCT('quarterly',this)">Quarterly</button>
          <button class="toggle-btn" onclick="setCT('annual',this)">Annual</button>
        </div>
        <div class="hint" id="commH">No variable pay</div>
      </div>
      <div class="cond" id="commF">
        <div class="field"><label>Input as</label>
          <div class="toggle-row">
            <button class="toggle-btn active" onclick="setCM('amount',this)">Fixed ₹</button>
            <button class="toggle-btn" onclick="setCM('percent',this)">% of CTC</button>
          </div>
        </div>
        <div class="field"><label>Annual Commission</label>
          <input type="number" id="commA" placeholder="e.g. 100000" min="0"/>
          <div class="hint" id="commAH">Total annual commission (₹)</div>
        </div>
      </div>
    </div>
    <div>
      <div class="section-head">05 — Bonus</div>
      <div class="field"><label>Bonus % (for PDF)</label><input type="number" id="bonusPct" value="8" min="0" max="100"/><div class="hint">Annual bonus % shown in PDF notes</div></div>
    </div>
  </div>

  <div class="output-panel">
    <div class="empty" id="emp"><div class="icon">📊</div><p>Enter CTC and click Calculate</p></div>
    <div class="results" id="res">
      <div id="badge"></div>
      <div class="cards" id="cards"></div>
      <div id="cnote"></div>
      <div class="tbl-wrap" id="tbl"></div>
      <div class="ded-grid" id="ded"></div>
      <div class="takehome" id="th"></div>
      <div class="footnote">⚠ Structure: Basic = 50% CTC, HRA = 40% Basic, LTA = CTC÷12, CCA = remainder. PF capped at ₹15,000 wage. Tax estimate uses new regime FY2025-26 with ₹50,000 standard deduction only. Verify with India payroll team (Nisha) before issuing formal offers.</div>
    </div>
  </div>
</div>
<script>
let mode='auto', ct='none', cm='amount', npsRate=15, lastData=null;
function setMode(v,b){mode=v;document.querySelectorAll('#modeT .toggle-btn').forEach(x=>x.classList.remove('active'));b.classList.add('active');
  const h={auto:'Auto-detects ESIC from gross vs ₹21,000',esic:'Force ESIC structure','no-esic':'Force No-ESIC structure',nps:'Force NPS structure'};
  document.getElementById('modeH').textContent=h[v];
  document.getElementById('npsF').classList.toggle('on',v==='nps'||v==='auto');}
function setNPS(r,b){npsRate=r;document.querySelectorAll('[onclick^="setNPS"]').forEach(x=>x.classList.remove('active'));b.classList.add('active');}
function setCT(v,b){ct=v;document.querySelectorAll('#commT .toggle-btn').forEach(x=>x.classList.remove('active'));b.classList.add('active');
  const h={none:'No variable pay',monthly:'Monthly → included in ESIC',bimonthly:'Bi-monthly → included in ESIC',quarterly:'Quarterly → excluded from ESIC',annual:'Annual → excluded from ESIC'};
  document.getElementById('commH').textContent=h[v];document.getElementById('commF').classList.toggle('on',v!=='none');}
function setCM(v,b){cm=v;document.querySelectorAll('[onclick^="setCM"]').forEach(x=>x.classList.remove('active'));b.classList.add('active');
  document.getElementById('commAH').textContent=v==='percent'?'% of CTC (e.g. 20 = 20%)':'Total annual commission (₹)';
  document.getElementById('commA').placeholder=v==='percent'?'e.g. 20':'e.g. 100000';}

function fi(n){n=Math.round(n);if(!n)return'0';let s=String(Math.abs(n));if(s.length>3){let l=s.slice(-3),r=s.slice(0,-3),g=[];while(r.length>2){g.unshift(r.slice(-2));r=r.slice(0,-2);}if(r)g.unshift(r);s=g.join(',')+','+l;}return'₹'+s;}

function payload(){
  return{ctc:parseFloat(document.getElementById('ctc').value)||0,
    name:document.getElementById('name').value||'[Candidate Name]',
    role:document.getElementById('role').value||'[Role Title]',
    date:document.getElementById('date').value||'[Date]',
    mode,comm_type:ct,comm_amount:parseFloat(document.getElementById('commA').value)||0,
    comm_pct:cm==='percent',nps_rate:npsRate,
    bonus_pct:parseFloat(document.getElementById('bonusPct').value)||8};}

async function doCalc(){
  const p=payload();
  if(!p.ctc){alert('Please enter a CTC.');return;}
  document.getElementById('res').classList.remove('on');
  document.getElementById('emp').innerHTML='<div class="icon">⏳</div><p>Calculating...</p>';
  const r=await fetch('/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});
  const d=await r.json();
  if(d.error){alert('Error: '+d.error);return;}
  lastData=p;
  render(p,d);
}

function render(p,d){
  document.getElementById('emp').style.display='none';
  document.getElementById('res').classList.add('on');
  document.getElementById('pdfBtn').disabled=false;

  const mc={esic:{cls:'esic',t:'With ESIC',desc:`Gross ${fi(d.gross_monthly_esic)}/mo — ESIC covered`},
    'no-esic':{cls:'no-esic',t:'ESIC Exempt',desc:`Gross ${fi(d.gross_monthly_esic)}/mo — above ₹21,000`},
    nps:{cls:'nps',t:'With NPS',desc:`NPS employer ${p.nps_rate}% of Basic included in CTC`}}[d.resolved_mode];
  document.getElementById('badge').innerHTML=`<div class="mode-badge ${mc.cls}"><div class="mdot"></div><div><h3>${mc.t}</h3><p>${mc.desc}</p></div></div>`;

  document.getElementById('cards').innerHTML=`
    <div class="card accent"><div class="card-label">Annual CTC</div><div class="card-val">${fi(p.ctc)}</div><div class="card-sub">Total cost to company</div></div>
    <div class="card"><div class="card-label">Monthly Gross</div><div class="card-val">${fi(d.sal.sub/12)}</div><div class="card-sub">Fixed earnings</div></div>
    <div class="card"><div class="card-label">Est. Take-Home</div><div class="card-val">${fi(d.take_home)}</div><div class="card-sub">After PF + ESIC + tax</div></div>`;

  const inc=d.comm_included_esic;
  const fl={monthly:'Monthly',bimonthly:'Bi-monthly',quarterly:'Quarterly',annual:'Annual'}[ct]||'';
  document.getElementById('cnote').innerHTML=(ct!='none'&&d.annual_comm>0)?
    `<div class="comm-note"><strong>Commission (${fl}) — ${fi(d.annual_comm)}/yr:</strong> Paid ${fl.toLowerCase()} → ${inc?'<strong>INCLUDED in ESIC wages</strong>':'<strong>EXCLUDED from ESIC, PF and NPS</strong>'}.</div>`:'';

  const s=d.sal,f=d.fixed,nps=d.resolved_mode==='nps';
  const commRow=ct!='none'&&d.annual_comm>0?`<tr><td>Commission (${fl}) avg</td><td class="r amber">${fi(d.annual_comm/12)}</td><td class="r amber">${fi(d.annual_comm)}</td></tr>`:'';
  document.getElementById('tbl').innerHTML=`<table>
    <thead><tr><th>Earnings</th><th class="r">Monthly</th><th class="r">Annually</th></tr></thead>
    <tbody>
      <tr><td>Basic + DA</td><td class="r">${fi(s.basic/12)}</td><td class="r">${fi(s.basic)}</td></tr>
      <tr><td>HRA</td><td class="r">${fi(s.hra/12)}</td><td class="r">${fi(s.hra)}</td></tr>
      <tr><td>Travelling Allowance</td><td class="r">${fi(f.travel/12)}</td><td class="r">${fi(f.travel)}</td></tr>
      <tr><td>Medical Allowance</td><td class="r">${fi(f.medical/12)}</td><td class="r">${fi(f.medical)}</td></tr>
      <tr><td>Mobile Reimbursement</td><td class="r">${fi(f.mobile/12)}</td><td class="r">${fi(f.mobile)}</td></tr>
      <tr><td>Education Allowance</td><td class="r">${fi(f.education/12)}</td><td class="r">${fi(f.education)}</td></tr>
      <tr><td>Statutory Bonus</td><td class="r muted">—</td><td class="r muted">—</td></tr>
      <tr><td>Leave Travel Allowance</td><td class="r">${fi(s.lta/12)}</td><td class="r">${fi(s.lta)}</td></tr>
      <tr><td>City Compensatory Allowance (CCA)</td><td class="r">${fi(s.cca/12)}</td><td class="r">${fi(s.cca)}</td></tr>
      <tr><td>Food Coupon</td><td class="r">${fi(f.food/12)}</td><td class="r">${fi(f.food)}</td></tr>
      ${commRow}
      <tr class="sub"><td>Sub Total</td><td class="r">${fi(s.sub/12)}</td><td class="r">${fi(s.sub)}</td></tr>
      <tr class="emp"><td>PF – Employer Contribution</td><td class="r green">${fi(s.pf_emp_m)}</td><td class="r green">${fi(s.pf_emp_a)}</td></tr>
      <tr class="emp"><td>ESIC Employer</td><td class="r ${d.esic_eligible?'amber':'muted'}">${d.esic_eligible?fi(d.esic_emp_m):'—'}</td><td class="r ${d.esic_eligible?'amber':'muted'}">${d.esic_eligible?fi(d.esic_emp_m*12):'—'}</td></tr>
      ${nps?`<tr class="emp"><td>NPS – Employer (${p.nps_rate}%)</td><td class="r" style="color:var(--purple)">${fi(s.nps_emp_m)}</td><td class="r" style="color:var(--purple)">${fi(s.nps_emp_a)}</td></tr>`:''}
      <tr class="tot"><td>Total Cost to Company (CTC)</td><td class="r">${fi(p.ctc/12)}</td><td class="r">${fi(p.ctc)}</td></tr>
    </tbody></table>`;

  document.getElementById('ded').innerHTML=`
    <div class="ded-card"><div class="ded-title" style="color:var(--green)">PF — Employee</div><div class="ded-who">12% Basic (≤ ₹15K wage)</div><div class="ded-val" style="color:var(--green)">${fi(s.pf_ee_m)}<span style="font-size:10px;color:var(--muted2)">/mo</span></div><div class="ded-annual">${fi(s.pf_ee_a)}/yr</div></div>
    <div class="ded-card"><div class="ded-title" style="color:var(--blue)">PF — Employer</div><div class="ded-who">12% Basic — in CTC</div><div class="ded-val" style="color:var(--blue)">${fi(s.pf_emp_m)}<span style="font-size:10px;color:var(--muted2)">/mo</span></div><div class="ded-annual">${fi(s.pf_emp_a)}/yr</div></div>
    <div class="ded-card"><div class="ded-title" style="color:${d.esic_eligible?'var(--green)':'var(--muted2)'}">ESIC — Employee</div><div class="ded-who">0.75% gross wages</div>${d.esic_eligible?`<div class="ded-val" style="color:var(--green)">${fi(d.esic_ee_m)}<span style="font-size:10px;color:var(--muted2)">/mo</span></div><div class="ded-annual">${fi(d.esic_ee_m*12)}/yr</div>`:`<div class="ded-na">Gross > ₹21K — exempt</div>`}</div>
    <div class="ded-card"><div class="ded-title" style="color:${d.esic_eligible?'var(--amber)':'var(--muted2)'}">ESIC — Employer</div><div class="ded-who">3.25% — additional cost</div>${d.esic_eligible?`<div class="ded-val" style="color:var(--amber)">${fi(d.esic_emp_m)}<span style="font-size:10px;color:var(--muted2)">/mo</span></div><div class="ded-annual">${fi(d.esic_emp_m*12)}/yr</div>`:`<div class="ded-na">No ESIC cost</div>`}</div>
    <div class="ded-card"><div class="ded-title" style="color:${nps?'var(--purple)':'var(--muted2)'}">NPS — Employer</div><div class="ded-who">${p.nps_rate}% of Basic — in CTC</div>${nps?`<div class="ded-val" style="color:var(--purple)">${fi(s.nps_emp_m)}<span style="font-size:10px;color:var(--muted2)">/mo</span></div><div class="ded-annual">${fi(s.nps_emp_a)}/yr</div>`:`<div class="ded-na">Not selected</div>`}</div>
    <div class="ded-card"><div class="ded-title" style="color:var(--muted)">Total Employer Cost</div><div class="ded-who">PF + NPS + ESIC employer</div><div class="ded-val" style="color:var(--text)">${fi(s.pf_emp_m+s.nps_emp_m+d.esic_emp_m)}<span style="font-size:10px;color:var(--muted2)">/mo</span></div><div class="ded-annual">${fi(s.pf_emp_a+s.nps_emp_a+d.esic_emp_m*12)}/yr</div></div>`;

  document.getElementById('th').innerHTML=`
    <div><div class="th-label">Est. Monthly Take-Home</div><div class="th-val">${fi(d.take_home)}</div><div class="th-sub">After all deductions</div></div>
    <div><div class="th-label">Total Deductions / month</div><div class="th-val red">${fi(s.pf_ee_m+d.esic_ee_m+d.tax_m)}</div><div class="th-sub">PF + ESIC + est. tax</div></div>
    <div><div class="th-label">Annual Take-Home (est.)</div><div class="th-val">${fi(d.take_home*12)}</div><div class="th-sub">Indicative only</div></div>`;}

async function doPDF(){
  if(!lastData)return;
  const btn=document.getElementById('pdfBtn');
  btn.disabled=true;btn.textContent='Generating...';
  try{
    const r=await fetch('/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload())});
    if(!r.ok){const e=await r.json();alert('Error: '+e.error);return;}
    const blob=await r.blob();
    const url=URL.createObjectURL(blob);
    const a=document.createElement('a');
    a.href=url;
    const name=document.getElementById('name').value.replace(/\s+/g,'_')||'Candidate';
    a.download=`Sovos_CTC_Annex_${name}.pdf`;
    a.click();URL.revokeObjectURL(url);
  }finally{btn.disabled=false;btn.textContent='⬇ Download PDF';}
}
</script>
</body>
</html>'''

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
