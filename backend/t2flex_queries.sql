-- =============================================================================
-- T2 Flex Web Service Queries -- automate branch
-- =============================================================================
-- Register each query in T2 Flex:
--   Reports > Query Manager > New Query
--   "Query Available for Web Services?" = Yes
--
-- Query UIDs are set in backend/.env:
--   T2_FLEX_QUERY_PERMITS_UID   = 4738
--   T2_FLEX_QUERY_CITATIONS_UID = 4742
-- =============================================================================


-- -----------------------------------------------------------------------------
-- Query 1: Parking Perks - List of active Permit Holders  (UID 4738)
-- Parameters: none
-- -----------------------------------------------------------------------------
--
-- Key design points:
--
--   * PERMISSION_VIEW + ENTITY_VIEW -- confirmed view names.
--   * LEFT JOIN COR_EMAIL -- permit holders WITHOUT a registered email still
--     appear (EMAIL_ADDRESS will be NULL). The draw system queues them in
--     missing_email_queue for the manager to resolve manually.
--   * CUSTOM_DATA filter (PNA_UID IN ...) -- restricts to permit program 2086
--     (DAD_UID 200044). This is the UBCO vehicle permit program confirmed by
--     the source query provided by the parking team. Remove this filter if you
--     ever want to include all active permit types campus-wide.
--   * PVR_END_DATE filter -- keeps only current vehicle-to-permit assignments.
--   * PNA_SERIES_PREFIX != 'BIKE' -- excludes bike permits at SQL level.
--   * LISTAGG -- groups multiple plates per person into one comma-separated
--     value ("WR3936,XA9894"), which the Python parser splits via _expand_plates().
--   * GROUP BY ENT.ENT_UID -- one row per entity (person).
--   * ENT_UID alias -- must stay as ENT_UID (not "Distinct of ENT_UID") so the
--     Python parser can find it with row.get("ENT_UID").

SELECT
    ENT.ENT_UID                                                      AS ENT_UID,
    MAX(COE.COE_EMAIL_ADDRESS)                                       AS EMAIL_ADDRESS,
    MAX(PNA.PNA_SERIES_PREFIX)                                       AS SERIES_PREFIX,
    MAX(PER.PER_NUMBER)                                              AS PERMIT_NUMBER,
    LISTAGG(VEH.VEH_PLATE_LICENSE, ',')
        WITHIN GROUP (ORDER BY VEH.VEH_PLATE_LICENSE)               AS LICENSE_PLATES
FROM PERMISSION_VIEW PER
INNER JOIN ENTITY_VIEW             ENT ON PER.ENT_UID_PURCHASING_ENTITY    = ENT.ENT_UID
LEFT  JOIN COR_EMAIL               COE ON ENT.COE_UID_HIGHEST_RANKED_EMAIL = COE.COE_UID
INNER JOIN PERMISSION_NUMBER_RANGE PNA ON PER.PNA_UID_PER_NUM_RANGE        = PNA.PNA_UID
INNER JOIN PER_VEH_REL             PVR ON PER.PER_UID                      = PVR.PER_UID_PERMISSION
INNER JOIN VEHICLE                 VEH ON PVR.VEH_UID_VEHICLE              = VEH.VEH_UID
WHERE PER.PSL_UID_STATUS = 5
  AND PNA.PNA_UID IN (
      SELECT CUD_RECORD_UID
      FROM   CUSTOM_DATA
      WHERE  UPPER(CUD_VALUE) = UPPER('2086')
        AND  DAD_UID = 200044
  )
  AND (PVR.PVR_END_DATE IS NULL OR PVR.PVR_END_DATE > CURRENT_DATE)
  AND PNA.PNA_SERIES_PREFIX != 'BIKE'
GROUP BY ENT.ENT_UID


-- -----------------------------------------------------------------------------
-- Query 2: Parking Perks - Citations by Month  (UID 4742)
-- Parameters: YEAR (integer, e.g. 2026), MONTH (integer, e.g. 4)
-- -----------------------------------------------------------------------------
--
-- Key design points:
--
--   * CONTRAVENTION_VIEW -- confirmed view name (not raw CONTRAVENTION table).
--   * CON_SNAP_VEH_PLATE_LICENSE -- plate snapshot at citation time.
--     No VEHICLE join needed; avoids broken-join failures.
--   * CZL_UID_ZONE = 2001 -- filters to UBCO zone only.
--   * DISTINCT -- one row per plate even if multiple citations that month.
--   * Parameters: T2 Flex substitutes the string literals 'YEAR' and 'MONTH'
--     with the provided values. Oracle implicitly casts them to numbers for
--     the EXTRACT() comparison.
--
-- Voided citations: CONTRAVENTION_VIEW does not expose the void reason column
-- directly. To exclude voided/dismissed citations add:
--   AND CON.CSL_UID_STATUS NOT IN (<void_uid>, <dismissed_uid>)
-- Confirm the status UIDs with your T2 Systems contact.

SELECT DISTINCT
    CON.CON_SNAP_VEH_PLATE_LICENSE  AS LICENSE_PLATE
FROM  CONTRAVENTION_VIEW CON
WHERE EXTRACT(YEAR  FROM CON.CON_ISSUE_DATE) = :YEAR
  AND EXTRACT(MONTH FROM CON.CON_ISSUE_DATE) = :MONTH
  AND CON.CZL_UID_ZONE = 2001
