-- Query 1: filter1_join1 (player, team)
SELECT player.draft_pick, team.team_name, player.fiba_world_cup, team.location FROM player JOIN team ON player.team = team.team_name WHERE player.fiba_world_cup > 0;

-- Query 2: filter2_join2 (player, team, city, owner)
SELECT owner.age, team.founded_year, player.name, city.city_name FROM player JOIN team ON player.team = team.team_name JOIN owner ON team.ownership = owner.name JOIN city ON team.location = city.city_name WHERE player.birth_date > '1994/2/2' AND city.population > 715522;

-- Query 3: filter3_join1 (player, team)
SELECT player.team, team.location, player.college, team.team_name FROM player JOIN team ON player.team = team.team_name WHERE player.nba_championships > 0 OR player.nationality != 'American-Venezuelan';

-- Query 4: filter4_join2 (player, team, city, owner)
SELECT owner.age, city.area, team.location, player.team FROM player JOIN team ON player.team = team.team_name JOIN owner ON team.ownership = owner.name JOIN city ON team.location = city.city_name WHERE player.college = 'University of Kentucky' AND city.population != 383997 AND team.founded_year >= 1949;

-- Query 5: filter5_join1 (player, team)
SELECT player.mvp_awards, team.championship, player.draft_year, team.team_name FROM player JOIN team ON player.team = team.team_name WHERE team.location != 'Los Angeles' OR team.founded_year < 1967 OR player.birth_date = '1971/10/2';

-- Query 6: filter6_join2 (player, team, city, owner)
SELECT owner.nba_team, team.ownership, player.fiba_world_cup, city.city_name FROM player JOIN team ON player.team = team.team_name JOIN owner ON team.ownership = owner.name JOIN city ON team.location = city.city_name WHERE (owner.nationality != 'American  ' AND player.olympic_gold_medals <= 1) OR (player.position = 'Backcourt' AND player.draft_year != 1990);

-- Query 7: filter1_join1 (player, team)
SELECT team.location, player.nba_championships, team.team_name, player.team FROM player JOIN team ON player.team = team.team_name WHERE player.nba_championships < 0;

-- Query 8: filter2_join2 (player, team, city, owner)
SELECT player.nationality, owner.nationality, city.population, team.championship FROM player JOIN team ON player.team = team.team_name JOIN owner ON team.ownership = owner.name JOIN city ON team.location = city.city_name WHERE player.position != 'Backcourt' AND player.draft_year >= 1990;

-- Query 9: filter3_join1 (player, team)
SELECT player.name, player.position, team.championship, team.founded_year FROM player JOIN team ON player.team = team.team_name WHERE player.name = 'Kobe Bean Bryant' OR player.fiba_world_cup >= 0;

-- Query 10: filter4_join2 (player, team, city, owner)
SELECT player.position, owner.age, team.championship, city.city_name FROM player JOIN team ON player.team = team.team_name JOIN owner ON team.ownership = owner.name JOIN city ON team.location = city.city_name WHERE player.olympic_gold_medals = 0 AND player.position != 'Backcourt' AND owner.name = 'Clay Bennett';

-- Query 11: filter5_join1 (player, team)
SELECT team.location, player.draft_year, team.ownership, player.name FROM player JOIN team ON player.team = team.team_name WHERE team.founded_year <= 1989 OR player.college = 'UCLA  ' OR player.fiba_world_cup >= 1;

-- Query 12: filter6_join2 (player, team, city, owner)
SELECT team.team_name, city.area, player.position, owner.own_year FROM player JOIN team ON player.team = team.team_name JOIN owner ON team.ownership = owner.name JOIN city ON team.location = city.city_name WHERE (player.mvp_awards <= 1 AND city.city_name = 'Miami') OR (player.draft_year < 2017 AND team.team_name = 'Detroit Pistons');

