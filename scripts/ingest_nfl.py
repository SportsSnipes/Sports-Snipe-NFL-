import os
from datetime import datetime
from zoneinfo import ZoneInfo

import nflreadpy as nfl
import psycopg


DATABASE_URL = os.environ["DATABASE_URL"]
SEASONS = list(range(2019, 2027))


def value(row, *names):
    for name in names:
        if name in row.index:
            return row[name]
    return None


def clean(value_):
    if value_ is None:
        return None

    try:
        if value_ != value_:
            return None
    except Exception:
        pass

    return value_


def game_datetime(row):
    gameday = clean(value(row, "gameday", "game_date"))
    gametime = clean(value(row, "gametime", "game_time"))

    if not gameday:
        return None

    try:
        if gametime:
            local_dt = datetime.fromisoformat(
                f"{gameday}T{gametime}"
            ).replace(tzinfo=ZoneInfo("America/New_York"))
        else:
            local_dt = datetime.fromisoformat(gameday).replace(
                tzinfo=ZoneInfo("America/New_York")
            )

        return local_dt.astimezone(ZoneInfo("UTC"))
    except Exception:
        return None


print("Loading NFL data from nflverse...")

teams = nfl.load_teams()
players = nfl.load_players()
schedules = nfl.load_schedules(SEASONS)
player_stats = nfl.load_player_stats(
    SEASONS,
    summary_level="week"
)

print("NFL data loaded.")

with psycopg.connect(DATABASE_URL) as conn:
    with conn.cursor() as cur:

        # -------------------------
        # TEAMS
        # -------------------------
        for row in teams.iter_rows(named=True):
            team_id = clean(row.get("team_abbr"))
            if not team_id:
                continue

            cur.execute(
                """
                INSERT INTO teams (
                    team_id,
                    team_name,
                    abbreviation,
                    conference,
                    division,
                    updated_at
                )
                VALUES (%s,%s,%s,%s,%s,NOW())
                ON CONFLICT (team_id)
                DO UPDATE SET
                    team_name = EXCLUDED.team_name,
                    abbreviation = EXCLUDED.abbreviation,
                    conference = EXCLUDED.conference,
                    division = EXCLUDED.division,
                    updated_at = NOW()
                """,
                (
                    team_id,
                    clean(row.get("team_name")),
                    team_id,
                    clean(row.get("team_conf")),
                    clean(row.get("team_division")),
                ),
            )

        # -------------------------
        # PLAYERS
        # -------------------------
        for row in players.iter_rows(named=True):
            player_id = clean(row.get("gsis_id"))

            if not player_id:
                player_id = clean(row.get("player_id"))

            if not player_id:
                continue

            team_id = clean(
                row.get("team_abbr")
                or row.get("team")
            )

            if team_id:
                cur.execute(
                    """
                    INSERT INTO teams (
                        team_id,
                        abbreviation,
                        updated_at
                    )
                    VALUES (%s,%s,NOW())
                    ON CONFLICT (team_id)
                    DO NOTHING
                    """,
                    (team_id, team_id),
                )

            first_name = clean(row.get("first_name"))
            last_name = clean(row.get("last_name"))

            player_name = clean(row.get("display_name"))

            if not player_name:
                player_name = " ".join(
                    x for x in [first_name, last_name] if x
                )

            cur.execute(
                """
                INSERT INTO players (
                    player_id,
                    player_name,
                    first_name,
                    last_name,
                    position,
                    team_id,
                    jersey_number,
                    status,
                    depth_chart_position,
                    experience,
                    updated_at
                )
                VALUES (
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW()
                )
                ON CONFLICT (player_id)
                DO UPDATE SET
                    player_name = EXCLUDED.player_name,
                    first_name = EXCLUDED.first_name,
                    last_name = EXCLUDED.last_name,
                    position = EXCLUDED.position,
                    team_id = EXCLUDED.team_id,
                    jersey_number = EXCLUDED.jersey_number,
                    status = EXCLUDED.status,
                    depth_chart_position = EXCLUDED.depth_chart_position,
                    experience = EXCLUDED.experience,
                    updated_at = NOW()
                """,
                (
                    player_id,
                    player_name,
                    first_name,
                    last_name,
                    clean(row.get("position")),
                    team_id,
                    clean(row.get("jersey_number")),
                    clean(row.get("status")),
                    clean(row.get("depth_chart_position")),
                    clean(row.get("years")),
                ),
            )

        # -------------------------
        # GAMES
        # -------------------------
        for row in schedules.iter_rows(named=True):
            game_id = clean(row.get("game_id"))

            if not game_id:
                continue

            home_team = clean(row.get("home_team"))
            away_team = clean(row.get("away_team"))

            if not home_team or not away_team:
                continue

            for team_id in [home_team, away_team]:
                cur.execute(
                    """
                    INSERT INTO teams (
                        team_id,
                        abbreviation,
                        updated_at
                    )
                    VALUES (%s,%s,NOW())
                    ON CONFLICT (team_id)
                    DO NOTHING
                    """,
                    (team_id, team_id),
                )

            total = clean(row.get("total_line"))
            spread = clean(row.get("spread_line"))

            home_implied = None
            away_implied = None

            if total is not None and spread is not None:
                try:
                    home_implied = (float(total) - float(spread)) / 2
                    away_implied = (float(total) + float(spread)) / 2
                except Exception:
                    pass

            status = "scheduled"

            if row.get("result") is not None:
                status = "final"

            cur.execute(
                """
                INSERT INTO games (
                    game_id,
                    season,
                    week,
                    game_date,
                    home_team_id,
                    away_team_id,
                    spread,
                    total,
                    home_implied_points,
                    away_implied_points,
                    home_score,
                    away_score,
                    status,
                    updated_at
                )
                VALUES (
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW()
                )
                ON CONFLICT (game_id)
                DO UPDATE SET
                    season = EXCLUDED.season,
                    week = EXCLUDED.week,
                    game_date = EXCLUDED.game_date,
                    home_team_id = EXCLUDED.home_team_id,
                    away_team_id = EXCLUDED.away_team_id,
                    spread = EXCLUDED.spread,
                    total = EXCLUDED.total,
                    home_implied_points = EXCLUDED.home_implied_points,
                    away_implied_points = EXCLUDED.away_implied_points,
                    home_score = EXCLUDED.home_score,
                    away_score = EXCLUDED.away_score,
                    status = EXCLUDED.status,
                    updated_at = NOW()
                """,
                (
                    game_id,
                    clean(row.get("season")),
                    clean(row.get("week")),
                    game_datetime(row),
                    home_team,
                    away_team,
                    spread,
                    total,
                    home_implied,
                    away_implied,
                    clean(row.get("home_score")),
                    clean(row.get("away_score")),
                    status,
                ),
            )

        # -------------------------
        # PLAYER GAME STATS
        # -------------------------
        for row in player_stats.iter_rows(named=True):

            player_id = clean(
                row.get("player_id")
                or row.get("gsis_id")
            )

            game_id = clean(row.get("game_id"))

            if not player_id or not game_id:
                continue

            team_id = clean(row.get("team"))

            if team_id:
                cur.execute(
                    """
                    INSERT INTO teams (
                        team_id,
                        abbreviation,
                        updated_at
                    )
                    VALUES (%s,%s,NOW())
                    ON CONFLICT (team_id)
                    DO NOTHING
                    """,
                    (team_id, team_id),
                )

                cur.execute(
                    """
                    UPDATE players
                    SET team_id = %s,
                        updated_at = NOW()
                    WHERE player_id = %s
                    """,
                    (team_id, player_id),
                )

            carries = clean(
                row.get("carries")
                or row.get("rushing_attempts")
            )

            rushing_yards = clean(
                row.get("rushing_yards")
                or row.get("rush_yards")
            )

            receptions = clean(row.get("receptions"))

            receiving_yards = clean(
                row.get("receiving_yards")
                or row.get("rec_yards")
            )

            targets = clean(row.get("targets"))

            pass_attempts = clean(
                row.get("attempts")
                or row.get("pass_attempts")
            )

            pass_completions = clean(
                row.get("completions")
                or row.get("pass_completions")
            )

            pass_yards = clean(
                row.get("passing_yards")
                or row.get("pass_yards")
            )

            rushing_tds = clean(
                row.get("rushing_tds")
                or row.get("rush_tds")
            ) or 0

            receiving_tds = clean(
                row.get("receiving_tds")
                or row.get("rec_tds")
            ) or 0

            passing_tds = clean(
                row.get("passing_tds")
                or row.get("pass_tds")
            ) or 0

            touchdowns = (
                float(rushing_tds)
                + float(receiving_tds)
                + float(passing_tds)
            )

            air_yards = clean(
                row.get("receiving_air_yards")
                or row.get("air_yards")
            )

            yac = clean(
                row.get("receiving_yards_after_catch")
                or row.get("yards_after_catch")
            )

            epa = clean(
                row.get("receiving_epa")
                or row.get("rushing_epa")
                or row.get("passing_epa")
            )

            cur.execute(
                """
                INSERT INTO player_game_stats (
                    player_id,
                    game_id,
                    carries,
                    carry_share,
                    rush_yards,
                    targets,
                    target_share,
                    receptions,
                    receiving_yards,
                    pass_attempts,
                    pass_completions,
                    pass_yards,
                    touchdowns,
                    air_yards,
                    yards_after_catch,
                    epa
                )
                VALUES (
                    %s,%s,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s,%s,%s,%s,%s,%s
                )
                ON CONFLICT (player_id, game_id)
                DO UPDATE SET
                    carries = EXCLUDED.carries,
                    rush_yards = EXCLUDED.rush_yards,
                    targets = EXCLUDED.targets,
                    receptions = EXCLUDED.receptions,
                    receiving_yards = EXCLUDED.receiving_yards,
                    pass_attempts = EXCLUDED.pass_attempts,
                    pass_completions = EXCLUDED.pass_completions,
                    pass_yards = EXCLUDED.pass_yards,
                    touchdowns = EXCLUDED.touchdowns,
                    air_yards = EXCLUDED.air_yards,
                    yards_after_catch = EXCLUDED.yards_after_catch,
                    epa = EXCLUDED.epa
                """,
                (
                    player_id,
                    game_id,
                    carries,
                    None,
                    rushing_yards,
                    targets,
                    None,
                    receptions,
                    receiving_yards,
                    pass_attempts,
                    pass_completions,
                    pass_yards,
                    touchdowns,
                    air_yards,
                    yac,
                    epa,
                ),
            )

        conn.commit()

print("NFL ingestion completed successfully.")
