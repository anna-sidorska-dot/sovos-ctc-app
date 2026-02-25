# Sovos India CTC Calculator

A web app for generating Sovos-branded CTC breakdown PDFs for India offers.
Handles ESIC, PF, NPS, and all commission types.

---

## What it does

- Enter candidate name, role, CTC, commission structure
- Live preview of full salary breakdown
- Download a Sovos-branded PDF (Annex 1 format) ready to attach to offer letters

---

## Deploy on Render (recommended — free)

1. Create a free account at https://render.com
2. Click **New → Web Service**
3. Connect your GitHub repo (upload this folder first)
4. Set these values:
   - **Runtime:** Python 3
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `gunicorn app:app`
5. Click **Deploy**
6. Render gives you a public URL — share with your team

---

## Deploy on Railway (alternative — free)

1. Create account at https://railway.app
2. Click **New Project → Deploy from GitHub**
3. Connect this repo
4. Railway auto-detects Python and deploys
5. Go to Settings → Networking → Generate Domain
6. Share the URL

---

## Deploy on Azure (if Sovos IT prefers)

1. Install Azure CLI
2. Run:
   ```
   az webapp up --name sovos-ctc-calculator --runtime PYTHON:3.11
   ```
3. Azure will deploy and give you a URL like:
   `https://sovos-ctc-calculator.azurewebsites.net`

---

## Run locally (for testing)

```bash
pip install -r requirements.txt
python app.py
```
Then open http://localhost:5000

---

## Files

- `app.py` — main app (Flask backend + HTML frontend)
- `requirements.txt` — Python dependencies
- `Procfile` — tells Render/Railway how to start the app

---

## Notes

- No database needed — stateless app
- PDF generated on the server, downloaded instantly
- Salary structure matches Sovos India template:
  - Basic = 50% CTC
  - HRA = 40% of Basic
  - LTA = CTC ÷ 12
  - CCA = remainder after all other components
  - PF capped at ₹15,000 wage ceiling
- Tax estimate uses new regime FY2025-26 only — not a substitute for payroll advice
- Verify all figures with Nisha / India payroll team before issuing formal offers
