-- =====================================================================
-- 02_generator.sql : Python stored procedure that simulates the Fluxx
-- "2DB" export and Salesforce extracts by writing JSON files to the
-- internal stage. Each call = one "feed cycle".
--   CALL BP_DEMO.RAW.GEN_MOCK_FILES(n_new_grants, n_new_opps, update_pct);
-- update_pct = share of n_new_grants emitted as status UPDATES to
-- existing grants (same grant_id, later last_modified) -> dedup demo.
-- =====================================================================
USE SCHEMA BP_DEMO.RAW;

CREATE OR REPLACE PROCEDURE GEN_MOCK_FILES(N_GRANTS INT, N_OPPS INT, UPDATE_PCT FLOAT)
RETURNS VARIANT
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python')
HANDLER = 'run'
COMMENT = 'Writes mock Fluxx grant + Salesforce opportunity JSON files to @LANDING_STAGE'
AS
$$
import io, json, random, datetime as dt

STAGE = '@BP_DEMO.RAW.LANDING_STAGE'

# ---------------------------------------------------------------- reference data
AREAS = {
  "Public Health": {
    "initiatives": ["Tobacco Control", "Road Safety", "Overdose Prevention", "Drowning Prevention",
                    "Maternal & Child Health", "Data for Health", "Healthy Food Policy", "Noncommunicable Disease Prevention"],
    "orgs": ["Global Tobacco Policy Alliance", "Vital Roads Coalition", "Safe Streets Africa", "Harm Reduction Network USA",
             "Coastal Water Safety Trust", "Mothers First Health Initiative", "Civil Registration & Vital Stats Partnership",
             "Healthy Cities Nutrition Lab", "Johns Hopkins Center for Injury Research", "Tobacco-Free Kids Southeast Asia",
             "Andean Public Health Institute", "Recovery Pathways Collaborative"],
    "kpis": ["Lives saved (est.)", "Policies enacted", "Population covered by new laws", "Deaths averted", "Health workers trained"]},
  "Environment": {
    "initiatives": ["Beyond Coal", "Beyond Petrochemicals", "Clean Air Cities", "Ocean Conservation",
                    "Clean Energy Transition", "Climate Finance", "Methane Reduction"],
    "orgs": ["Clean Grid Futures", "Gulf Coast Environmental Justice Fund", "Blue Oceans Accord", "Coal Transition Partners India",
             "Urban Air Quality Institute", "Global Methane Hub Partners", "Renewable Access Africa", "Climate Disclosure Project",
             "Fishing Communities Resilience Trust", "European Clean Power Alliance", "Petrochemical Watch Louisiana"],
    "kpis": ["Coal plants retired", "GW of clean energy enabled", "Tons CO2e avoided", "Marine area protected (km2)", "Cities with air monitoring"]},
  "Education": {
    "initiatives": ["College Access & Success", "Career & Technical Education", "High-Quality Charter Expansion",
                    "Early Literacy", "Tutoring Corps", "Healthcare Workforce Pathways"],
    "orgs": ["CollegeBound Advising Network", "Skilled Futures Academy", "Bright Minds Charter Network", "Readers Rising Foundation",
             "National Tutoring Collaborative", "Allied Health Career High Schools", "First-Gen Scholars Alliance",
             "Rural Learning Innovation Lab", "STEM Pathways Baltimore"],
    "kpis": ["Students enrolled", "College acceptance rate", "Credentials earned", "Reading proficiency gain (pts)", "Graduates placed in jobs"]},
  "Government Innovation": {
    "initiatives": ["What Works Cities", "Mayors Challenge", "Innovation Teams", "City Data Alliance",
                    "City Leadership Academy", "Youth Mental Health in Cities", "Housing Innovation"],
    "orgs": ["Civic Data Partners", "City Innovation Studio", "Results for Cities Institute", "Municipal Leadership Academy",
             "Latin America Urban Lab", "Open Government Collaborative", "Smart Permitting Coalition",
             "European Cities Innovation Network", "Affordable Housing Delivery Lab", "Civic Tech Africa"],
    "kpis": ["Cities engaged", "Residents served", "Staff trained in data practice", "Programs scaled", "Cost savings ($)"]},
  "Arts": {
    "initiatives": ["Digital Accelerator for Arts", "Public Art Challenge", "Arts Innovation & Management",
                    "Museum Access", "Cultural Districts", "Asian Arts Initiative"],
    "orgs": ["Harbor City Symphony", "Riverside Contemporary Art Museum", "Community Theater Collective", "Public Art Futures",
             "Digital Museum Commons", "Dance Across Boroughs", "Heritage Crafts Guild", "Neighborhood Murals Project",
             "Youth Orchestra of the Americas", "Island Arts Alliance"],
    "kpis": ["Visitors reached", "Artists commissioned", "Digital audience growth (%)", "Free admissions", "Earned revenue growth (%)"]},
}
AREA_WEIGHTS = {"Public Health": 0.30, "Environment": 0.25, "Education": 0.17, "Government Innovation": 0.16, "Arts": 0.12}
REGIONS = {
  "North America": ["United States", "Canada", "Mexico"],
  "Latin America": ["Brazil", "Colombia", "Peru", "Chile"],
  "Europe": ["United Kingdom", "France", "Germany", "Italy"],
  "Africa": ["Kenya", "Nigeria", "Ghana", "Ethiopia", "South Africa"],
  "South Asia": ["India", "Bangladesh", "Pakistan"],
  "East Asia & Pacific": ["Indonesia", "Philippines", "Vietnam", "Australia"],
}
REGION_WEIGHTS = [0.40, 0.12, 0.12, 0.14, 0.12, 0.10]
OFFICERS = {"Public Health": ["Karen Hale", "Dr. Amara Okafor", "Raj Patel"],
            "Environment": ["Andrea Wells", "Sofia Marquez", "Daniel Cho"],
            "Education": ["Henry Walsh", "Leah Goldberg"],
            "Government Innovation": ["Jason Andrews", "Priya Nair", "Marcus Bell"],
            "Arts": ["Katie Lowe", "Elena Rossi"]}
GRANT_TYPES = ["Project", "General Operating", "Capacity Building", "Challenge Grant", "Research", "Technical Assistance"]
BUDGET_LINES = ["Personnel", "Program Delivery", "Evaluation & Data", "Advocacy & Communications", "Technology", "Overhead"]

STRENGTHS = [
  "The applicant has a strong, decade-long track record in {init} and has delivered measurable outcomes across {country}.",
  "Leadership is exceptionally credible; the executive director previously scaled a similar program to national level.",
  "The theory of change is clear and directly aligned with the foundation's {area} strategy.",
  "Government partners in {country} have signed letters of support, which materially de-risks implementation.",
  "The evaluation plan includes a quasi-experimental design with baseline data already collected.",
  "Co-funding of roughly {match}% has been committed by peer funders, signalling strong field confidence.",
  "The budget is lean and well justified, with overhead below sector benchmarks.",
  "The proposal builds on a successful pilot that exceeded its targets by a wide margin.",
  "Data collection is grounded in open standards, enabling comparison across cities and countries.",
  "There is a credible sustainability plan to transition costs to public budgets after year three.",
]
CONCERNS = [
  "The budget allocates a high share to personnel without a clear staffing plan for {region}.",
  "Measurable outcomes are loosely defined; KPIs such as '{kpi}' lack baselines and targets.",
  "Political risk is elevated given upcoming elections in {country}, which could stall policy adoption.",
  "The organization has limited financial reserves and relied on a single funder for most of last year's revenue.",
  "Prior grant reporting was submitted late twice, raising concerns about grants management capacity.",
  "The scale-up timeline appears ambitious relative to current staff capacity.",
  "Overlap with an existing foundation grantee in {country} needs to be clarified to avoid duplication.",
  "The monitoring plan depends on administrative data that may not be reliably available.",
  "Industry opposition to {init} policy in the region may slow progress and increase legal costs.",
  "Audited financial statements for the most recent year are still outstanding.",
]
RECS = {
  "positive": ["Recommend approval at the full requested amount.",
               "Recommend approval with a light-touch reporting schedule.",
               "Strong candidate for a multi-year renewal pending year-one results."],
  "mixed":    ["Recommend approval at a reduced amount with milestone-based tranches.",
               "Recommend a revise-and-resubmit focused on outcome metrics.",
               "Recommend proceeding to due diligence with a site visit before final decision."],
  "negative": ["Do not recommend funding in the current cycle.",
               "Recommend declining; encourage reapplication once financial controls improve.",
               "Recommend referral to a peer funder better aligned with the scope."],
}

DONOR_TYPES = {"Family Foundation": ["Hartwell Family Foundation", "Nguyen-Ross Family Fund", "The Abernathy Trust", "Castellano Family Foundation"],
               "Corporate Partner": ["Meridian Global Bank", "Atlas Health Corp", "BrightGrid Energy", "Vantage Media Group", "Orion Pharmaceuticals"],
               "Peer Foundation": ["Horizon Foundation", "Global Commons Fund", "The Clearwater Foundation", "Future Cities Trust"],
               "Donor-Advised Fund": ["Summit Philanthropy DAF", "Legacy Giving DAF", "North Star Giving Fund"],
               "Government / Multilateral": ["UK Foreign Development Office", "World Health Partnership", "Inter-American Development Fund"],
               "High-Net-Worth Individual": ["Margaret Liu", "Robert & Ana Kessler", "Samuel Adeyemi", "Isabelle Fournier"]}
STAGES = ["Prospecting", "Cultivation", "Solicitation", "Negotiation", "Committed", "Closed Won", "Closed Lost"]
STAGE_PROB = {"Prospecting": 10, "Cultivation": 25, "Solicitation": 45, "Negotiation": 65, "Committed": 90, "Closed Won": 100, "Closed Lost": 0}
RMS = ["Patricia Harris", "Jordan Blake", "Mei Tanaka", "Omar Haddad", "Grace Whitfield"]
TOUCH_TYPES = ["Site Visit", "Board Briefing", "Email", "Call", "Gala Event", "Impact Report Sent", "Proposal Meeting"]
ENG = {
  "positive": ["The donor was enthusiastic after the {area} briefing and asked how to deepen their involvement.",
               "They praised the impact data from the {init} program and want to co-brand the next report.",
               "Excellent site visit in {country}; the family is considering a multi-year pledge.",
               "Board chair called personally to confirm they are excited to increase their commitment.",
               "Relationship is warm and trusting; they referred two peer funders to us this quarter."],
  "neutral":  ["Donor requested additional detail on the evaluation methodology before deciding.",
               "Meeting was cordial; timing of the gift depends on their fiscal year planning.",
               "They are reviewing several co-funding opportunities and will respond next quarter.",
               "Standard check-in call; no major updates on giving intentions.",
               "Program officer shared the latest {init} update and the donor acknowledged receipt."],
  "negative": ["The donor expressed frustration about delayed reporting on the previous grant.",
               "They are concerned about overhead levels and questioned the value of the {init} program.",
               "Engagement has cooled since leadership changes on their side; calls have gone unanswered.",
               "Donor indicated they may redirect funds to another cause area next year.",
               "They were disappointed that the {country} results fell short of what was promised."],
}

def _fill(t, ctx):
    return t.format(**ctx)

def _wchoice(d):
    keys = list(d.keys()); return random.choices(keys, weights=[d[k] for k in keys])[0]

def make_grant(gid, today):
    area = _wchoice(AREA_WEIGHTS)
    a = AREAS[area]
    region = random.choices(list(REGIONS.keys()), weights=REGION_WEIGHTS)[0]
    country = random.choice(REGIONS[region])
    init = random.choice(a["initiatives"])
    quality = random.random()                       # hidden merit score drives notes + status
    tone = "positive" if quality > 0.62 else ("mixed" if quality > 0.30 else "negative")
    match = random.choice([10, 15, 20, 25, 30, 40])
    ctx = dict(area=area, init=init, country=country, region=region, match=match, kpi=random.choice(a["kpis"]))
    n_s = {"positive": 4, "mixed": 2, "negative": 1}[tone]
    n_c = {"positive": 1, "mixed": 3, "negative": 4}[tone]
    notes = ["Reviewer assessment for the {} proposal under the {} initiative.".format(area, init)]
    notes += [_fill(s, ctx) for s in random.sample(STRENGTHS, n_s)]
    cons = [_fill(c, ctx) for c in random.sample(CONCERNS, n_c)]
    cons[0] = "However, " + cons[0][0].lower() + cons[0][1:]
    notes += cons
    notes += ["Overall merit score {:.1f}/5.".format(1 + quality * 4), random.choice(RECS[tone])]
    submitted = today - dt.timedelta(days=random.randint(5, 900))
    age = (today - submitted).days
    if age < 30:   status = random.choice(["Draft", "Submitted", "Submitted", "Under Review"])
    elif age < 240: status = random.choices(["Submitted", "Under Review", "Approved", "Declined"], [2, 5, 2, 1])[0]
    else:
        status = ("Paid" if random.random() < 0.6 else "Approved") if tone != "negative" else random.choice(["Declined", "Declined", "Under Review"])
    req = round(random.lognormvariate(12.6, 0.9) / 1000) * 1000  # ~ $300K median, long tail into multi-millions
    req = max(25000, min(req, 15000000))
    approved = int(req * random.choice([1.0, 1.0, 0.9, 0.75])) if status in ("Approved", "Paid") else None
    dur = random.choice([12, 18, 24, 36, 48])
    shares = [random.random() for _ in BUDGET_LINES]; tot = sum(shares)
    budget = [{"line_item": b, "amount": round(req * s / tot, 2)} for b, s in zip(BUDGET_LINES, shares)]
    outcomes = [{"kpi": k, "baseline": random.randint(0, 500), "target": random.randint(600, 50000)}
                for k in random.sample(a["kpis"], 2)]
    return {
        "grant_id": gid, "organization_name": random.choice(a["orgs"]), "program_area": area, "initiative": init,
        "grant_type": random.choice(GRANT_TYPES), "region": region, "country": country,
        "program_officer": random.choice(OFFICERS[area]), "requested_amount": req, "approved_amount": approved,
        "currency": "USD", "duration_months": dur, "status": status,
        "submitted_date": submitted.isoformat(),
        "decision_date": (submitted + dt.timedelta(days=random.randint(30, 120))).isoformat() if status in ("Approved", "Paid", "Declined") else None,
        "risk_rating": "Low" if quality > 0.62 else ("Medium" if quality > 0.30 else "High"),
        "matching_funds_required": random.random() < 0.35,
        "reviewer_score": round(1 + quality * 4, 1),
        "budget_breakdown": budget, "outcome_targets": outcomes,
        "reviewer_notes": " ".join(notes),
        "last_modified": dt.datetime.utcnow().isoformat() + "Z",
    }

NEXT = {"Draft": "Submitted", "Submitted": "Under Review", "Under Review": None, "Approved": "Paid"}

def advance(rec):
    rec = dict(rec)
    s = rec.get("status")
    if s == "Under Review":
        new = "Approved" if rec.get("reviewer_score", 3) >= 3 else "Declined"
    else:
        new = NEXT.get(s)
    if not new: return None
    rec["status"] = new
    if new in ("Approved",):
        rec["approved_amount"] = int(rec["requested_amount"] * random.choice([1.0, 0.9, 0.75]))
    if new in ("Approved", "Declined"):
        rec["decision_date"] = dt.date.today().isoformat()
    rec["last_modified"] = dt.datetime.utcnow().isoformat() + "Z"
    return rec

def make_opp(oid, grant, today):
    dtype = random.choices(list(DONOR_TYPES.keys()), weights=[3, 3, 2, 2, 1, 2])[0]
    area = grant["program_area"] if grant else random.choice(list(AREAS.keys()))
    init = grant["initiative"] if grant else random.choice(AREAS[area]["initiatives"])
    country = grant["country"] if grant else "United States"
    stage = random.choices(STAGES, weights=[2, 3, 3, 2, 2, 4, 1.5])[0]
    tone = random.choices(["positive", "neutral", "negative"],
                          weights=[6, 3, 1] if stage in ("Committed", "Closed Won") else ([1, 3, 6] if stage == "Closed Lost" else [3, 4, 2]))[0]
    ctx = dict(area=area, init=init, country=country)
    notes = " ".join(_fill(t, ctx) for t in random.sample(ENG[tone], 2))
    if tone != "neutral":
        notes += " " + _fill(random.choice(ENG["neutral"]), ctx)
    base = grant["requested_amount"] if grant else 500000
    amt = max(10000, round(base * random.uniform(0.15, 0.8) / 1000) * 1000)
    touches = [{"date": (today - dt.timedelta(days=random.randint(1, 300))).isoformat(),
                "type": random.choice(TOUCH_TYPES), "owner": random.choice(RMS)} for _ in range(random.randint(1, 4))]
    return {
        "opp_id": oid, "account_name": random.choice(DONOR_TYPES[dtype]), "donor_type": dtype,
        "grant_id_ref": grant["grant_id"] if grant else None, "program_area_interest": area,
        "stage": stage, "probability_pct": STAGE_PROB[stage], "amount": amt, "currency": "USD",
        "close_date": (today + dt.timedelta(days=random.randint(-400, 270))).isoformat(),
        "relationship_manager": random.choice(RMS), "engagement_history": touches,
        "donor_engagement_notes": notes, "last_modified": dt.datetime.utcnow().isoformat() + "Z",
    }

def _put(session, folder, key, body):
    ts = dt.datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    path = f"{STAGE}/{folder}/{folder}_{ts}.json"
    session.file.put_stream(io.BytesIO(json.dumps({key: body}).encode("utf-8")), path,
                            auto_compress=False, overwrite=True)
    return path.split("/")[-1]

def run(session, n_grants, n_opps, update_pct):
    random.seed()
    today = dt.date.today()
    # latest version of existing grants (so updates + opp FKs reference real ids)
    existing = [json.loads(r[0]) for r in session.sql("""
        SELECT r.value::string FROM BP_DEMO.RAW.RAW_FLUXX t, LATERAL FLATTEN(t.payload:records) r
        QUALIFY ROW_NUMBER() OVER (PARTITION BY r.value:grant_id ORDER BY r.value:last_modified::timestamp_ntz DESC) = 1
        """).collect()]
    max_id = 0
    for e in existing:
        try: max_id = max(max_id, int(e["grant_id"].split("-")[-1]))
        except Exception: pass
    n_upd = int(n_grants * update_pct) if existing else 0
    updates = [u for u in (advance(e) for e in random.sample(existing, min(n_upd, len(existing)))) if u]
    new = [make_grant(f"FLX-{today.year}-{max_id + i + 1:05d}", today) for i in range(n_grants - n_upd)]
    grants = new + updates

    pool = existing + new
    max_opp = session.sql("""SELECT COALESCE(MAX(TRY_TO_NUMBER(SPLIT_PART(o.value:opp_id::string,'-',2))),0)
                             FROM BP_DEMO.RAW.RAW_SFDC t, LATERAL FLATTEN(t.payload:opportunities) o""").collect()[0][0]
    opps = [make_opp(f"OPP-{int(max_opp) + i + 1:06d}", random.choice(pool) if pool and random.random() < 0.85 else None, today)
            for i in range(n_opps)]

    files = []
    for i in range(0, len(grants), 100):
        files.append(_put(session, "fluxx", "records", grants[i:i + 100]))
    for i in range(0, len(opps), 100):
        files.append(_put(session, "sfdc", "opportunities", opps[i:i + 100]))
    return {"new_grants": len(new), "grant_updates": len(updates), "opportunities": len(opps), "files": files}
$$;
