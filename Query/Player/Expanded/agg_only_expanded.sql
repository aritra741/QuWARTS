-- Query 1: agg_only (player)
SELECT position, MIN(olympic_gold_medals) AS min_olympic_gold_medals FROM player GROUP BY position;

-- Query 2: agg_only (player)
SELECT nationality, COUNT(*) AS count_all FROM player GROUP BY nationality;

-- Query 3: agg_only (player)
SELECT position, AVG(age) AS avg_age FROM player GROUP BY position;

-- Query 4: agg_only (player)
SELECT nationality, MAX(age) AS max_age FROM player GROUP BY nationality;

-- Query 5: agg_only (player)
SELECT nationality, MIN(age) AS min_age FROM player GROUP BY nationality;

-- Query 6: agg_only (player)
SELECT nationality, AVG(age) AS avg_age FROM player GROUP BY nationality;

-- Query 7: agg_only (player)
SELECT position, COUNT(*) AS count_all FROM player GROUP BY position;

-- Query 8: agg_only (player)
SELECT position, SUM(olympic_gold_medals) AS sum_olympic_gold_medals FROM player GROUP BY position;

-- Query 9: agg_only (player)
SELECT position, MAX(nba_championships) AS max_nba_championships FROM player GROUP BY position;

-- Query 10: agg_only (player)
SELECT nationality, SUM(olympic_gold_medals) AS sum_olympic_gold_medals FROM player GROUP BY nationality;

-- Query 11: agg_only (player, team)
SELECT team, COUNT(*) AS count_all FROM player GROUP BY team;

-- Query 12: agg_only (player, team)
SELECT team, SUM(olympic_gold_medals) AS sum_olympic_gold_medals FROM player GROUP BY team;

-- Query 13: agg_only (player, team)
SELECT team, AVG(age) AS avg_age FROM player GROUP BY team;

-- Query 14: agg_only (player, team)
SELECT team, MIN(mvp_awards) AS min_mvp_awards FROM player GROUP BY team;

-- Query 15: agg_only (player, team)
SELECT team, MAX(nba_championships) AS max_nba_championships FROM player GROUP BY team;

-- Query 16: agg_only (player)
SELECT college, COUNT(*) AS count_all FROM player GROUP BY college;

-- Query 17: agg_only (player)
SELECT college, SUM(olympic_gold_medals) AS sum_olympic_gold_medals FROM player GROUP BY college;

-- Query 18: agg_only (player)
SELECT college, AVG(age) AS avg_age FROM player GROUP BY college;

-- Query 19: agg_only (player)
SELECT college, MIN(mvp_awards) AS min_mvp_awards FROM player GROUP BY college;

-- Query 20: agg_only (player)
SELECT college, MAX(nba_championships) AS max_nba_championships FROM player GROUP BY college;
