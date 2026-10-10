-- =====================================================================
-- 06 - Agent skill: upload fpa-variance-review/SKILL.md to a named stage
-- Run from a client that supports PUT (SnowSQL / snow sql / CoCo), from this
-- FP&A directory. In Snowsight, upload the file to the stage path instead.
-- =====================================================================
USE ROLE FPA_DEMO_ROLE; USE WAREHOUSE FPA_DEMO_WH;

CREATE STAGE IF NOT EXISTS FPA_DEMO.FPA.AGENT_SKILLS
  DIRECTORY = (ENABLE = TRUE) COMMENT = 'Cortex Agent skills for FPA_AGENT';

-- Adjust the local path if you run from a different directory
PUT 'file:///Users/hbarile/Dev/dev/profiles/hbtraining/FP&A/agent_skills/fpa-variance-review/SKILL.md'
  @FPA_DEMO.FPA.AGENT_SKILLS/skills/fpa-variance-review/ AUTO_COMPRESS = FALSE OVERWRITE = TRUE;

-- Validation: expect agent_skills/skills/fpa-variance-review/SKILL.md
LS @FPA_DEMO.FPA.AGENT_SKILLS PATTERN = '.*SKILL\\.md';
