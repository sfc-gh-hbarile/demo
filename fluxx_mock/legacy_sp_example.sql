/* =====================================================================
   legacy_sp_example.sql  -- the "BEFORE" picture (SQL Server, T-SQL)
   Representative of the nightly stored procs that rebuild grant reporting
   tables today. Shown side by side with 04_dynamic_tables.sql.
   ===================================================================== */
CREATE OR ALTER PROCEDURE dbo.usp_Rebuild_GrantPipeline_Report
AS
BEGIN
    SET NOCOUNT ON;
    BEGIN TRY
        BEGIN TRANSACTION;

        -- 1. Shred the Fluxx XML/JSON export into a temp table (schema must be predefined)
        IF OBJECT_ID('tempdb..#grants') IS NOT NULL DROP TABLE #grants;
        SELECT  j.grant_id, j.organization_name, j.program_area, j.status,
                CAST(j.requested_amount AS DECIMAL(14,2)) AS requested_amount,
                j.reviewer_notes, j.last_modified
        INTO    #grants
        FROM    stg.FluxxExport e
        CROSS APPLY OPENJSON(e.payload, '$.records')
             WITH (grant_id VARCHAR(30), organization_name NVARCHAR(200), program_area VARCHAR(50),
                   status VARCHAR(30), requested_amount VARCHAR(30), reviewer_notes NVARCHAR(MAX),
                   last_modified DATETIME2) j;

        -- 2. Dedup to latest version (manual window + delete)
        ;WITH d AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY grant_id ORDER BY last_modified DESC) rn FROM #grants)
        DELETE FROM d WHERE rn > 1;

        -- 3. Budget line items: nested array -> cursor loop
        DECLARE @gid VARCHAR(30), @budget NVARCHAR(MAX);
        DECLARE budget_cur CURSOR FAST_FORWARD FOR
            SELECT grant_id, JSON_QUERY(payload, '$.budget_breakdown') FROM stg.FluxxExport_Detail;
        OPEN budget_cur;
        FETCH NEXT FROM budget_cur INTO @gid, @budget;
        WHILE @@FETCH_STATUS = 0
        BEGIN
            INSERT INTO rpt.GrantBudget (grant_id, budget_line, budget_amount)
            SELECT @gid, line_item, amount FROM OPENJSON(@budget) WITH (line_item VARCHAR(50), amount DECIMAL(14,2));
            FETCH NEXT FROM budget_cur INTO @gid, @budget;
        END
        CLOSE budget_cur; DEALLOCATE budget_cur;

        -- 4. Salesforce join + aggregation into the Tableau extract table
        TRUNCATE TABLE rpt.GrantPipeline;
        INSERT INTO rpt.GrantPipeline (grant_id, organization_name, program_area, status,
                                       requested_amount, opp_count, pipeline_amount)
        SELECT g.grant_id, g.organization_name, g.program_area, g.status, g.requested_amount,
               COUNT(o.opp_id), ISNULL(SUM(o.amount), 0)
        FROM   #grants g
        LEFT JOIN stg.SalesforceOpportunity o ON o.grant_id_ref = g.grant_id
        GROUP BY g.grant_id, g.organization_name, g.program_area, g.status, g.requested_amount;

        -- 5. No AI: reviewer_notes stay unread free text; sentiment is not possible in-engine.

        COMMIT TRANSACTION;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
        THROW;
    END CATCH
END;
GO
-- Scheduled by a SQL Agent job every 15-30 min; Tableau extracts refresh after it.
-- Every schema change in Fluxx/Salesforce = edit WITH(...) clauses, temp tables, rpt tables, extracts.
