-- Query 1: agg_join (city, player, team)
SELECT player.position, MAX(player.mvp_awards) AS max_player_mvp_awards FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name GROUP BY player.position;

-- Query 2: agg_join (player, team)
SELECT player.nationality, SUM(player.nba_championships) AS sum_player_nba_championships FROM player JOIN team ON player.team = team.team_name GROUP BY player.nationality;

-- Query 3: agg_join (city, player, team)
SELECT player.position, AVG(team.championship) AS avg_team_championship FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name GROUP BY player.position;

-- Query 4: agg_join (player, team)
SELECT player.position, SUM(team.championship) AS sum_team_championship FROM player JOIN team ON player.team = team.team_name GROUP BY player.position;

-- Query 5: agg_join (city, player, team)
SELECT player.position, COUNT(player.mvp_awards) AS count_player_mvp_awards FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name GROUP BY player.position;

-- Query 6: agg_join (city, player, team)
SELECT player.team, SUM(player.olympic_gold_medals) AS sum_player_olympic_gold_medals FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name GROUP BY player.team;

-- Query 7: agg_join (player, team)
SELECT player.position, COUNT(player.mvp_awards) AS count_player_mvp_awards FROM player JOIN team ON player.team = team.team_name GROUP BY player.position;

-- Query 8: agg_join (player, team)
SELECT player.team, SUM(player.olympic_gold_medals) AS sum_player_olympic_gold_medals FROM player JOIN team ON player.team = team.team_name GROUP BY player.team;

-- Query 9: agg_join (city, player, team)
SELECT player.position, SUM(team.championship) AS sum_team_championship FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name GROUP BY player.position;
