-- Query 1: agg_filter (player)
SELECT nationality, AVG(age) AS avg_age FROM player WHERE nationality = 'Serbian' GROUP BY nationality;

-- Query 2: agg_filter (player, team)
SELECT team, COUNT(*) AS count_all FROM player WHERE (nationality != 'American-Venezuelan') OR (nationality = 'Croatian') GROUP BY team;

-- Query 3: agg_filter (player, team)
SELECT team, SUM(olympic_gold_medals) AS sum_olympic_gold_medals FROM player WHERE (nationality = 'Dutch') AND (team != 'Lokomotiv Kuban') GROUP BY team;

-- Query 4: agg_filter (player, team)
SELECT nationality, AVG(age) AS avg_age FROM player WHERE (nationality != 'American' AND nationality = 'Nigerian-American') OR (team = 'Lokomotiv Kuban') GROUP BY nationality;

-- Query 5: agg_filter (player)
SELECT nationality, MAX(nba_championships) AS max_nba_championships FROM player WHERE nationality != 'American' GROUP BY nationality;

-- Query 6: agg_filter (player, team)
SELECT team, COUNT(*) AS count_all FROM player WHERE (nationality = 'American-Venezuelan') AND (nationality != 'Slovenian') GROUP BY team;

-- Query 7: agg_filter (player, team)
SELECT position, MIN(mvp_awards) AS min_mvp_awards FROM player WHERE (nationality = 'American-born naturalized Azerbaijani' AND nationality != 'Greek-American') OR (team != 'Rochester Royals') GROUP BY position;

-- Query 8: agg_filter (player)
SELECT position, SUM(olympic_gold_medals) AS sum_olympic_gold_medals FROM player WHERE nationality = 'American-born naturalized Azerbaijani' GROUP BY position;

-- Query 9: agg_filter (player, team)
SELECT team, MAX(nba_championships) AS max_nba_championships FROM player WHERE (nationality = 'Dutch') OR (team != 'Lokomotiv Kuban') GROUP BY team;

-- Query 10: agg_filter (player)
SELECT nationality, COUNT(*) AS count_all FROM player WHERE (nationality = 'American' AND nationality != 'American-Venezuelan') OR (nationality != 'Croatian') GROUP BY nationality;

-- Query 11: agg_filter (player, team)
SELECT team, SUM(olympic_gold_medals) AS sum_olympic_gold_medals FROM player WHERE nationality = 'Nigerian-American' GROUP BY team;

-- Query 12: agg_filter (player, team)
SELECT team, MIN(mvp_awards) AS min_mvp_awards FROM player WHERE (nationality = 'Dutch' AND team != 'Lokomotiv Kuban') OR (team != 'Saski Baskonia') GROUP BY team;

-- Query 13: agg_filter (player)
SELECT position, MAX(nba_championships) AS max_nba_championships FROM player WHERE nationality = 'American-Venezuelan' GROUP BY position;

-- Query 14: agg_filter (player)
SELECT nationality, SUM(olympic_gold_medals) AS sum_olympic_gold_medals FROM player WHERE (nationality = 'Serbian') OR (nationality != 'Nigerian-American') GROUP BY nationality;
