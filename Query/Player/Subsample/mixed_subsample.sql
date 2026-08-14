-- Query 1: filter1_agg1 (owner)
SELECT nationality, MIN(age) AS min_age FROM owner WHERE nba_team != 'Cleveland Cavaliers' GROUP BY nationality;

-- Query 2: filter2_agg1 (player)
SELECT nationality, SUM(olympic_gold_medals) AS sum_olympic_gold_medals FROM player WHERE nationality = 'German' AND olympic_gold_medals <= 0 GROUP BY nationality;

-- Query 3: filter1_join1 (player, team)
SELECT player.draft_pick, team.team_name, player.fiba_world_cup, team.location FROM player JOIN team ON player.team = team.team_name WHERE player.fiba_world_cup > 0;

-- Query 4: filter2_join2 (player, team, city, owner)
SELECT owner.age, team.founded_year, player.name, city.city_name FROM player JOIN team ON player.team = team.team_name JOIN owner ON team.ownership = owner.name JOIN city ON team.location = city.city_name WHERE player.birth_date > '1994/2/2' AND city.population > 715522;
