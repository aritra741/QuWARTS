-- Query 1: binary_join (player, team)
SELECT team.championship, team.location, player.age, player.olympic_gold_medals FROM player JOIN team ON player.team = team.team_name;

-- Query 2: binary_join (player, team)
SELECT team.founded_year, team.team_name, player.name, player.team FROM player JOIN team ON player.team = team.team_name;

-- Query 3: binary_join (team, city)
SELECT city.city_name, city.population, team.founded_year, team.championship FROM team JOIN city ON team.location = city.city_name;

-- Query 4: binary_join (team, owner)
SELECT owner.nba_team, team.location, team.founded_year, owner.name FROM team JOIN owner ON team.ownership = owner.name;

-- Query 5: multi_table_join (player, team, city)
SELECT player.fiba_world_cup, player.name, team.team_name, team.championship, city.state_name FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name;

-- Query 6: multi_table_join (player, team, owner)
SELECT owner.name, team.founded_year, team.championship, owner.age, player.nationality FROM player JOIN team ON player.team = team.team_name JOIN owner ON team.ownership = owner.name;
