-- Query 1: agg_filter_join (player, team)
SELECT player.position, MIN(player.olympic_gold_medals) AS min_player_olympic_gold_medals FROM player JOIN team ON player.team = team.team_name WHERE team.location = 'Boston' GROUP BY player.position;

-- Query 2: agg_filter_join (player, team)
SELECT player.team, AVG(player.age) AS avg_player_age FROM player JOIN team ON player.team = team.team_name WHERE (player.nationality = 'Serbian') OR (player.nationality = 'Nigerian-American') GROUP BY player.team;

-- Query 3: agg_filter_join (city, player, team)
SELECT player.position, AVG(player.age) AS avg_player_age FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name WHERE player.team = 'Lokomotiv Kuban' GROUP BY player.position;

-- Query 4: agg_filter_join (city, player, team)
SELECT player.position, AVG(player.age) AS avg_player_age FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name WHERE (player.team = 'Cedevita Olimpija') OR (team.location = 'Boston') GROUP BY player.position;

-- Query 5: agg_filter_join (player, team)
SELECT team.location, COUNT(*) AS count_all FROM player JOIN team ON player.team = team.team_name WHERE team.location = 'Boston' GROUP BY team.location;

-- Query 6: agg_filter_join (city, player, team)
SELECT team.location, MAX(team.championship) AS max_team_championship FROM player JOIN team ON player.team = team.team_name WHERE (city.city_name = 'Dallas') OR (player.draft_pick <= 20) GROUP BY team.location;

-- Query 7: agg_filter_join (player, team)
SELECT player.position, MAX(team.championship) AS max_team_championship FROM player JOIN team ON player.team = team.team_name WHERE team.championship > 0 GROUP BY player.position;

-- Query 8: agg_filter_join (player, team)
SELECT player.nationality, MIN(player.olympic_gold_medals) AS min_player_olympic_gold_medals FROM player JOIN team ON player.team = team.team_name WHERE (player.nationality = 'American') OR (player.nationality = 'American-Venezuelan') GROUP BY player.nationality;

-- Query 9: agg_filter_join (city, player, team)
SELECT team.location, MIN(player.olympic_gold_medals) AS min_player_olympic_gold_medals FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name WHERE player.nationality = 'Serbian' GROUP BY team.location;

-- Query 10: agg_filter_join (city, player, team)
SELECT team.location, MIN(player.olympic_gold_medals) AS min_player_olympic_gold_medals FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name WHERE (player.fiba_world_cup <= 1) AND (player.nationality = 'American-born naturalized Azerbaijani') GROUP BY team.location;

-- Query 11: agg_filter_join (player, team)
SELECT player.team, SUM(player.mvp_awards) AS sum_player_mvp_awards FROM player JOIN team ON player.team = team.team_name WHERE (player.nationality = 'French') OR (player.team = 'Lokomotiv Kuban') GROUP BY player.team;

-- Query 12: agg_filter_join (city, player, team)
SELECT player.team, MIN(player.olympic_gold_medals) AS min_player_olympic_gold_medals FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name WHERE city.city_name = 'Denver' GROUP BY player.team;

-- Query 13: agg_filter_join (city, player, team)
SELECT player.team, MAX(team.championship) AS max_team_championship FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name WHERE (city.population < 2000000) OR (player.nationality = 'Serbian') GROUP BY player.team;

-- Query 14: agg_filter_join (player, team)
SELECT player.position, MAX(team.championship) AS max_team_championship FROM player JOIN team ON player.team = team.team_name WHERE player.age > 28 GROUP BY player.position;

-- Query 15: agg_filter_join (player, team)
SELECT player.team, COUNT(*) AS count_all FROM player JOIN team ON player.team = team.team_name WHERE (player.nationality = 'American-born naturalized Azerbaijani') AND (player.team = 'Los Angeles Lakers') GROUP BY player.team;

-- Query 16: agg_filter_join (city, player, team)
SELECT team.location, AVG(player.age) AS avg_player_age FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name WHERE player.nationality = 'American' GROUP BY team.location;

-- Query 17: agg_filter_join (city, player, team)
SELECT player.position, SUM(player.mvp_awards) AS sum_player_mvp_awards FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name WHERE (player.team = 'Orlando Magic') AND (team.location = 'Charlotte') GROUP BY player.position;

-- Query 18: agg_filter_join (player, team)
SELECT player.nationality, SUM(player.mvp_awards) AS sum_player_mvp_awards FROM player JOIN team ON player.team = team.team_name WHERE player.team = 'Los Angeles Lakers' GROUP BY player.nationality;
