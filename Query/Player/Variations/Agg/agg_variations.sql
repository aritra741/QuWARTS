-- Inspiration: Query 1 (agg_queries.sql)
-- Variation: Changed MIN to MAX for olympic_gold_medals grouped by position.
SELECT position, MAX(olympic_gold_medals) AS max_olympic_gold_medals FROM player GROUP BY position;

-- Inspiration: Query 2 & Query 5 (agg_queries.sql)
-- Variation: Count players and find max age per nationality.
SELECT nationality, COUNT(*) AS count_all, MAX(age) AS max_age FROM player GROUP BY nationality;

-- Inspiration: Query 3 (agg_queries.sql)
-- Variation: Instead of AVG(age), calculate MIN and MAX age per position.
SELECT position, MIN(age) AS min_age, MAX(age) AS max_age FROM player GROUP BY position;

-- Inspiration: Query 4 (agg_queries.sql)
-- Variation: MIN age per nationality instead of MAX.
SELECT nationality, MIN(age) AS min_age FROM player GROUP BY nationality;

-- Inspiration: Query 8 (agg_queries.sql)
-- Variation: Changed MIN(age) to AVG(age) for owners grouped by nationality.
SELECT nationality, AVG(age) AS avg_age FROM owner GROUP BY nationality;

-- Inspiration: Query 9 (agg_queries.sql)
-- Variation: Count owners and find min own_year per nationality.
SELECT nationality, COUNT(*) AS count_all, MIN(own_year) AS min_own_year FROM owner GROUP BY nationality;
