-- =====================================================================================
-- Flujos de tokens ERC-20 hacia / desde exchanges, velas de 4h, desde 2020-09
-- GOOGLE BIGQUERY (modo sandbox: gratis, sin tarjeta, 1 TB de consultas al mes)
--
-- ANTES DE EJECUTAR:
--   1. Sube la lista de direcciones de exchanges (resultado de dune_etiquetas_cex.sql,
--      exportado como CSV) a una tabla:  TU_PROYECTO.crucible.cex_addresses  (columna: address)
--   2. Sustituye TU_PROYECTO por el id de tu proyecto de Google Cloud.
--   3. Mira arriba a la derecha cuántos GB va a procesar ANTES de darle a Ejecutar.
--      Si pasa de ~900 GB, ejecútala por años cambiando las fechas del WHERE.
--   4. Exporta el resultado como CSV:  flujos_cex_4h.csv
--
-- Tokens (verifica las direcciones en etherscan.io antes de ejecutar):
--   UNI  0x1f9840a85d5af5bf1d1762f925bdaddc4201f984
--   LINK 0x514910771af9ca656af840dff83e8264ecf986ca
--   AAVE 0x7fc66500c84a76ad7e9c93437bfc5ac33e2ddae9
--   ONDO 0xfaba6f8e4a5e8ab82f62fe7c39859fa577269be3
--   ENA  0x57e114b691db790c35207b2e685d4a43181e6061
--   SHIB 0x95ad61b0a150d79219dcf64e1e6cc01f0b64c4ce
--   (todos con 18 decimales)
-- =====================================================================================

WITH cex AS (
  SELECT DISTINCT LOWER(address) AS address FROM `TU_PROYECTO.crucible.cex_addresses`
),
t AS (
  SELECT
    token_address,
    TIMESTAMP_SECONDS(DIV(UNIX_SECONDS(block_timestamp), 14400) * 14400) AS t4h,
    LOWER(from_address) AS de,
    LOWER(to_address)   AS a,
    SAFE_CAST(value AS FLOAT64) / 1e18 AS cantidad
  FROM `bigquery-public-data.crypto_ethereum.token_transfers`
  WHERE block_timestamp >= TIMESTAMP('2020-09-01')
    AND token_address IN (
      '0x1f9840a85d5af5bf1d1762f925bdaddc4201f984',
      '0x514910771af9ca656af840dff83e8264ecf986ca',
      '0x7fc66500c84a76ad7e9c93437bfc5ac33e2ddae9',
      '0xfaba6f8e4a5e8ab82f62fe7c39859fa577269be3',
      '0x57e114b691db790c35207b2e685d4a43181e6061',
      '0x95ad61b0a150d79219dcf64e1e6cc01f0b64c4ce')
),
m AS (
  SELECT t.*, cf.address IS NOT NULL AS de_cex, ca.address IS NOT NULL AS a_cex
  FROM t
  LEFT JOIN cex cf ON t.de = cf.address
  LEFT JOIN cex ca ON t.a  = ca.address
)
SELECT
  token_address,
  t4h,
  SUM(IF(a_cex AND NOT de_cex, cantidad, 0))                      AS entrada_cex,
  SUM(IF(de_cex AND NOT a_cex, cantidad, 0))                      AS salida_cex,
  SUM(IF(a_cex AND NOT de_cex, cantidad, 0))
    - SUM(IF(de_cex AND NOT a_cex, cantidad, 0))                  AS neto_cex,
  COUNTIF(a_cex AND NOT de_cex)                                   AS n_depositos,
  MAX(IF(a_cex AND NOT de_cex, cantidad, 0))                      AS mayor_deposito,
  MAX(IF(de_cex AND NOT a_cex, cantidad, 0))                      AS mayor_retirada
FROM m
GROUP BY token_address, t4h
ORDER BY token_address, t4h
