-- =====================================================================
-- 05_semantic_agent.sql : consumption layer replacing static Tableau
--   AI.SV_GRANT_PIPELINE      semantic view (Cortex Analyst)
--   AI.CSS_GRANT_REVIEWS      Cortex Search over reviewer notes + AI summaries
--   AI.CSS_DONOR_NOTES        Cortex Search over donor engagement notes
--   AI.BP_GRANTS_AGENT        Cortex Agent (Snowflake Intelligence)
-- =====================================================================
USE WAREHOUSE BP_DEMO_WH;
USE SCHEMA BP_DEMO.AI;

-- ---------------------------------------------------------------- semantic view
CREATE OR REPLACE SEMANTIC VIEW BP_DEMO.AI.SV_GRANT_PIPELINE
  TABLES (
    grants AS BP_DEMO.CURATED.DT_GRANT_PIPELINE
      PRIMARY KEY (grant_id)
      WITH SYNONYMS ('grant applications', 'proposals', 'Fluxx grants', 'grantees')
      COMMENT = 'One row per Fluxx grant application with AI reviewer summary, AI risk theme and rolled-up Salesforce funding pipeline',
    opportunities AS BP_DEMO.AI.DT_OPPS_ENRICHED
      PRIMARY KEY (opp_id)
      WITH SYNONYMS ('donor opportunities', 'Salesforce opportunities', 'co-funding', 'gifts', 'pledges')
      COMMENT = 'Salesforce donor / co-funder opportunities, optionally linked to a grant, with AI sentiment score',
    budget AS BP_DEMO.CURATED.DT_GRANT_BUDGET
      PRIMARY KEY (grant_id, budget_line)
      WITH SYNONYMS ('budget line items', 'grant budgets')
      COMMENT = 'Requested grant budget split by line item'
  )
  RELATIONSHIPS (
    opp_to_grant    AS opportunities (grant_id_ref) REFERENCES grants,
    budget_to_grant AS budget (grant_id)            REFERENCES grants
  )
  FACTS (
    grants.requested_amount_f          AS requested_amount,
    grants.approved_amount_f           AS approved_amount,
    grants.committed_amount_f          AS committed_amount,
    grants.reviewer_score_f            AS reviewer_score,
    opportunities.amount_f             AS amount,
    opportunities.weighted_amount_f    AS amount * probability_pct / 100,
    opportunities.sentiment_f          AS donor_sentiment,
    budget.budget_amount_f             AS budget_amount
  )
  DIMENSIONS (
    grants.grant_id              AS grant_id            COMMENT = 'Fluxx grant identifier, e.g. FLX-2026-00042',
    grants.organization_name     AS organization_name   WITH SYNONYMS ('grantee', 'applicant', 'organization', 'nonprofit')
                                 COMMENT = 'Applicant organization',
    grants.program_area          AS program_area        WITH SYNONYMS ('focus area', 'portfolio', 'issue area', 'program')
                                 COMMENT = 'BP focus area: Public Health, Environment, Education, Government Innovation, Arts',
    grants.initiative            AS initiative          WITH SYNONYMS ('campaign', 'strategy', 'sub-program')
                                 COMMENT = 'Initiative within the program area, e.g. Beyond Coal, Tobacco Control, What Works Cities, Road Safety',
    grants.grant_type            AS grant_type          COMMENT = 'Project, General Operating, Capacity Building, Challenge Grant, Research, Technical Assistance',
    grants.region                AS region              WITH SYNONYMS ('geography', 'continent')
                                 COMMENT = 'North America, Latin America, Europe, Africa, South Asia, East Asia & Pacific',
    grants.country               AS country             COMMENT = 'Country where the grant is implemented',
    grants.program_officer       AS program_officer     WITH SYNONYMS ('PO', 'grant officer', 'program manager')
                                 COMMENT = 'Foundation program officer responsible for the grant',
    grants.status                AS status              WITH SYNONYMS ('grant status', 'stage of review', 'decision')
                                 COMMENT = 'Draft, Submitted, Under Review, Approved, Declined, Paid. "Pending" or "in review" means Under Review; "funded" or "awarded" means Approved or Paid.',
    grants.risk_rating           AS risk_rating         COMMENT = 'Reviewer risk rating: Low, Medium, High',
    grants.ai_primary_risk       AS ai_primary_risk     WITH SYNONYMS ('main concern', 'risk theme', 'top risk')
                                 COMMENT = 'AI_CLASSIFY-derived primary concern from reviewer notes',
    grants.ai_reviewer_summary   AS ai_reviewer_summary WITH SYNONYMS ('AI summary', 'executive summary', 'reviewer summary')
                                 COMMENT = 'One-sentence Cortex AI executive summary of the reviewer assessment',
    grants.matching_funds_required AS matching_funds_required COMMENT = 'TRUE if the grant requires matching funds from co-funders',
    grants.duration_months       AS duration_months     COMMENT = 'Grant duration in months',
    grants.submitted_date        AS submitted_date      WITH SYNONYMS ('application date')
                                 COMMENT = 'Date the application was submitted in Fluxx',
    grants.submitted_year        AS YEAR(submitted_date) COMMENT = 'Calendar year of submission',
    grants.submitted_quarter     AS DATE_TRUNC('quarter', submitted_date) COMMENT = 'Quarter of submission',
    grants.decision_date         AS decision_date       COMMENT = 'Date of approval/decline decision',
    opportunities.opp_id         AS opp_id              COMMENT = 'Salesforce opportunity id',
    opportunities.account_name   AS account_name        WITH SYNONYMS ('donor', 'funder', 'co-funder', 'partner', 'account')
                                 COMMENT = 'Salesforce donor / co-funder account',
    opportunities.donor_type     AS donor_type          WITH SYNONYMS ('funder type', 'donor segment')
                                 COMMENT = 'Family Foundation, Corporate Partner, Peer Foundation, Donor-Advised Fund, Government / Multilateral, High-Net-Worth Individual',
    opportunities.stage          AS stage               WITH SYNONYMS ('opportunity stage', 'pipeline stage')
                                 COMMENT = 'Prospecting, Cultivation, Solicitation, Negotiation, Committed, Closed Won, Closed Lost',
    opportunities.relationship_manager AS relationship_manager WITH SYNONYMS ('RM', 'gift officer', 'donor relations lead')
                                 COMMENT = 'Relationship manager who owns the donor',
    opportunities.donor_health   AS donor_health        COMMENT = 'Positive / Neutral / At Risk bucket derived from AI sentiment',
    opportunities.program_area_interest AS program_area_interest COMMENT = 'Program area the donor is interested in',
    opportunities.close_date     AS close_date          COMMENT = 'Expected or actual close date of the opportunity',
    budget.budget_line           AS budget_line         WITH SYNONYMS ('budget category', 'line item')
                                 COMMENT = 'Personnel, Program Delivery, Evaluation & Data, Advocacy & Communications, Technology, Overhead'
  )
  METRICS (
    grants.grant_count              AS COUNT(grants.grant_id)                  WITH SYNONYMS ('number of grants', 'applications')
                                    COMMENT = 'Number of grant applications',
    grants.total_requested_amount   AS SUM(grants.requested_amount_f)          WITH SYNONYMS ('requested', 'ask amount', 'total ask')
                                    COMMENT = 'Total requested grant amount (USD)',
    grants.total_approved_amount    AS SUM(grants.approved_amount_f)           WITH SYNONYMS ('awarded', 'funded amount', 'grants awarded')
                                    COMMENT = 'Total approved/awarded amount (USD)',
    grants.avg_request_size         AS AVG(grants.requested_amount_f)          COMMENT = 'Average requested amount (USD)',
    grants.avg_reviewer_score       AS AVG(grants.reviewer_score_f)            COMMENT = 'Average reviewer merit score (1-5)',
    grants.approval_rate            AS COUNT_IF(grants.status IN ('Approved','Paid'))
                                       / NULLIF(COUNT_IF(grants.status IN ('Approved','Paid','Declined')), 0)
                                    WITH SYNONYMS ('win rate', 'success rate')
                                    COMMENT = 'Share of decided grants that were approved',
    grants.total_committed_cofunding AS SUM(grants.committed_amount_f)         COMMENT = 'Co-funding committed or closed-won against grants (USD)',
    opportunities.opportunity_count AS COUNT(opportunities.opp_id)             COMMENT = 'Number of Salesforce opportunities',
    opportunities.total_pipeline_amount AS SUM(opportunities.amount_f)         WITH SYNONYMS ('pipeline', 'donor pipeline', 'fundraising pipeline')
                                    COMMENT = 'Total opportunity amount (USD)',
    opportunities.weighted_pipeline AS SUM(opportunities.weighted_amount_f)    WITH SYNONYMS ('forecast', 'probability-weighted pipeline')
                                    COMMENT = 'Opportunity amount weighted by stage probability (USD)',
    opportunities.avg_donor_sentiment AS AVG(opportunities.sentiment_f)        WITH SYNONYMS ('sentiment', 'donor sentiment', 'relationship health')
                                    COMMENT = 'Average Cortex AI sentiment of donor engagement notes (-1 negative to 1 positive)',
    budget.total_budget_amount      AS SUM(budget.budget_amount_f)             COMMENT = 'Total budget by line item (USD)'
  )
  COMMENT = 'BP grantmaking + donor pipeline (Fluxx + Salesforce), AI-enriched'
  AI_SQL_GENERATION 'Amounts are USD. "Under review" / "pending" = status Under Review. "Funded"/"awarded" = status IN (Approved, Paid). Round currency to whole dollars. When listing grants include organization_name, program_area and requested_amount; include ai_reviewer_summary when the user asks why, what reviewers said, or for qualitative context.'
  AI_VERIFIED_QUERIES (
    vq_under_review_arts_edu AS (
      QUESTION 'What is the total requested amount for Arts and Education grants currently under review?'
      ONBOARDING_QUESTION TRUE
      SQL 'SELECT program_area, COUNT(*) AS grant_count, SUM(requested_amount) AS total_requested_amount FROM __grants WHERE status = ''Under Review'' AND program_area IN (''Arts'', ''Education'') GROUP BY program_area ORDER BY total_requested_amount DESC'
    ),
    vq_sentiment_by_area AS (
      QUESTION 'Which program area has the lowest average donor sentiment?'
      ONBOARDING_QUESTION TRUE
      SQL 'SELECT g.program_area, AVG(o.donor_sentiment) AS avg_donor_sentiment, COUNT(o.opp_id) AS opportunity_count FROM __opportunities o JOIN __grants g ON o.grant_id_ref = g.grant_id GROUP BY g.program_area ORDER BY avg_donor_sentiment ASC'
    ),
    vq_approval_rate AS (
      QUESTION 'What is the approval rate and total awarded by program area?'
      SQL 'SELECT program_area, COUNT_IF(status IN (''Approved'',''Paid'')) / NULLIF(COUNT_IF(status IN (''Approved'',''Paid'',''Declined'')),0) AS approval_rate, SUM(approved_amount) AS total_approved_amount FROM __grants GROUP BY program_area ORDER BY total_approved_amount DESC'
    ),
    vq_top_env AS (
      QUESTION 'Top 5 Environment organizations by requested amount with their AI summaries'
      ONBOARDING_QUESTION TRUE
      SQL 'SELECT organization_name, initiative, status, requested_amount, ai_reviewer_summary FROM __grants WHERE program_area = ''Environment'' ORDER BY requested_amount DESC LIMIT 5'
    )
  );

-- ---------------------------------------------------------------- Cortex Search services
CREATE OR REPLACE CORTEX SEARCH SERVICE BP_DEMO.AI.CSS_GRANT_REVIEWS
  ON search_text
  ATTRIBUTES program_area, status, initiative, region, ai_primary_risk, risk_rating
  WAREHOUSE = BP_DEMO_WH
  TARGET_LAG = '10 minutes'
  COMMENT = 'Semantic search over Fluxx reviewer assessments and AI summaries'
AS
SELECT grant_id, organization_name, program_area, initiative, region, country, status,
       risk_rating, ai_primary_risk, requested_amount, ai_reviewer_summary, reviewer_notes,
       ai_reviewer_summary || ' ' || reviewer_notes AS search_text
FROM BP_DEMO.AI.DT_GRANTS_ENRICHED;

CREATE OR REPLACE CORTEX SEARCH SERVICE BP_DEMO.AI.CSS_DONOR_NOTES
  ON donor_engagement_notes
  ATTRIBUTES donor_type, stage, donor_health, program_area_interest, relationship_manager
  WAREHOUSE = BP_DEMO_WH
  TARGET_LAG = '10 minutes'
  COMMENT = 'Semantic search over Salesforce donor engagement notes'
AS
SELECT opp_id, account_name, donor_type, stage, amount, donor_health, donor_sentiment,
       program_area_interest, relationship_manager, grant_id_ref, donor_engagement_notes
FROM BP_DEMO.AI.DT_OPPS_ENRICHED;

-- ---------------------------------------------------------------- Cortex Agent
CREATE OR REPLACE AGENT BP_DEMO.AI.BP_GRANTS_AGENT
  COMMENT = 'Grants & donor intelligence agent - replaces static Tableau grant/pipeline reports'
  PROFILE = '{"display_name": "Philanthropy Insights Agent", "color": "blue"}'
  FROM SPECIFICATION
  $$
  models:
    orchestration: auto

  orchestration:
    budget:
      seconds: 60
      tokens: 32000

  instructions:
    orchestration: >
      You support program officers, grants managers and donor-relations staff at a large philanthropy
      (focus areas: Public Health, Environment, Education, Government Innovation, Arts).
      Use GrantPipelineAnalyst for any question involving amounts, counts, rates, rankings, trends or
      sentiment averages across grants, donors, budgets or opportunities.
      Use GrantReviewSearch for qualitative questions about what reviewers said, concerns, strengths,
      risks or recommendations on grant applications.
      Use DonorNotesSearch for qualitative questions about donor relationships, engagement or donor concerns.
      For mixed questions (e.g. "which large Public Health grants are under review and what are the concerns"),
      first use GrantPipelineAnalyst to identify the grants, then GrantReviewSearch for the qualitative context.
    response: >
      Be concise and executive-ready. Lead with the answer, then a short table when listing items.
      Format currency as USD with thousands separators. When citing reviewer insight, quote the AI reviewer
      summary. Note that donor sentiment ranges from -1 (negative) to 1 (positive).
    sample_questions:
      - question: "What is the total requested amount for Arts and Education grants currently under review?"
      - question: "Which program area has the lowest average donor sentiment, and what are those donors saying?"
      - question: "Summarize the main concerns reviewers raised on Public Health grants under review."
      - question: "Show the top 5 Environment grants by requested amount with their AI summaries."
      - question: "What is our approval rate by program area, and how much have we awarded?"
      - question: "Which corporate partners are at risk, and which relationship managers own them?"

  tools:
    - tool_spec:
        type: "cortex_analyst_text_to_sql"
        name: "GrantPipelineAnalyst"
        description: "Text-to-SQL over Fluxx grants (requested/approved amounts, status, program area, initiative, region, program officer, AI summary, AI risk theme), Salesforce donor opportunities (donor, donor type, stage, amount, weighted pipeline, sentiment) and grant budget line items."
    - tool_spec:
        type: "cortex_search"
        name: "GrantReviewSearch"
        description: "Searches Fluxx reviewer assessments and one-sentence AI reviewer summaries. Filterable by program_area, status, initiative, region, ai_primary_risk, risk_rating."
    - tool_spec:
        type: "cortex_search"
        name: "DonorNotesSearch"
        description: "Searches Salesforce donor engagement notes. Filterable by donor_type, stage, donor_health, program_area_interest, relationship_manager."

  tool_resources:
    GrantPipelineAnalyst:
      semantic_view: "BP_DEMO.AI.SV_GRANT_PIPELINE"
      execution_environment:
        type: "warehouse"
        warehouse: "BP_DEMO_WH"
    GrantReviewSearch:
      search_service: "BP_DEMO.AI.CSS_GRANT_REVIEWS"
      max_results: "8"
      title_column: "organization_name"
      id_column: "grant_id"
    DonorNotesSearch:
      search_service: "BP_DEMO.AI.CSS_DONOR_NOTES"
      max_results: "8"
      title_column: "account_name"
      id_column: "opp_id"
  $$;

-- Make it visible in Snowflake Intelligence (if the account uses the SI object model):
-- ALTER SNOWFLAKE INTELLIGENCE SNOWFLAKE_INTELLIGENCE_OBJECT_DEFAULT ADD AGENT BP_DEMO.AI.BP_GRANTS_AGENT;
