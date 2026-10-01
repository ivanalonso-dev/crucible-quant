-- =====================================================================================
-- Flujos de UN token ERC-20 hacia / desde exchanges, velas de 4h, desde 2020-09 (DUNE)
-- Versión alternativa a BigQuery, para cuando se renueven tus créditos gratuitos.
--
-- Para ahorrar créditos: ejecútala UN TOKEN CADA VEZ cambiando {{token}} (parámetro de Dune)
-- y, si aun así se agotan, por tramos de fechas.
-- Exporta cada resultado como CSV y júntalos en uno:  flujos_cex_4h.csv
-- (mismas columnas que la versión de BigQuery)
-- =====================================================================================
WITH cex AS (
    SELECT DISTINCT address FROM cex.addresses WHERE blockchain = 'ethereum'
),
t AS (
    SELECT
        tr.contract_address AS token_address,
        from_unixtime(floor(to_unixtime(tr.evt_block_time) / 14400) * 14400) AS t4h,
        CAST(tr.value AS DOUBLE) / 1e18 AS cantidad,
        cf.address IS NOT NULL AS de_cex,
        ca.address IS NOT NULL AS a_cex
    FROM erc20_ethereum.evt_Transfer tr
    LEFT JOIN cex cf ON tr."from" = cf.address
    LEFT JOIN cex ca ON tr."to"   = ca.address
    WHERE tr.contract_address = {{token}}
      AND tr.evt_block_time >= TIMESTAMP '2020-09-01'
      AND (cf.address IS NOT NULL OR ca.address IS NOT NULL)
)
SELECT
    token_address,
    t4h,
    SUM(CASE WHEN a_cex AND NOT de_cex THEN cantidad ELSE 0 END)                        AS entrada_cex,
    SUM(CASE WHEN de_cex AND NOT a_cex THEN cantidad ELSE 0 END)                        AS salida_cex,
    SUM(CASE WHEN a_cex AND NOT de_cex THEN cantidad ELSE 0 END)
      - SUM(CASE WHEN de_cex AND NOT a_cex THEN cantidad ELSE 0 END)                    AS neto_cex,
    SUM(CASE WHEN a_cex AND NOT de_cex THEN 1 ELSE 0 END)                               AS n_depositos,
    MAX(CASE WHEN a_cex AND NOT de_cex THEN cantidad ELSE 0 END)                        AS mayor_deposito,
    MAX(CASE WHEN de_cex AND NOT a_cex THEN cantidad ELSE 0 END)                        AS mayor_retirada
FROM t
GROUP BY 1, 2
ORDER BY 1, 2
