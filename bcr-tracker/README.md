## Local Development

Run locally to avoid copy-pasting to Snowsight on every change.

### One-time setup

```bash
cd /Users/hbarile/Dev/dev/profiles/snowhouse/wa-assessments/THE_HARTFORD/CASES-BCR-TRACKING/bcr_tracker_app

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Run

Your demo account connection is `hbtraining`. Run:

```bash
source .venv/bin/activate
BCR_CONNECTION=hbtraining streamlit run streamlit_app.py
```

App opens at http://localhost:8501

To use a different account, set `BCR_CONNECTION` to any connection name from `cortex connections list`:
- `hbtraining` — SFSENORTHAMERICA-HBTRAINING (demo account, BCR_TRACKER_DB lives here)
- `hol` — CRB06861
- `tokyo-hyrbid` — SFSENORTHAMERICA-HBTOKYO

### Deploy to Snowsight when ready

1. Snowsight → Projects → Streamlit → your app → open editor
2. Paste `streamlit_app.py` contents → Run

No other files needed — `requirements.txt` is only for local dev.

---

## Parser changes (v2.1)

The MDX source structure is now confirmed from a live fetch:

**Dates** — numbered list in Bundle history section:
```
1. Introduced in the 10.12 release (April 2026) as Disabled by Default   → DBD
2. Status changed in the 10.17 release (May 8-14, 2026) → EBD
3. Status planned to change in June 2026 to Generally Enabled             → GE
```

**BCR rows** — empty link text, impact in col2:
```
<td>[](/release-notes/bcr-bundles/2026_03/bcr-2290)</td>
<td>Low</td>
```

**Category rows** — bold text:
```
<td>**Security Changes**</td>
<td>**Impact Score**</td>
```

**Titles** — from individual BCR page markdown H1: `# Title here`
