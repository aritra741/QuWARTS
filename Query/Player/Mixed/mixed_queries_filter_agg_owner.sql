-- Query 1: filter1_agg1 (owner)
SELECT nationality, MIN(age) AS min_age FROM owner WHERE nba_team != 'Cleveland Cavaliers' GROUP BY nationality;

-- Query 2: filter2_agg1 (owner)
SELECT nationality, SUM(age) AS sum_age FROM owner WHERE age != 76 AND nba_team != 'Houston Rockets' GROUP BY nationality;

-- Query 3: filter3_agg1 (owner)
SELECT nationality, COUNT(age) AS count_age FROM owner WHERE name = 'Tom Gores  ' OR own_year >= 1994 GROUP BY nationality;

-- Query 4: filter4_agg1 (owner)
SELECT nationality, MAX(age) AS max_age FROM owner WHERE own_year = 2012 AND nba_team = 'New York Knicks' AND age <= 88 GROUP BY nationality;

-- Query 5: filter5_agg1 (owner)
SELECT nationality, AVG(age) AS avg_age FROM owner WHERE nationality = 'Taiwanese-Canadian' OR own_year <= 2012 OR nba_team != 'Dallas Mavericks' GROUP BY nationality;

-- Query 6: filter6_agg1 (owner)
SELECT nationality, MIN(age) AS min_age FROM owner WHERE (nba_team != 'Chicago Bulls' AND nationality = 'Israeli-American') OR (name = 'Steven Anthony Ballmer' AND age <= 63) GROUP BY nationality;

