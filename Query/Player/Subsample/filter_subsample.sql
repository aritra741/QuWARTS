-- Query 1: 1 (player)
SELECT mvp_awards, draft_pick, fiba_world_cup FROM player WHERE fiba_world_cup <= 0;

-- Query 2: 1 (player)
SELECT position, nationality, age FROM player WHERE age < 91;

-- Query 3: 1 (player)
SELECT age, birth_date, team FROM player WHERE team = 'Phoenix Suns';

-- Query 4: 1 (team)
SELECT founded_year, ownership, team_name FROM team WHERE ownership != '  ';

-- Query 5: 1 (owner)
SELECT age, nba_team, name FROM owner WHERE nba_team != 'Cleveland Cavaliers';

-- Query 6: 1 (city)
SELECT state_name, area, city_name FROM city WHERE area = 375.78;

-- Query 7: 2 (player)
SELECT fiba_world_cup, draft_year, name FROM player WHERE draft_year <= 2017 AND fiba_world_cup > 0;

-- Query 8: 2 (player)
SELECT draft_pick, nba_championships, team FROM player WHERE draft_pick < 17 AND draft_pick >= 5;

-- Query 9: 2 (team)
SELECT founded_year, ownership, team_name FROM team WHERE ownership != 'Harris Blitzer Sports & Entertainment (HBSE)  ' AND founded_year >= 1967;

-- Query 10: 2 (owner)
SELECT age, nba_team, name FROM owner WHERE nba_team != 'Golden State Warriors' AND age >= 66;

-- Query 11: 2 (city)
SELECT state_name, area, city_name FROM city WHERE area != 1314.80 AND population = 887642;

-- Query 12: 3 (player)
SELECT team, nationality, mvp_awards FROM player WHERE mvp_awards < 1 OR birth_date = '1995/10/2';

-- Query 13: 3 (team)
SELECT founded_year, team_name, location FROM team WHERE founded_year < 1949 OR location != 'Oklahoma City';

-- Query 14: 3 (owner)
SELECT age, name, nationality FROM owner WHERE age < 63 OR nationality != 'Israeli-American';

-- Query 15: 3 (city)
SELECT state_name, city_name, population FROM city WHERE state_name != 'Indiana' OR population != 372624;

-- Query 16: 6 (player)
SELECT nationality, birth_date, age FROM player WHERE (birth_date != '1994/6/6' AND nationality = 'Dutch  ') OR (nba_championships <= 2 AND age > 91);

-- Query 17: 6 (team)
SELECT location, founded_year, team_name FROM team WHERE (founded_year >= 1949 AND founded_year = 1949) OR (ownership != 'Paul Allen' AND ownership != 'Glen Taylor');

-- Query 18: 6 (owner)
SELECT nationality, age, name FROM owner WHERE (age >= 63 AND age = 63) OR (nba_team != 'Indiana Pacers' AND nba_team != 'New Orleans Pelicans');
