from flask import Flask, request, jsonify, send_file, render_template_string
import io, math
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

app = Flask(__name__)

# ── BRAND COLORS ──
NAVY      = colors.HexColor('#0A0E33')
WHITE     = colors.HexColor('#FFFFFF')
BLUE      = colors.HexColor('#0078D6')
BLUE_PALE = colors.HexColor('#E8F9FF')
GREY_LINE = colors.HexColor('#E0E0E0')
GREY_TEXT = colors.HexColor('#666666')
GREEN     = colors.HexColor('#00641F')
AMBER     = colors.HexColor('#FA8F2D')
AMBER_BG  = colors.HexColor('#FFF7F0')

# ── FIXED ALLOWANCES ──
TRAVEL_PF   = 19600   # With PF structures
TRAVEL_NOPF = 19200   # Without PF structures
MEDICAL = 15000
MOBILE  = 12000
EDUCATION = 2400
FOOD    = 15600

def fmt_in(n):
    n = int(round(n))
    if n == 0: return "0"
    s = str(abs(n))
    if len(s) > 3:
        last3 = s[-3:]; rest = s[:-3]; groups = []
        while len(rest) > 2: groups.append(rest[-2:]); rest = rest[:-2]
        if rest: groups.append(rest)
        groups.reverse()
        s = ','.join(groups) + ',' + last3
    return s

def compute_salary(ctc, pf_included=True, nps_rate=0):
    basic = ctc * 0.50

    if not pf_included:
        # WITHOUT PF: HRA=50% basic, Travel=19200, LTA always present
        hra = basic * 0.50
        travel = TRAVEL_NOPF
        lta = round(ctc / 12)
        nps_emp_a = (basic/12) * (nps_rate/100) * 12 if nps_rate > 0 else 0
        fixed = basic + hra + travel + MEDICAL + MOBILE + EDUCATION + FOOD + lta
        cca = max(0, ctc - fixed - nps_emp_a)
        sub = basic + hra + travel + MEDICAL + MOBILE + EDUCATION + lta + cca + FOOD
        return dict(basic=basic, hra=hra, travel=travel, medical=MEDICAL, mobile=MOBILE,
                    education=EDUCATION, food=FOOD, stat_bonus=0, lta=lta, cca=cca,
                    pf_emp_m=0, pf_emp_a=0, pf_ee_m=0, pf_ee_a=0,
                    nps_emp_m=nps_emp_a/12, nps_emp_a=nps_emp_a,
                    esic_elig=False, esic_emp_m=0, esic_ee_m=0, sub=sub,
                    structure='nopf_nps' if nps_rate > 0 else 'nopf')

    # WITH PF
    pf_wage = min(basic/12, 15000)
    pf_emp_a = pf_wage * 0.12 * 12
    pf_ee_a  = pf_wage * 0.12 * 12
    nps_emp_a = (basic/12) * (nps_rate/100) * 12 if nps_rate > 0 else 0

    # ESIC structure (CTC <= 379,000)
    if ctc <= 379000:
        hra = basic * 0.05
        stat_bonus = round(basic * 8.33 / 100)
        gross_m = (basic + hra + stat_bonus) / 12
        esic_elig = gross_m <= 21000
        esic_emp_m = gross_m * 0.0325 if esic_elig else 0
        esic_ee_m  = gross_m * 0.0075 if esic_elig else 0
        cca = max(0, ctc - (basic+hra+stat_bonus) - pf_emp_a - esic_emp_m*12)
        sub = basic + hra + stat_bonus + cca
        return dict(basic=basic, hra=hra, travel=0, medical=0, mobile=0,
                    education=0, food=0, stat_bonus=stat_bonus, lta=0, cca=cca,
                    pf_emp_m=pf_emp_a/12, pf_emp_a=pf_emp_a, pf_ee_m=pf_ee_a/12, pf_ee_a=pf_ee_a,
                    nps_emp_m=0, nps_emp_a=0,
                    esic_elig=esic_elig, esic_emp_m=esic_emp_m, esic_ee_m=esic_ee_m, sub=sub,
                    structure='esic')

    # Standard with PF (> 379K)
    hra = basic * 0.40
    travel = TRAVEL_PF
    lta = round(ctc/12) if ctc > 700000 else 0
    fixed = basic + hra + travel + MEDICAL + MOBILE + EDUCATION + FOOD + lta
    cca = max(0, ctc - fixed - pf_emp_a - nps_emp_a)
    sub = basic + hra + travel + MEDICAL + MOBILE + EDUCATION + lta + cca + FOOD
    return dict(basic=basic, hra=hra, travel=travel, medical=MEDICAL, mobile=MOBILE,
                education=EDUCATION, food=FOOD, stat_bonus=0, lta=lta, cca=cca,
                pf_emp_m=pf_emp_a/12, pf_emp_a=pf_emp_a, pf_ee_m=pf_ee_a/12, pf_ee_a=pf_ee_a,
                nps_emp_m=nps_emp_a/12, nps_emp_a=nps_emp_a,
                esic_elig=False, esic_emp_m=0, esic_ee_m=0, sub=sub,
                structure='pf_nps' if nps_rate > 0 else 'pf')

def structure_label(sc):
    return {'esic':'With ESIC','pf':'Without ESIC','pf_nps':'Without ESIC + NPS',
            'nopf':'Without PF','nopf_nps':'Without PF + NPS'}.get(sc,'Standard')

def generate_pdf_bytes(data):
    ctc         = float(data['ctc'])
    name        = data.get('name','[Candidate Name]')
    role        = data.get('role','[Role Title]')
    date_str    = data.get('date','[Date]')
    pf_included = data.get('pf_included', True)
    nps_rate    = float(data.get('nps_rate', 0))
    comm_type   = data.get('comm_type','none')
    comm_amount = float(data.get('comm_amount', 0))
    comm_pct    = data.get('comm_pct', False)
    bonus_pct   = float(data.get('bonus_pct', 8))

    annual_comm = (comm_amount/100*ctc) if comm_pct else comm_amount
    if comm_type == 'none': annual_comm = 0
    periods = {'monthly':12,'bimonthly':6,'quarterly':4,'annual':1}.get(comm_type,1)
    comm_inc_esic = comm_type in ('monthly','bimonthly')

    sal = compute_salary(ctc, pf_included, nps_rate)
    sc  = sal['structure']

    # Tax estimate
    taxable = max(0, sal['sub'] - sal['pf_ee_a'] - 50000)
    tax = 0
    if taxable > 1500000:      tax = (taxable-1500000)*0.30+187500
    elif taxable > 1200000:    tax = (taxable-1200000)*0.20+127500
    elif taxable > 900000:     tax = (taxable-900000)*0.15+82500
    elif taxable > 600000:     tax = (taxable-600000)*0.10+52500
    elif taxable > 300000:     tax = (taxable-300000)*0.05
    tax_m = tax/12
    take_home = sal['sub']/12 - sal['pf_ee_m'] - sal['esic_ee_m'] - tax_m

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=20*mm, rightMargin=20*mm,
                            topMargin=15*mm, bottomMargin=25*mm)

    def ps(name, font='Helvetica', size=10, color=colors.black,
           bold=False, align=TA_LEFT, sb=0, sa=4):
        return ParagraphStyle(name, fontName='Helvetica-Bold' if bold else font,
                              fontSize=size, textColor=color, alignment=align,
                              spaceBefore=sb, spaceAfter=sa, leading=size*1.4)

    s_normal = ps('n', color=NAVY, size=10, sa=3)
    s_muted  = ps('m', color=GREY_TEXT, size=9, sa=2)
    s_right  = ps('r', color=NAVY, size=10, align=TA_RIGHT, sa=3)
    s_wht    = ps('w', color=WHITE, size=10, bold=True)
    s_wht_r  = ps('wr', color=WHITE, size=10, bold=True, align=TA_RIGHT)

    story = []
    pw, ph = A4

    # ── HEADER ──
    hdr = Table([[
        Paragraph('<b>SOVOS</b>', ps('logo', size=20, color=WHITE, bold=True)),
        Paragraph('Compensation Annex — India', ps('ht', size=12, color=WHITE, bold=True, align=TA_RIGHT))
    ]], colWidths=['50%','50%'])
    hdr.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1),NAVY),
        ('TOPPADDING',(0,0),(-1,-1),12),('BOTTOMPADDING',(0,0),(-1,-1),12),
        ('LEFTPADDING',(0,0),(0,-1),16),('RIGHTPADDING',(-1,0),(-1,-1),16),
    ]))
    story.append(hdr)
    story.append(Spacer(1,6*mm))

    # ── CANDIDATE INFO ──
    info = Table([
        [Paragraph('<b>Candidate</b>', s_muted), Paragraph(name, ps('nb',color=NAVY,size=10,bold=True,sa=3)),
         Paragraph('<b>Date</b>', s_muted), Paragraph(date_str, s_normal)],
        [Paragraph('<b>Role</b>', s_muted), Paragraph(role, s_normal),
         Paragraph('<b>Structure</b>', s_muted), Paragraph(structure_label(sc), s_normal)],
    ], colWidths=[28*mm,67*mm,25*mm,50*mm])
    info.setStyle(TableStyle([
        ('ROWBACKGROUNDS',(0,0),(-1,-1),[colors.HexColor('#F4FCFF'), WHITE]),
        ('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5),
        ('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),
        ('LINEBELOW',(0,0),(-1,-1),0.5,GREY_LINE),
    ]))
    story.append(info)
    story.append(Spacer(1,5*mm))

    # ── ANNEX TITLE ──
    story.append(Paragraph('ANNEX 1 – CTC BREAKDOWN',
                            ps('at', color=BLUE, size=12, bold=True, sa=2)))
    story.append(HRFlowable(width='100%', thickness=1.5, color=BLUE, spaceAfter=3))
    story.append(Spacer(1,2*mm))

    # ── MAIN TABLE ──
    def row(label, monthly, annual, bold=False, white=False):
        fc = WHITE if white else NAVY
        fn = 'Helvetica-Bold' if bold else 'Helvetica'
        lp = ParagraphStyle('rl', fontName=fn, fontSize=9, textColor=fc)
        rp = ParagraphStyle('rr', fontName=fn, fontSize=9, textColor=fc, alignment=TA_RIGHT)
        mv = fmt_in(monthly) if monthly else ('—' if not bold else '0')
        av = fmt_in(annual)  if annual  else ('—' if not bold else '0')
        return [Paragraph(label, lp), Paragraph(mv, rp), Paragraph(av, rp)]

    s = sal
    if sc == 'esic':
        trows = [
            row('Basic + DA', s['basic']/12, s['basic']),
            row('HRA', s['hra']/12, s['hra']),
            row('Statutory Bonus', s['stat_bonus']/12, s['stat_bonus']),
            row('City Compensatory Allowance (CCA)', s['cca']/12, s['cca']),
        ]
    else:
        fl = {'monthly':'Monthly','bimonthly':'Bi-monthly','quarterly':'Quarterly','annual':'Annual'}.get(comm_type,'')
        trows = [
            row('Basic + DA', s['basic']/12, s['basic']),
            row('HRA', s['hra']/12, s['hra']),
            row('Travelling Allowance', s['travel']/12, s['travel']),
            row('Medical Allowance', s['medical']/12, s['medical']),
            row('Mobile Reimbursement', s['mobile']/12, s['mobile']),
            row('Education Allowance', s['education']/12, s['education']),
            row('Statutory Bonus', 0, 0),
            row('Leave Travel Allowance', s['lta']/12 if s['lta'] else 0, s['lta']),
            row('City Compensatory Allowance (CCA)', s['cca']/12, s['cca']),
            row('Food Coupon', s['food']/12, s['food']),
        ]
        if comm_type != 'none' and annual_comm > 0:
            trows.append(row(f'Commission ({fl})', annual_comm/12, annual_comm))

    sub_idx = len(trows)
    trows.append(row('Sub Total', s['sub']/12, s['sub'], bold=True))
    trows.append(row('PF – Employer Contribution', s['pf_emp_m'], s['pf_emp_a']))
    trows.append(row('ESIC Employer', s['esic_emp_m'] if s['esic_elig'] else 0, s['esic_emp_m']*12 if s['esic_elig'] else 0))
    if s['nps_emp_m']:
        trows.append(row(f'NPS – Employer ({int(nps_rate)}%)', s['nps_emp_m'], s['nps_emp_a']))
    tot_idx = len(trows)
    trows.append(row('TOTAL COST TO COMPANY (CTC)', ctc/12, ctc, bold=True, white=True))

    # Header row
    hp = lambda t: Paragraph(t, ps('th', font='Helvetica-Bold', size=9, color=WHITE, bold=True))
    hpr = lambda t: Paragraph(t, ps('thr', font='Helvetica-Bold', size=9, color=WHITE, bold=True, align=TA_RIGHT))
    full_rows = [[hp('EARNINGS'), hpr('MONTHLY'), hpr('ANNUALLY')]] + trows

    mt = Table(full_rows, colWidths=[95*mm, 37*mm, 38*mm])
    mt.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),BLUE),('LINEBELOW',(0,0),(-1,0),1.5,WHITE),
        ('TOPPADDING',(0,0),(-1,0),9),('BOTTOMPADDING',(0,0),(-1,0),9),
        ('BACKGROUND',(0,1),(-1,-1),WHITE),('LINEBELOW',(0,1),(-1,-2),0.5,GREY_LINE),
        ('TOPPADDING',(0,1),(-1,-1),6),('BOTTOMPADDING',(0,1),(-1,-1),6),
        ('LEFTPADDING',(0,0),(-1,-1),9),('RIGHTPADDING',(0,0),(-1,-1),9),
        ('BACKGROUND',(0,sub_idx+1),(-1,sub_idx+1),colors.HexColor('#E8F9FF')),
        ('LINEABOVE',(0,sub_idx+1),(-1,sub_idx+1),1,BLUE),
        ('BACKGROUND',(0,sub_idx+2),(-1,tot_idx),colors.HexColor('#F8F9FA')),
        ('BACKGROUND',(0,tot_idx+1),(-1,tot_idx+1),NAVY),
        ('LINEABOVE',(0,tot_idx+1),(-1,tot_idx+1),1.5,BLUE),
    ]))
    story.append(mt)
    story.append(Spacer(1,5*mm))

    # ── DEDUCTIONS ──
    story.append(Paragraph('EMPLOYEE DEDUCTIONS (Monthly)',
                            ps('ds', color=BLUE, size=11, bold=True, sa=2)))
    story.append(HRFlowable(width='100%', thickness=1, color=BLUE, spaceAfter=3))
    ded_rows = [
        [hp('Component'), hp('Rate'), hpr('Monthly')],
        [Paragraph('Provident Fund (Employee)', s_normal),
         Paragraph('12% of Basic (≤Rs15,000 wage)' if s['pf_ee_m'] else 'Not applicable', s_normal),
         Paragraph(fmt_in(s['pf_ee_m']) if s['pf_ee_m'] else '0', s_right)],
        [Paragraph('ESIC (Employee)', s_normal),
         Paragraph('0.75% of gross' if s['esic_elig'] else 'Exempt (gross > Rs21,000)', s_normal),
         Paragraph(fmt_in(s['esic_ee_m']) if s['esic_elig'] else '0', s_right)],
        [Paragraph('Estimated Income Tax', s_normal),
         Paragraph('New regime FY2025-26 (indicative)', s_normal),
         Paragraph(fmt_in(tax_m), s_right)],
    ]
    dt = Table(ded_rows, colWidths=[65*mm,75*mm,30*mm])
    dt.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),BLUE),('LINEBELOW',(0,0),(-1,0),1.5,WHITE),
        ('BACKGROUND',(0,1),(-1,-1),WHITE),('LINEBELOW',(0,1),(-1,-2),0.5,GREY_LINE),
        ('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6),
        ('LEFTPADDING',(0,0),(-1,-1),9),('RIGHTPADDING',(0,0),(-1,-1),9),
    ]))
    story.append(dt)
    story.append(Spacer(1,4*mm))

    # ── TAKE HOME ──
    th_t = Table([[Paragraph(
        f'<b>Estimated Monthly Take-Home: Rs {fmt_in(take_home)}</b>',
        ps('thv', font='Helvetica-Bold', size=11, color=WHITE, bold=True, align=TA_CENTER)
    )]], colWidths=['100%'])
    th_t.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1),GREEN),
        ('TOPPADDING',(0,0),(-1,-1),10),('BOTTOMPADDING',(0,0),(-1,-1),10),
    ]))
    story.append(th_t)
    story.append(Spacer(1,5*mm))

    # ── COMMISSION NOTE ──
    if comm_type != 'none' and annual_comm > 0:
        fl = {'monthly':'monthly','bimonthly':'bi-monthly','quarterly':'quarterly','annual':'annual'}.get(comm_type,'')
        inc = comm_type in ('monthly','bimonthly')
        note = (f'Rs{fmt_in(annual_comm)}/yr paid {fl}. '
                f'{"Included in ESIC wage calculation." if inc else "Excluded from ESIC, PF and NPS."} '
                f'Commission is subject to income tax.')
        cn = Table([[Paragraph(f'<b>Commission Note:</b> {note}',
                               ps('cn', size=9, color=NAVY))]], colWidths=['100%'])
        cn.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,-1),AMBER_BG),
            ('LINELEFT',(0,0),(0,-1),3,AMBER),
            ('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8),
            ('LEFTPADDING',(0,0),(-1,-1),12),
        ]))
        story.append(cn)
        story.append(Spacer(1,4*mm))

    # ── NOTE ──
    story.append(Paragraph('NOTE', ps('nh', color=BLUE, size=10, bold=True, sa=2)))
    story.append(HRFlowable(width='100%', thickness=0.5, color=BLUE, spaceAfter=4))
    for note in [
        'Gratuity is applicable as per the Payment of Gratuity Act, 1972.',
        'In addition to this, the company provides Health Insurance of Rs.300,000 coverage for self, spouse, and 2 children.',
        'As a part of your total benefits package, you will also be covered under Group Accidental Insurance (3x CTC) and Group Term Life Insurance (2x CTC).',
    ]:
        story.append(Paragraph(f'• {note}', s_normal))
    story.append(Spacer(1,4*mm))

    # ── BONUS ──
    story.append(Paragraph('BONUS', ps('bh', color=BLUE, size=10, bold=True, sa=2)))
    story.append(HRFlowable(width='100%', thickness=0.5, color=BLUE, spaceAfter=4))
    for bp in [
        f'In addition to the above fixed CTC, you will be eligible for an annual bonus of {int(bonus_pct)}%.',
        'Details of the AIP Bonus program will be provided with your Appointment Letter.',
        "To qualify for the bonus, you must be an active employee on the company's payroll at the time of payout.",
        'This bonus will be treated as taxable income, and applicable payroll taxes will be withheld.',
    ]:
        story.append(Paragraph(f'• {bp}', s_normal))
    story.append(Spacer(1,4*mm))

    # ── DISCLAIMER ──
    disc = ('This document is indicative only. Salary structure follows Sovos India standard template. '
            'PF structures: Basic=50% CTC, HRA=40% Basic, Travel=Rs19,600/yr. Without PF: HRA=50% Basic, Travel=Rs19,200/yr. '
            'LTA=CTC/12 where applicable. PF capped at Rs15,000 wage ceiling. Tax estimate uses new regime FY2025-26 '
            'with Rs50,000 standard deduction only. Verify all figures with the India payroll team (Nisha) before issuing formal offer letters.')
    disc_t = Table([[Paragraph(disc, ps('disc', size=7.5, color=GREY_TEXT))]], colWidths=['100%'])
    disc_t.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#E8F9FF')),
        ('LINEALL',(0,0),(-1,-1),0.3,GREY_LINE),
        ('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8),
        ('LEFTPADDING',(0,0),(-1,-1),10),
    ]))
    story.append(disc_t)

    def footer(canvas, doc):
        canvas.saveState()
        w, h = A4
        canvas.setFillColor(NAVY); canvas.rect(0,0,w,18*mm,fill=1,stroke=0)
        canvas.setFillColor(WHITE); canvas.setFont('Helvetica-Bold',11)
        canvas.drawString(20*mm,7*mm,'SOVOS')
        canvas.setFont('Helvetica',8); canvas.setFillColor(colors.HexColor('#AAAAAA'))
        canvas.drawCentredString(w/2,7*mm,'© Sovos 2025. Proprietary and Confidential.')
        canvas.drawRightString(w-20*mm,7*mm,f'Page {doc.page}')
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    buf.seek(0)
    return buf

@app.route('/')
def index():
    with open('templates/index.html', 'r') as f:
        return f.read()

@app.route('/generate', methods=['POST'])
def generate():
    try:
        data = request.json
        buf = generate_pdf_bytes(data)
        name = data.get('name','Candidate').replace(' ','_')
        return send_file(buf, mimetype='application/pdf',
                         as_attachment=True,
                         download_name=f'Sovos_CTC_Annex_{name}.pdf')
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/preview', methods=['POST'])
def preview():
    try:
        data = request.json
        ctc         = float(data['ctc'])
        pf_included = data.get('pf_included', True)
        nps_rate    = float(data.get('nps_rate', 0))
        comm_type   = data.get('comm_type','none')
        comm_amount = float(data.get('comm_amount', 0))
        comm_pct    = data.get('comm_pct', False)

        annual_comm = (comm_amount/100*ctc) if comm_pct else comm_amount
        if comm_type == 'none': annual_comm = 0
        comm_inc_esic = comm_type in ('monthly','bimonthly')
        periods = {'monthly':12,'bimonthly':6,'quarterly':4,'annual':1}.get(comm_type,1)
        comm_pp = annual_comm/periods if comm_type != 'none' else 0
        monthly_comm_esic = (comm_pp if comm_type=='monthly' else comm_pp/2) if comm_inc_esic else 0

        sal = compute_salary(ctc, pf_included, nps_rate)
        gross_esic = sal['sub']/12 + monthly_comm_esic

        taxable = max(0, sal['sub'] - sal['pf_ee_a'] - 50000)
        tax = 0
        if taxable > 1500000:      tax=(taxable-1500000)*0.30+187500
        elif taxable > 1200000:    tax=(taxable-1200000)*0.20+127500
        elif taxable > 900000:     tax=(taxable-900000)*0.15+82500
        elif taxable > 600000:     tax=(taxable-600000)*0.10+52500
        elif taxable > 300000:     tax=(taxable-300000)*0.05
        tax_m = tax/12
        take_home = sal['sub']/12 - sal['pf_ee_m'] - sal['esic_ee_m'] - tax_m

        return jsonify({
            'sal': {k: round(v) for k,v in sal.items() if isinstance(v,(int,float))},
            'structure': sal['structure'],
            'esic_elig': sal['esic_elig'],
            'annual_comm': round(annual_comm),
            'comm_inc_esic': comm_inc_esic,
            'gross_esic': round(gross_esic),
            'take_home': round(take_home),
            'tax_m': round(tax_m),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)
