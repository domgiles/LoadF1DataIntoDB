import argparse
import time
import datetime

import requests
import xmltodict
import oracledb
from rich import print
from rich_argparse import RichHelpFormatter
from rich.console import Console
from rich.traceback import install

console = Console(color_system='auto')
install()
def prepare_database(connection) -> None:
    with console.status("Setting up schema"):
        with connection.cursor() as cursor:
            cursor.execute('''
                BEGIN
                  EXECUTE IMMEDIATE 'CREATE TABLE IF NOT EXISTS team
                    (team_id    INTEGER GENERATED BY DEFAULT ON NULL AS IDENTITY,
                     name       VARCHAR2(255) NOT NULL UNIQUE,
                     points     INTEGER NOT NULL,
                     CONSTRAINT team_pk PRIMARY KEY(team_id))';

                  EXECUTE IMMEDIATE 'CREATE TABLE IF NOT EXISTS driver
                    (driver_id  INTEGER GENERATED BY DEFAULT ON NULL AS IDENTITY,
                     name       VARCHAR2(255) NOT NULL UNIQUE,
                     points     INTEGER NOT NULL,
                     team_id    INTEGER,
                     CONSTRAINT driver_pk PRIMARY KEY(driver_id),
                     CONSTRAINT driver_fk FOREIGN KEY(team_id) REFERENCES team(team_id))';

                  EXECUTE IMMEDIATE 'CREATE TABLE IF NOT EXISTS race
                     (race_id    INTEGER GENERATED BY DEFAULT ON NULL AS IDENTITY,
                     name       VARCHAR2(255) NOT NULL UNIQUE,
                     laps       INTEGER NOT NULL,
                     race_date  DATE,
                     podium     JSON,
                     CONSTRAINT race_pk PRIMARY KEY(race_id))';

                  EXECUTE IMMEDIATE 'CREATE TABLE IF NOT EXISTS DRIVER_RACE_MAP
                    (DRIVER_RACE_MAP_ID NUMBER generated by default on null as identity constraint DRIVER_RACE_MAP_PK primary key,
                    RACE_ID            NUMBER not null constraint DRIVER_RACE_MAP_FK1 references RACE,
                    DRIVER_ID          NUMBER not null constraint DRIVER_RACE_MAP_FK2 references DRIVER,
                    POSITION           NUMBER)';

                  EXECUTE IMMEDIATE 'TRUNCATE TABLE driver_race_map';
                  EXECUTE IMMEDIATE 'TRUNCATE TABLE race';
                  EXECUTE IMMEDIATE 'TRUNCATE TABLE driver';
                  EXECUTE IMMEDIATE 'TRUNCATE TABLE team';
                END;''')
    console.print("[yellow]Schema setup completed[/yellow]")

def fetch_data(connection) -> None:
    drivers_map = {}
    drivers_data_map = {}
    teams = {}
    driver_seq = 0

    with connection.cursor() as cursor:
        # Constructors
        with console.status("[yellow bold]Inserting constructors[/yellow bold]"):
            api_url = f'http://ergast.com/api/f1/{year}/constructors'
            response = requests.get(api_url)

            constructors = xmltodict.parse(response.text)
            for id, constructor in enumerate(constructors['MRData']['ConstructorTable']['Constructor']):
                cursor.execute("insert into team values(:team_id, :name, :points)", [id, constructor['Name'], 0])
                teams[constructor['Name']] = id
            connection.commit()
        print("[yellow]Inserted constructors[/yellow]")

        # Drivers
        with console.status("[yellow bold]Inserting drivers[/yellow bold]"):
            api_url = 'http://ergast.com/api/f1/current'
            response = requests.get(api_url)

            data = response.text
            d = xmltodict.parse(data)
            race_list = d['MRData']['RaceTable']['Race']
            for i, race in enumerate(race_list):
                results_url = f"http://ergast.com/api/f1/{year}/{race['@round']}/results"
                response = requests.get(results_url)
                race_data = xmltodict.parse(response.text)
                if race_data['MRData']['@total'] != "0":
                    drivers_url = f"http://ergast.com/api/f1/{year}/{race['@round']}/drivers"
                    response = requests.get(drivers_url)
                    drivers_data = xmltodict.parse(response.text)
                    for x in drivers_data['MRData']['DriverTable']['Driver']:
                        driver_id = x['@driverId']
                        api_url_driver = f'http://ergast.com/api/f1/{year}/drivers/{driver_id}/constructors'
                        driver_response = requests.get(api_url_driver)
                        constructor = xmltodict.parse(driver_response.text)
                        # print(f"{driver_seq}, {x['GivenName']} {x['FamilyName']}, {constructor['MRData']['ConstructorTable']['Constructor']['Name']}")
                        ds = 0
                        if x['@driverId'] not in drivers_map:
                            driver_seq += + 1
                            # print(f"{x['@driverId']} doesn't have an id, allocating {driver_seq}")
                            drivers_map[x['@driverId']] = driver_seq
                            ds = driver_seq
                        else:
                            ds = drivers_map[x['@driverId']]
                        drivers_data_map[x['@driverId']] = (ds, x['GivenName'], x['FamilyName'],
                                                            constructor['MRData']['ConstructorTable']['Constructor'][
                                                                'Name'])

            for row in drivers_data_map.values():
                cursor.execute('insert into driver values(:driver_id, :name, :points, :team_id)',
                               [row[0], f"{row[1]} {row[2]}", 0, teams[row[3]]])
            connection.commit()
        console.print("[yellow]Drivers inserted[/yellow]")

        with console.status("[yellow bold]Inserting circuits[/yellow bold]"):
            api_url = 'http://ergast.com/api/f1/current'
            response = requests.get(api_url)

            data = response.text
            d = xmltodict.parse(data)
            a = d['MRData']['RaceTable']['Race']
            for x in a:
                cursor.execute(
                    f"insert into race values(:race_id, :name, :laps, to_date(:race_date, 'YYYY-MM-DD'), :podium)",
                    [x['@round'], x['RaceName'], 56, x['Date'], ''])
            connection.commit()
        console.print("[yellow]Circuits inserted[/yellow]")

        with console.status("[yellow bold]Inserting results[/yellow bold]"):
            # Results
            api_url = 'http://ergast.com/api/f1/current'
            response = requests.get(api_url)

            data = response.text
            d = xmltodict.parse(data)
            race_list = d['MRData']['RaceTable']['Race']
            race_driver_map_seq = 1
            for i, race in enumerate(race_list):
                results_url = f"http://ergast.com/api/f1/{year}/{race['@round']}/results"
                response = requests.get(results_url)
                race_data = xmltodict.parse(response.text)
                if race_data['MRData']['@total'] != "0":
                    race_name = race_data['MRData']['RaceTable']['Race']['RaceName']
                    result_list = race_data['MRData']['RaceTable']['Race']['ResultsList']['Result']
                    for rr in result_list:
                        cursor.execute(
                            "insert into driver_race_map values (:driver_race_map_id, :race_id, :driver_id, :position)",
                            [race_driver_map_seq, race['@round'], drivers_map[rr['Driver']['@driverId']],
                             rr['@position']])
                        race_driver_map_seq += 1
            connection.commit()
        console.print("[yellow]Results inserted")

if __name__ == "__main__":
    print("[bold magenta]F1 Data Schema Setup[/bold magenta]")

    year = None

    parser = argparse.ArgumentParser(description='Load F1 data into database for a given year', formatter_class=RichHelpFormatter)
    parser.add_argument('-u', '--user', help='user/schema to insert data into', required=True)
    parser.add_argument('-p', '--password', help='password for user', required=True)
    parser.add_argument('-cs', '--connectstring', help='connectstring of target database', required=True)
    parser.add_argument('-y', '--year', help='the year to populate database with', required=False,
                        default=argparse.SUPPRESS)

    args = parser.parse_args()

    if 'year' not in args:
        year = datetime.date.today().year
    else:
        year = args.year

    start = time.time()
    print(f"[magenta]Started retrieving F1 data for[/magenta] [cyan bold]{year}[/cyan bold]")

    connection = oracledb.connect(user=args.user, password=args.password, dsn=args.connectstring)
    prepare_database(connection)
    fetch_data(connection)

    print("[magenta]F1 Data Loaded[/magenta]")
    print(f"[magenta]Finished in [/magenta][cyan]{time.time() - start:.2f} seconds[/cyan]")
