-- =============================================================================
-- T2 Flex Web Service Queries — automate branch
-- =============================================================================
-- Register each query in T2 Flex:
--   Reports > Query Manager > New Query
--   "Query Available for Web Services?" = Yes
--
-- Query names must match T2_FLEX_QUERY_PERMITS and T2_FLEX_QUERY_CITATIONS
-- in backend/.env exactly (case-sensitive).
-- =============================================================================


-- -----------------------------------------------------------------------------
-- Query 1: Parking Perks - List of active Permit Holders
-- Parameters: none
-- -----------------------------------------------------------------------------
--
-- Adapted from an existing working T2 Flex query. Key design points:
--
--   • PERMISSION_VIEW + ENTITY_VIEW — confirmed view names.
--   • PNA_SERIES_PREFIX — confirmed column on PERMISSION_NUMBER_RANGE.
--   • PER_VEH_REL (PVR) — permit-to-vehicle relationship, more accurate than
--     ENT_VEH_REL for our purposes. PVR_END_DATE IS NULL filters current
--     vehicle assignments only.
--   • LISTAGG — groups multiple plates per person into one comma-separated
--     row ("WR3936,XA9894"), matching the format the Python parser expects.
--   • GROUP BY ENT.ENT_UID — one row per entity.
--   • LEFT JOIN COR_EMAIL — permit holders without a registered email still
--     appear (email column will be NULL; manager notifies them manually).
--   • SERIES_PREFIX filter — excludes BIKE permits at SQL level.
--
-- CUSTOM_DATA filter note:
--   The original source query included this WHERE clause:
--     AND PNA.PNA_UID IN (
--         SELECT CUD_RECORD_UID FROM CUSTOM_DATA
--         WHERE UPPER(CUD_VALUE) = UPPER('2086') AND DAD_UID = 200044
--     )
--   This filters to a specific permit program/facility (value '2086').
--   It has been removed here so all active UBCO vehicle permit holders are
--   included. If results include unwanted permit types, add it back and
--   confirm with your T2 Systems contact what '2086' / DAD_UID 200044 represents.

SELECT
    ENT.ENT_UID                                                      AS ENT_UID,
    MAX(COE.COE_EMAIL_ADDRESS)                                       AS EMAIL_ADDRESS,
    MAX(PNA.PNA_SERIES_PREFIX)                                       AS SERIES_PREFIX,
    MAX(PER.PER_NUMBER)                                              AS PERMIT_NUMBER,
    LISTAGG(VEH.VEH_PLATE_LICENSE, ',')
        WITHIN GROUP (ORDER BY VEH.VEH_PLATE_LICENSE)               AS LICENSE_PLATES
FROM PERMISSION_VIEW PER
INNER JOIN ENTITY_VIEW             ENT ON PER.ENT_UID_PURCHASING_ENTITY   = ENT.ENT_UID
LEFT  JOIN COR_EMAIL               COE ON ENT.COE_UID_HIGHEST_RANKED_EMAIL = COE.COE_UID
INNER JOIN PERMISSION_NUMBER_RANGE PNA ON PER.PNA_UID_PER_NUM_RANGE        = PNA.PNA_UID
INNER JOIN PER_VEH_REL             PVR ON PER.PER_UID                      = PVR.PER_UID_PERMISSION
INNER JOIN VEHICLE                 VEH ON PVR.VEH_UID_VEHICLE              = VEH.VEH_UID
WHERE PER.PSL_UID_STATUS = 5
  AND (PVR.PVR_END_DATE IS NULL OR PVR.PVR_END_DATE > CURRENT_DATE)
  AND PNA.PNA_SERIES_PREFIX != 'BIKE'
GROUP BY ENT.ENT_UID


-- -----------------------------------------------------------------------------
-- Query 2: Parking Perks - Citations by Month
-- Parameters: :YEAR (integer, e.g. 2026), :MONTH (integer, e.g. 4)
-- -----------------------------------------------------------------------------
--
-- Adapted from confirmed working query "UBCO Citations Issued by Date Range
-- with Vehicle" (Query UID 4737). Key design points:
--
--   • CONTRAVENTION_VIEW — confirmed view name (not raw CONTRAVENTION table).
--   • CON_SNAP_VEH_PLATE_LICENSE — plate snapshot stored on the citation at
--     issue time. No VEHICLE join needed; avoids broken-join failures.
--   • CZL_UID_ZONE = 2001 — filters to UBCO zone only.
--   • CON_ISSUE_DATE — confirmed column name.
--   • DISTINCT — one row per plate even if multiple citations that month.
--
-- Parameters are plain integers to avoid T2 Flex Alpha-type validation errors
-- that reject hyphens in date strings. EXTRACT() compares year and month
-- directly against the numeric values.
--   Example: YEAR=2026, MONTH=4  →  all citations in April 2026
--
-- Voided citations: CONTRAVENTION_VIEW does not expose CVL_UID_VOID_REASON
-- directly. If you need to exclude voided/dismissed citations, add:
--   AND CON.CSL_UID_STATUS NOT IN (<void_status_uid>, <dismissed_status_uid>)
-- Confirm status UIDs with your T2 Systems contact.

SELECT DISTINCT
    CON.CON_SNAP_VEH_PLATE_LICENSE  AS LICENSE_PLATE
FROM  CONTRAVENTION_VIEW CON
WHERE EXTRACT(YEAR  FROM CON.CON_ISSUE_DATE) = :YEAR
  AND EXTRACT(MONTH FROM CON.CON_ISSUE_DATE) = :MONTH
  AND CON.CZL_UID_ZONE = 2001
