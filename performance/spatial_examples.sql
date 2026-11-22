-- The stored point is (longitude, latitude). These examples center on Sao Paulo.
-- The GiST index ix_geo_point supports the bounding-box and nearest-neighbor steps.

EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) AS postal_prefixes_in_box
FROM dw.dim_geolocation
WHERE geo_point <@ box(point(-47.0,-24.0), point(-46.0,-23.0));

SELECT count(*) AS postal_prefixes_in_box
FROM dw.dim_geolocation
WHERE geo_point <@ box(point(-47.0,-24.0), point(-46.0,-23.0));

-- <-> ranks candidates in planar degrees; the displayed distance uses Haversine km.
EXPLAIN (ANALYZE, BUFFERS)
WITH candidates AS (
    SELECT zip_prefix, city, state, latitude, longitude
    FROM dw.dim_geolocation
    WHERE geo_point IS NOT NULL
    ORDER BY geo_point <-> point(-46.6333,-23.5505)
    LIMIT 10
)
SELECT zip_prefix, city, state,
    round((2 * 6371.0088 * asin(sqrt(least(1.0,
        power(sin(radians(latitude - (-23.5505)) / 2), 2) +
        cos(radians(-23.5505)) * cos(radians(latitude)) *
        power(sin(radians(longitude - (-46.6333)) / 2), 2)))))::numeric, 2)
        AS distance_km
FROM candidates
ORDER BY distance_km;

WITH candidates AS (
    SELECT zip_prefix, city, state, latitude, longitude
    FROM dw.dim_geolocation
    WHERE geo_point IS NOT NULL
    ORDER BY geo_point <-> point(-46.6333,-23.5505)
    LIMIT 10
)
SELECT zip_prefix, city, state,
    round((2 * 6371.0088 * asin(sqrt(least(1.0,
        power(sin(radians(latitude - (-23.5505)) / 2), 2) +
        cos(radians(-23.5505)) * cos(radians(latitude)) *
        power(sin(radians(longitude - (-46.6333)) / 2), 2)))))::numeric, 2)
        AS distance_km
FROM candidates
ORDER BY distance_km;
