-- =====================================================================================
-- Lista de direcciones de EXCHANGES CENTRALIZADOS en Ethereum (etiquetas de Dune)
-- Consulta MUY barata (tabla pequeña). Exporta el resultado como CSV: cex_addresses.csv
-- Se usa en BigQuery (bigquery_flujos_2020.sql) y como referencia.
-- =====================================================================================
SELECT DISTINCT
    lower(to_hex(address)) AS address_hex,
    '0x' || lower(to_hex(address)) AS address,
    cex_name
FROM cex.addresses
WHERE blockchain = 'ethereum'
ORDER BY cex_name
