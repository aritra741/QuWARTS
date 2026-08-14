-- Query 1: agg_temporal (player, team)
SELECT player.nationality, MIN(player.draft_year) AS min_player_draft_year FROM player JOIN team ON player.team = team.team_name WHERE player.birth_date = '1919/3/23' GROUP BY player.nationality;

-- Query 2: agg_temporal (player)
SELECT player.nationality, AVG(player.age) AS avg_player_age FROM player WHERE player.draft_year > 1985 GROUP BY player.nationality;

-- Query 3: agg_temporal (player)
SELECT player.position, AVG(player.age) AS avg_player_age FROM player WHERE player.birth_date = '1919/3/23' GROUP BY player.position;

-- Query 4: agg_temporal (player, team)
SELECT player.position, COUNT(*) AS count_all FROM player JOIN team ON player.team = team.team_name WHERE team.founded_year > 1946 GROUP BY player.position;

-- Query 5: agg_temporal (player, team)
SELECT player.team, COUNT(*) AS count_all FROM player JOIN team ON player.team = team.team_name WHERE player.birth_date = '1919/3/23' GROUP BY player.team;

-- Query 6: agg_temporal (player)
SELECT player.nationality, COUNT(*) AS count_all FROM player WHERE player.draft_year > 1985 GROUP BY player.nationality;

-- Query 7: agg_temporal (player, team)
SELECT player.position, COUNT(*) AS count_all FROM player JOIN team ON player.team = team.team_name WHERE player.birth_date = '1919/3/23' GROUP BY player.position;

-- Query 8: agg_temporal (player, team)
SELECT player.team, MIN(player.draft_year) AS min_player_draft_year FROM player JOIN team ON player.team = team.team_name WHERE player.birth_date = '1919/3/23' GROUP BY player.team;

-- Query 9: agg_temporal (player)
SELECT player.position, MIN(player.draft_year) AS min_player_draft_year FROM player WHERE player.draft_year < 1985 GROUP BY player.position;

-- Query 10: agg_temporal (player)
SELECT player.position, MAX(player.draft_pick) AS max_player_draft_pick FROM player WHERE player.birth_date = '1919/3/23' GROUP BY player.position;
