SELECT t.team_name, t.founded_year, t.championship, SUM(p.nba_championships)
FROM team t
LEFT JOIN player p ON t.team_name = p.team
WHERE t.location = 'Los Angeles' OR t.location = 'Boston'
   OR t.championship > 15
   OR p.nba_championships < 12
GROUP BY t.team_name;

SELECT position, college, COUNT(*)
FROM player
WHERE position = 'Frontcourt' 
  OR college = 'University of Minnesota'
GROUP BY position, college;

SELECT draft_year, MIN(birth_date), AVG(draft_pick)
FROM player
WHERE birth_date > '1990/01/01'
  AND draft_pick < 30
GROUP BY draft_year;

SELECT nationality, AVG(age), SUM(mvp_awards), SUM(olympic_gold_medals), SUM(fiba_world_cup)
FROM player
WHERE nationality = 'Serbian'
   OR nationality = 'Greek and Nigerian'
   OR mvp_awards < 7
   OR olympic_gold_medals <= 3
   OR fiba_world_cup <= 2
GROUP BY nationality;

SELECT t.location, c.state_name, MAX(c.population), SUM(c.area), AVG(c.gdp)
FROM team t
JOIN city c ON t.location = c.city_name
WHERE c.area < 340 
   OR c.population > 1000000
   OR c.gdp > 200000
GROUP BY t.location;

SELECT o.nba_team, o.name, o.age, MIN(o.own_year), t.ownership
FROM owner o
JOIN team t ON o.nba_team = t.team_name
WHERE o.own_year > 2010.0 
   OR o.age > 80
GROUP BY o.nba_team;

SELECT nationality, AVG(age), COUNT(*)
FROM owner
WHERE nationality = 'American'
GROUP BY nationality;

SELECT p.name, t.team_name, c.city_name
FROM player p
JOIN team t ON p.team = t.team_name
JOIN city c ON t.location = c.city_name
WHERE p.name = 'Anthony Marshon Davis Jr.' 
   OR p.name = 'LeBron Raymone James Sr.';

SELECT t.team_name, t.championship, t.founded_year, o.name, o.nationality, AVG(o.age)
FROM team t
JOIN owner o ON t.ownership = o.name
WHERE t.championship > 5
   OR o.own_year > 2000
GROUP BY t.team_name;

SELECT p.name, p.nationality, t.team_name, o.name, MAX(p.mvp_awards)
FROM player p
JOIN team t ON p.team = t.team_name
JOIN owner o ON t.ownership = o.name
WHERE p.age > 25
   OR o.nationality = 'American'
GROUP BY p.nationality;

SELECT t.team_name, t.location, c.city_name, c.state_name, o.name, SUM(t.championship)
FROM team t
JOIN city c ON t.location = c.city_name
JOIN owner o ON t.ownership = o.name
WHERE c.population > 500000
   OR o.own_year > 2005
GROUP BY t.team_name;

SELECT p.name, p.nationality, t.team_name, o.name, c.city_name, c.state_name, COUNT(*)
FROM player p
JOIN team t ON p.team = t.team_name
JOIN owner o ON t.ownership = o.name
JOIN city c ON t.location = c.city_name
WHERE p.draft_year > 2000
   OR c.population > 1000000
GROUP BY t.team_name;

-- S3
SELECT draft_pick FROM player;

-- S4
SELECT team, name, mvp_awards, birth_date FROM player;

-- S5
SELECT olympic_gold_medals FROM player;

-- S6
SELECT nba_championships, name, fiba_world_cup FROM player;

-- S7
SELECT olympic_gold_medals, birth_date FROM player;

-- S8
SELECT fiba_world_cup, draft_pick, mvp_awards, name FROM player;

-- S9
SELECT ownership, team_name, championship, founded_year FROM team;

-- S10
SELECT founded_year, location, team_name, championship FROM team;

-- F3
SELECT state_name, city_name, population FROM city WHERE state_name != 'Indiana' OR population != 372624;

-- F4
SELECT gdp, area, state_name FROM city WHERE area = 976.15 AND gdp != 473000 AND area = 375.78 AND population = 808988;

-- F5
SELECT gdp, state_name, population FROM city WHERE state_name != 'Ontario' OR city_name = 'Minneapolis' OR gdp != 102000000000 OR gdp IS NOT NULL;

-- F6
SELECT population, state_name, city_name FROM city WHERE (state_name = 'Minnesota' AND population = 887642) OR (area != 976.15 AND area != 976.15);

-- F9
SELECT age, name, nationality FROM owner WHERE age < 63 OR nationality != 'Israeli-American';

-- F10
SELECT own_year, nba_team, age FROM owner WHERE nba_team = 'Miami Heat' AND own_year != 2008 AND nationality != 'American  ' AND nationality != 'American  ';

-- F11
SELECT own_year, age, nationality FROM owner WHERE age <= 76 OR name = 'Joseph Chung-Hsin Tsai' OR own_year != 2012 OR own_year = 2017;

-- F12
SELECT nationality, age, name FROM owner WHERE (age >= 63 AND age = 63) OR (nba_team != 'Indiana Pacers' AND nba_team != 'New Orleans Pelicans');

-- F15
SELECT mvp_awards, draft_pick, name FROM player WHERE mvp_awards >= 1;

-- F16
SELECT age, birth_date, team FROM player WHERE team = 'Phoenix Suns';

-- F17
SELECT fiba_world_cup, nba_championships, birth_date FROM player WHERE nba_championships = 0;

-- F18
SELECT college, birth_date, draft_year FROM player WHERE birth_date = '1973/11/25';

-- F19
SELECT fiba_world_cup, draft_year, name FROM player WHERE draft_year <= 2017 AND fiba_world_cup > 0;

-- F20
SELECT position, nba_championships, fiba_world_cup FROM player WHERE fiba_world_cup > 0 AND nationality != 'French  ';

-- F21
SELECT draft_pick, nba_championships, team FROM player WHERE draft_pick < 17 AND draft_pick >= 5;

-- F22
SELECT age, birth_date, college FROM player WHERE age > 91 AND mvp_awards > 0;

-- F23
SELECT fiba_world_cup, birth_date, nba_championships FROM player WHERE birth_date != '1959/6/10' AND birth_date != '1964/2/15';

-- F24
SELECT olympic_gold_medals, position, birth_date FROM player WHERE olympic_gold_medals < 1 AND draft_pick = 17;

-- F25
SELECT team, nationality, mvp_awards FROM player WHERE mvp_awards < 1 OR birth_date = '1995/10/2';

-- F26
SELECT draft_year, age, fiba_world_cup FROM player WHERE draft_year <= 2017 OR olympic_gold_medals >= 0;

-- F27
SELECT fiba_world_cup, nationality, college FROM player WHERE college = 'UCLA  ' OR birth_date != '1971/12/3';

-- F28
SELECT olympic_gold_medals, fiba_world_cup, birth_date FROM player WHERE birth_date = '1994/4/25' OR position != 'Frontcourt';

-- F29
SELECT college, draft_pick, fiba_world_cup FROM player WHERE draft_pick <= 5 OR college = 'Wake Forest University';

-- F30
SELECT olympic_gold_medals, nba_championships, age FROM player WHERE olympic_gold_medals > 1 OR position != 'Frontcourt';

-- F31
SELECT fiba_world_cup, draft_pick, draft_year FROM player WHERE draft_pick >= 17 AND age >= 47 AND mvp_awards <= 0 AND mvp_awards < 1;

-- F32
SELECT name, nba_championships, college FROM player WHERE nba_championships > 2 AND olympic_gold_medals >= 0 AND olympic_gold_medals != 1 AND name != 'Toby Kimball  ';

-- F33
SELECT age, olympic_gold_medals, mvp_awards FROM player WHERE olympic_gold_medals >= 1 AND college = 'UCLA  ' AND draft_year > 2012 AND fiba_world_cup >= 0;

-- F34
SELECT draft_pick, olympic_gold_medals, position FROM player WHERE olympic_gold_medals > 0 AND birth_date != '1943/12/23' AND nba_championships < 2 AND birth_date = '1992/12/17';

-- F35
SELECT fiba_world_cup, birth_date, draft_pick FROM player WHERE birth_date != '1950/1/29' AND college = 'University of Florida' AND age != 47 AND name = 'Walter Berry ';

-- F36
SELECT nationality, draft_pick, team FROM player WHERE nationality != 'Croatian  ' AND olympic_gold_medals < 0 AND olympic_gold_medals != 0 AND mvp_awards = 0;

-- F37
SELECT draft_pick, age, position FROM player WHERE age <= 66 OR birth_date = '1997/8/7' OR college != 'Duke University' OR nba_championships = 2;

-- F38
SELECT olympic_gold_medals, college, age FROM player WHERE age > 47 OR name != 'Fran Curran Francis Hugh Curran Sr.' OR name = 'Dewayne "D. J." White, Jr.' OR fiba_world_cup = 1;

-- F39
SELECT nba_championships, name, olympic_gold_medals FROM player WHERE nba_championships = 0 OR team != 'Miami Heat  ' OR nationality = ' ' OR team != 'Philadelphia 76ers  ';

-- F40
SELECT draft_year, age, nationality FROM player WHERE age <= 91 OR team = 'Guaros de Lara' OR mvp_awards = 0 OR olympic_gold_medals > 1;

-- F41
SELECT olympic_gold_medals, age, team FROM player WHERE age >= 47 OR team != 'San Antonio Spurs' OR nba_championships <= 0 OR nba_championships < 0;

-- F42
SELECT position, nationality, olympic_gold_medals FROM player WHERE position != 'Frontcourt' OR draft_pick > 5 OR olympic_gold_medals < 0 OR mvp_awards = 0;

-- F43
SELECT team, nationality, fiba_world_cup FROM player WHERE (nationality = 'American-Venezuelan  ' AND position = 'Frontcourt') OR (draft_pick >= 17 AND draft_pick >= 17);

-- F44
SELECT nationality, olympic_gold_medals, fiba_world_cup FROM player WHERE (fiba_world_cup != 0 AND name = 'Erick Strickland  ') OR (birth_date != '1973/11/25' AND nba_championships >= 0);

-- F45
SELECT college, age, position FROM player WHERE (age < 47 AND olympic_gold_medals <= 1) OR (team = 'Milwaukee Hawks  ' AND college = 'University of Florida  ');

-- F46
SELECT nationality, name, draft_year FROM player WHERE (draft_year != 2017 AND nationality != 'Croatian  ') OR (name = 'Donta Hall  ' AND nba_championships != 0);

-- F47
SELECT birth_date, olympic_gold_medals, mvp_awards FROM player WHERE (birth_date = '1973/11/25' AND olympic_gold_medals != 0) OR (team = 'Miami Heat' AND nationality = 'Canadian');

-- F48
SELECT nationality, birth_date, age FROM player WHERE (birth_date != '1994/6/6' AND nationality = 'Dutch  ') OR (nba_championships <= 2 AND age > 91);

-- F51
SELECT founded_year, ownership, team_name FROM team WHERE ownership != 'Harris Blitzer Sports & Entertainment (HBSE)  ' AND founded_year >= 1967;

-- F52
SELECT championship, founded_year, location FROM team WHERE location = 'Brooklyn' AND location = 'Memphis';

-- F53
SELECT founded_year, team_name, location FROM team WHERE founded_year < 1949 OR location != 'Oklahoma City';

-- F54
SELECT ownership, founded_year, championship FROM team WHERE ownership != 'Professional Basketball Club LLC, a group of Oklahoma City investors led by Clay Bennett  ' OR ownership != 'Jerry Buss (from 1979)';

-- F55
SELECT championship, ownership, founded_year FROM team WHERE ownership = 'James L. Dolan' AND ownership = 'Glen Taylor' AND location = 'Houston' AND location != 'Brooklyn';

-- F56
SELECT team_name, championship, location FROM team WHERE team_name = 'Golden State Warriors' AND founded_year >= 1989 AND ownership != 'Joseph Tsai' AND location != 'Charlotte';

-- F57
SELECT championship, founded_year, location FROM team WHERE founded_year <= 1978 OR team_name = 'Dallas Mavericks' OR location != 'Minneapolis' OR team_name != 'Miami Heat';

-- F58
SELECT team_name, founded_year, ownership FROM team WHERE founded_year > 1967 OR team_name != 'Charlotte Hornets' OR team_name = 'Detroit Pistons' OR founded_year >= 1989;

-- F59
SELECT location, founded_year, team_name FROM team WHERE (founded_year >= 1949 AND founded_year = 1949) OR (ownership != 'Paul Allen' AND ownership != 'Glen Taylor');

-- F60
SELECT location, founded_year, team_name FROM team WHERE (founded_year > 1989 AND ownership != 'Gabe Plotkin and Rick Schnall') OR (ownership = ' ' AND founded_year = 1967);

-- A2
SELECT nationality, COUNT(*) AS count_all FROM player GROUP BY nationality;

-- A4
SELECT nationality, MAX(age) AS max_age FROM player GROUP BY nationality;

-- A5
SELECT nationality, COUNT(*) AS count_all FROM player GROUP BY nationality;

-- A6
SELECT nationality, MIN(age) AS min_age FROM player GROUP BY nationality;

-- A7
SELECT nationality, AVG(age) AS avg_age FROM player GROUP BY nationality;

-- A8
SELECT nationality, MIN(age) AS min_age FROM owner GROUP BY nationality;

-- A9
SELECT nationality, COUNT(*) AS count_all FROM owner GROUP BY nationality;

-- A10
SELECT nationality, AVG(age) AS avg_age FROM owner GROUP BY nationality;

-- J3
SELECT team.ownership, player.name, player.mvp_awards, team.championship FROM player JOIN team ON player.team = team.team_name;

-- J4
SELECT player.nationality, player.age, team.location, team.team_name FROM player JOIN team ON player.team = team.team_name;

-- J5
SELECT city.city_name, city.population, team.founded_year, team.location FROM team JOIN city ON team.location = city.city_name;

-- J6
SELECT city.state_name, city.area, team.founded_year, team.championship FROM team JOIN city ON team.location = city.city_name;

-- J7
SELECT owner.nba_team, team.location, team.founded_year, owner.name FROM team JOIN owner ON team.ownership = owner.name;

-- J8
SELECT owner.name, owner.own_year, team.team_name, team.founded_year FROM team JOIN owner ON team.ownership = owner.name;

-- J9
SELECT owner.nba_team, team.team_name, team.founded_year, owner.nationality FROM team JOIN owner ON team.ownership = owner.name;

-- J10
SELECT owner.nba_team, team.location, owner.name, team.team_name FROM team JOIN owner ON team.ownership = owner.name;

-- J11
SELECT player.fiba_world_cup, player.name, team.team_name, team.ownership, city.state_name FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name;

-- J12
SELECT city.state_name, player.name, player.college, team.founded_year, team.team_name FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name;

-- J13
SELECT city.population, player.position, city.city_name, team.founded_year, player.name FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name;

-- J14
SELECT team.championship, city.gdp, player.team, team.team_name, city.city_name FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name;

-- J15
SELECT owner.name, team.founded_year, team.location, owner.age, player.nationality FROM player JOIN team ON player.team = team.team_name JOIN owner ON team.ownership = owner.name;

-- J16
SELECT player.college, owner.name, player.position, team.championship, player.fiba_world_cup FROM player JOIN team ON player.team = team.team_name JOIN owner ON team.ownership = owner.name;

-- J17
SELECT team.championship, owner.age, player.team, player.draft_year, player.age FROM player JOIN team ON player.team = team.team_name JOIN owner ON team.ownership = owner.name;

-- J18
SELECT player.nationality, player.olympic_gold_medals, team.location, owner.nba_team, player.draft_pick FROM player JOIN team ON player.team = team.team_name JOIN owner ON team.ownership = owner.name;

-- J19
SELECT city.state_name, player.olympic_gold_medals, team.team_name, player.college, owner.own_year FROM player JOIN team ON player.team = team.team_name JOIN owner ON team.ownership = owner.name JOIN city ON team.location = city.city_name;

-- J20
SELECT team.championship, owner.nationality, city.population, player.nationality, player.college FROM player JOIN team ON player.team = team.team_name JOIN owner ON team.ownership = owner.name JOIN city ON team.location = city.city_name;

-- M3
SELECT nationality, MIN(age) AS min_age FROM owner WHERE nba_team != 'Cleveland Cavaliers' GROUP BY nationality;

-- M6
SELECT nationality, MAX(mvp_awards) AS max_mvp_awards FROM player WHERE draft_year > 2012 OR nba_championships > 0 GROUP BY nationality;

-- M7
SELECT nationality, AVG(fiba_world_cup) AS avg_fiba_world_cup FROM player WHERE team = 'New York Knicks  ' OR nba_championships <= 0 OR fiba_world_cup < 0 GROUP BY nationality;

-- M8
SELECT position, MIN(fiba_world_cup) AS min_fiba_world_cup FROM player WHERE (fiba_world_cup < 0 AND mvp_awards <= 0) OR (age < 91 AND fiba_world_cup >= 0) GROUP BY position;

-- M11
SELECT player.nationality, AVG(player.mvp_awards) AS avg_player_mvp_awards FROM player JOIN team ON player.team = team.team_name WHERE player.age <= 66 GROUP BY player.nationality;

-- M12
SELECT owner.nationality, MAX(player.nba_championships) AS max_player_nba_championships FROM player JOIN team ON player.team = team.team_name JOIN owner ON team.ownership = owner.name JOIN city ON team.location = city.city_name WHERE city.population = 1603797 AND city.gdp != 518.5 AND player.birth_date = '1990/8/17' GROUP BY owner.nationality;

-- M13
SELECT player.position, AVG(player.fiba_world_cup) AS avg_player_fiba_world_cup FROM player JOIN team ON player.team = team.team_name WHERE player.nba_championships < 0 OR player.age >= 47 OR player.nationality = 'Greek-American  ' GROUP BY player.position;

-- M14
SELECT player.position, AVG(player.age) AS avg_player_age FROM player JOIN team ON player.team = team.team_name JOIN owner ON team.ownership = owner.name JOIN city ON team.location = city.city_name WHERE (player.nba_championships <= 2 AND player.mvp_awards < 1) OR (player.olympic_gold_medals != 0 AND player.nationality = 'American-born naturalized Azerbaijani  ') GROUP BY player.position;

-- M15
SELECT player.position, AVG(player.fiba_world_cup) AS avg_player_fiba_world_cup FROM player JOIN team ON player.team = team.team_name WHERE player.olympic_gold_medals = 0 GROUP BY player.position;

-- M16
SELECT player.position, AVG(player.olympic_gold_medals) AS avg_player_olympic_gold_medals FROM player JOIN team ON player.team = team.team_name JOIN owner ON team.ownership = owner.name JOIN city ON team.location = city.city_name WHERE owner.nationality = 'Israeli-American' AND team.founded_year > 1989 GROUP BY player.position;

-- M17
SELECT player.nationality, COUNT(*) AS count_all FROM player JOIN team ON player.team = team.team_name WHERE player.nationality = 'Cameroonian-American' OR player.birth_date = '1972/3/6' GROUP BY player.nationality;

-- M18
SELECT player.nationality, SUM(team.championship) AS sum_team_championship FROM player JOIN team ON player.team = team.team_name JOIN owner ON team.ownership = owner.name JOIN city ON team.location = city.city_name WHERE player.draft_year <= 1990 AND player.position = 'Backcourt' AND player.draft_pick <= 35 GROUP BY player.nationality;

-- M19
SELECT player.nationality, SUM(player.mvp_awards) AS sum_player_mvp_awards FROM player JOIN team ON player.team = team.team_name WHERE player.team != 'Milwaukee Bucks' OR player.nba_championships > 2 OR team.founded_year != 1949 GROUP BY player.nationality;

-- M20
SELECT player.position, MIN(team.championship) AS min_team_championship FROM player JOIN team ON player.team = team.team_name JOIN owner ON team.ownership = owner.name JOIN city ON team.location = city.city_name WHERE (team.location = 'Brooklyn' AND player.nba_championships < 0) OR (player.team != 'Milwaukee Hawks  ' AND player.draft_pick != 35) GROUP BY player.position;

-- M22
SELECT nationality, SUM(age) AS sum_age FROM owner WHERE age != 76 AND nba_team != 'Houston Rockets' GROUP BY nationality;

-- M23
SELECT nationality, COUNT(age) AS count_age FROM owner WHERE name = 'Tom Gores  ' OR own_year >= 1994 GROUP BY nationality;

-- M24
SELECT nationality, MAX(age) AS max_age FROM owner WHERE own_year = 2012 AND nba_team = 'New York Knicks' AND age <= 88 GROUP BY nationality;

-- M25
SELECT nationality, AVG(age) AS avg_age FROM owner WHERE nationality = 'Taiwanese-Canadian' OR own_year <= 2012 OR nba_team != 'Dallas Mavericks' GROUP BY nationality;

-- M26
SELECT nationality, MIN(age) AS min_age FROM owner WHERE (nba_team != 'Chicago Bulls' AND nationality = 'Israeli-American') OR (name = 'Steven Anthony Ballmer' AND age <= 63) GROUP BY nationality;

-- M29
SELECT nationality, COUNT(age) AS count_age FROM player WHERE name = 'Antonius Cleveland  ' OR nba_championships >= 0 GROUP BY nationality;

-- M30
SELECT position, MAX(mvp_awards) AS max_mvp_awards FROM player WHERE nba_championships = 0 AND draft_year > 2012 AND nba_championships != 2 GROUP BY position;

-- M31
SELECT team, AVG(fiba_world_cup) AS avg_fiba_world_cup FROM player WHERE team = 'New York Knicks  ' OR nba_championships <= 0 OR fiba_world_cup > 0 GROUP BY team;

-- M32
SELECT team, MIN(fiba_world_cup) AS min_fiba_world_cup FROM player WHERE (fiba_world_cup > 0 AND mvp_awards <= 0) OR (age < 91 AND fiba_world_cup >= 0) GROUP BY team;

-- M35
SELECT player.team, team.location, player.college, team.team_name FROM player JOIN team ON player.team = team.team_name WHERE player.nba_championships > 0 OR player.nationality != 'American-Venezuelan';

-- M36
SELECT owner.age, city.area, team.location, player.team FROM player JOIN team ON player.team = team.team_name JOIN owner ON team.ownership = owner.name JOIN city ON team.location = city.city_name WHERE player.college = 'University of Kentucky' AND city.population != 383997 AND team.founded_year >= 1949;

-- M37
SELECT player.mvp_awards, team.championship, player.draft_year, team.team_name FROM player JOIN team ON player.team = team.team_name WHERE team.location != 'Los Angeles' OR team.founded_year < 1967 OR player.birth_date = '1971/10/2';

-- M38
SELECT owner.nba_team, team.ownership, player.fiba_world_cup, city.city_name FROM player JOIN team ON player.team = team.team_name JOIN owner ON team.ownership = owner.name JOIN city ON team.location = city.city_name WHERE (owner.nationality != 'American  ' AND player.olympic_gold_medals <= 1) OR (player.position = 'Backcourt' AND player.draft_year != 1990);

-- M39
SELECT team.location, player.nba_championships, team.team_name, player.team FROM player JOIN team ON player.team = team.team_name WHERE player.nba_championships < 0;

-- M40
SELECT player.nationality, owner.nationality, city.population, team.championship FROM player JOIN team ON player.team = team.team_name JOIN owner ON team.ownership = owner.name JOIN city ON team.location = city.city_name WHERE player.position != 'Backcourt' AND player.draft_year >= 1990;

-- M41
SELECT player.name, player.position, team.championship, team.founded_year FROM player JOIN team ON player.team = team.team_name WHERE player.name = 'Kobe Bean Bryant' OR player.fiba_world_cup >= 0;

-- M42
SELECT player.position, owner.age, team.championship, city.city_name FROM player JOIN team ON player.team = team.team_name JOIN owner ON team.ownership = owner.name JOIN city ON team.location = city.city_name WHERE player.olympic_gold_medals = 0 AND player.position != 'Backcourt' AND owner.name = 'Clay Bennett';

-- M43
SELECT team.location, player.draft_year, team.ownership, player.name FROM player JOIN team ON player.team = team.team_name WHERE team.founded_year <= 1989 OR player.college = 'UCLA  ' OR player.fiba_world_cup >= 1;

-- M44
SELECT team.team_name, city.area, player.position, owner.own_year FROM player JOIN team ON player.team = team.team_name JOIN owner ON team.ownership = owner.name JOIN city ON team.location = city.city_name WHERE (player.mvp_awards <= 1 AND city.city_name = 'Miami') OR (player.draft_year < 2017 AND team.team_name = 'Detroit Pistons');
