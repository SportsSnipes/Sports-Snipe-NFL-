import os
from datetime import datetime
from zoneinfo import ZoneInfo

import nflreadpy as nfl
import psycopg


DATABASE_URL = os.environ["DATABASE_URL"]

# Historical data for model development + current season.
SEASONS = list(range(2019, 2027))

UTC = ZoneInfo("UTC")
EASTERN = ZoneInfo("America/New_York")


def clean(value):
    """Convert missing/NaN-like values to None while preserving zero."""
    if value is None:
        return None

    try:
        if value != value:
            return None
    except Exception:
        pass

    return value


def first_value(row, *names):
    """Return the first non-null field that exists."""
    for name in names:
        if name in row:
            value = clean(row[name])
            if value is not None:
                return value

    return None


def to_int(value):
    value = clean(value)

    if value is None:
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def to_float(value):
    value = clean(value)

    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def game_datetime(row):
    gameday = first_value(row, "gameday", "game_date")
    gametime = first_value(row, "gametime", "game_time")

    if gameday is None:
        return None

    try:
        gameday = str(gameday)

        if gametime:
            local_dt = datetime.fromisoformat(
                f"{gameday}T{gametime}"
            ).replace(tzinfo=EASTERN)
        else:
            local_dt = datetime.fromisoformat(
                gameday
            ).replace(tzinfo=EASTERN)

        return local_dt.astimezone(UTC)

    except Exception:
        return None


def ensure_team(cur, team_id):
    """Create a minimal team row if a referenced team does not exist."""
    team_id = clean(team_id)

    if not team_id:
        return

    cur.execute(
        """
        INSERT INTO teams (
            team_id,
            abbreviation
        )
        VALUES (%s, %s)
        ON CONFLICT (team_id)
        DO NOTHING
        """,
        (team_id, team_id),
    )


print("========================================")
print("Sports Snipe NFL - Base Data Ingestion")
print("========================================")
print(f"Seasons: {SEASONS}")
print("Loading NFL data from nflverse...")

teams = nfl.load_teams()
players = nfl.load_players()
schedules = nfl.load_schedules(SEASONS)

player_stats = nfl.load_player_stats(
    SEASONS,
    summary_level="week",
)

print("NFL data loaded.")
print(f"Teams: {len(teams)}")
print(f"Players: {len(players)}")
print(f"Games: {len(schedules)}")
print(f"Player stat rows: {len(player_stats)}")

with psycopg.connect(DATABASE_URL) as conn:
    with conn.cursor() as cur:

        # ========================================
        # TEAMS
        # ========================================

        print("Loading teams...")

        for row in teams.iter_rows(named=True):

            team_id = first_value(
                row,
                "team_abbr",
                "team_id",
            )

            if not team_id:
                continue

            team_name = first_value(
                row,
                "team_name",
                "name",
            )

            conference = first_value(
                row,
                "team_conf",
                "conference",
            )

            division = first_value(
                row,
                "team_division",
                "division",
            )

            cur.execute(
                """
                INSERT INTO teams (
                    team_id,
                    name,
                    abbreviation,
                    conference,
                    division
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (team_id)
                DO UPDATE SET
                    name = EXCLUDED.name,
                    abbreviation = EXCLUDED.abbreviation,
                    conference = EXCLUDED.conference,
                    division = EXCLUDED.division
                """,
                (
                    team_id,
                    team_name,
                    team_id,
                    conference,
                    division,
                ),
            )

        print("Teams loaded.")

        # ========================================
        # PLAYERS
        # ========================================

        print("Loading players...")

        for row in players.iter_rows(named=True):

            player_id = first_value(
                row,
                "gsis_id",
                "player_id",
            )

            if not player_id:
                continue

            team_id = first_value(
                row,
                "team_abbr",
                "team",
            )

            if team_id:
                ensure_team(cur, team_id)

            player_name = first_value(
                row,
                "display_name",
                "name",
                "full_name",
            )

            position = first_value(
                row,
                "position",
                "position_group",
            )

            jersey_number = to_int(
                first_value(
                    row,
                    "jersey_number",
                    "jersey",
                )
            )

            status = first_value(
                row,
                "status",
            )

            depth_chart_position = to_int(
                first_value(
                    row,
                    "depth_chart_position",
                )
            )

            experience = to_int(
                first_value(
                    row,
                    "years",
                    "experience",
                )
            )

            birth_date = first_value(
                row,
                "birth_date",
            )

            cur.execute(
                """
                INSERT INTO players (
                    player_id,
                    name,
                    team_id,
                    position,
                    jersey_number,
                    status,
                    depth_chart_position,
                    experience,
                    birth_date
                )
                VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s
                )
                ON CONFLICT (player_id)
                DO UPDATE SET
                    name = EXCLUDED.name,
                    team_id = EXCLUDED.team_id,
                    position = EXCLUDED.position,
                    jersey_number = EXCLUDED.jersey_number,
                    status = EXCLUDED.status,
                    depth_chart_position = EXCLUDED.depth_chart_position,
                    experience = EXCLUDED.experience,
                    birth_date = EXCLUDED.birth_date,
                    updated_at = NOW()
                """,
                (
                    player_id,
                    player_name,
                    team_id,
                    position,
                    jersey_number,
                    status,
                    depth_chart_position,
                    experience,
                    birth_date,
                ),
            )

        print("Players loaded.")

        # ========================================
        # GAMES
        # ========================================

        print("Loading games...")

        for row in schedules.iter_rows(named=True):

            game_id = first_value(row, "game_id")

            if not game_id:
                continue

            home_team = first_value(
                row,
                "home_team",
            )

            away_team = first_value(
                row,
                "away_team",
            )

            if not home_team or not away_team:
                continue

            ensure_team(cur, home_team)
            ensure_team(cur, away_team)

            total = to_float(
                first_value(
                    row,
                    "total_line",
                    "total",
                )
            )

            spread = to_float(
                first_value(
                    row,
                    "spread_line",
                    "spread",
                )
            )

            home_implied = None
            away_implied = None

            if total is not None and spread is not None:

                # NFL schedule spread_line is generally
                # from the home-team perspective.
                home_implied = (total - spread) / 2
                away_implied = (total + spread) / 2

            home_score = to_int(
                first_value(
                    row,
                    "home_score",
                )
            )

            away_score = to_int(
                first_value(
                    row,
                    "away_score",
                )
            )

            status = "scheduled"

            if (
                home_score is not None
                and away_score is not None
            ):
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
                    status
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s
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
                    status = EXCLUDED.status
                """,
                (
                    game_id,
                    to_int(row.get("season")),
                    to_int(row.get("week")),
                    game_datetime(row),
                    home_team,
                    away_team,
                    spread,
                    total,
                    home_implied,
                    away_implied,
                    home_score,
                    away_score,
                    status,
                ),
            )

        print("Games loaded.")

        # ========================================
        # PLAYER GAME STATS
        # ========================================

        print("Loading player game stats...")

        processed = 0

        for row in player_stats.iter_rows(named=True):

            player_id = first_value(
                row,
                "player_id",
                "gsis_id",
            )

            game_id = first_value(
                row,
                "game_id",
            )

            if not player_id or not game_id:
                continue

            # Make sure the player exists before
            # inserting the foreign-key relationship.
            team_id = first_value(
                row,
                "team",
                "team_abbr",
            )

            if team_id:
                ensure_team(cur, team_id)

                cur.execute(
                    """
                    UPDATE players
                    SET team_id = %s,
                        updated_at = NOW()
                    WHERE player_id = %s
                    """,
                    (
                        team_id,
                        player_id,
                    ),
                )

            season = to_int(
                first_value(row, "season")
            )

            week = to_int(
                first_value(row, "week")
            )

            snaps = to_int(
                first_value(row, "snaps")
            )

            snap_share = to_float(
                first_value(row, "snap_share")
            )

            routes = to_int(
                first_value(row, "routes")
            )

            route_share = to_float(
                first_value(row, "route_share")
            )

            targets = to_int(
                first_value(row, "targets")
            )

            target_share = to_float(
                first_value(row, "target_share")
            )

            carries = to_int(
                first_value(
                    row,
                    "carries",
                    "rushing_attempts",
                )
            )

            carry_share = to_float(
                first_value(row, "carry_share")
            )

            receptions = to_int(
                first_value(row, "receptions")
            )

            receiving_yards = to_int(
                first_value(
                    row,
                    "receiving_yards",
                    "rec_yards",
                )
            )

            receiving_tds = to_int(
                first_value(
                    row,
                    "receiving_tds",
                    "rec_tds",
                )
            )

            rush_yards = to_int(
                first_value(
                    row,
                    "rushing_yards",
                    "rush_yards",
                )
            )

            rushing_tds = to_int(
                first_value(
                    row,
                    "rushing_tds",
                    "rush_tds",
                )
            )

            pass_attempts = to_int(
                first_value(
                    row,
                    "attempts",
                    "pass_attempts",
                )
            )

            completions = to_int(
                first_value(
                    row,
                    "completions",
                    "pass_completions",
                )
            )

            pass_yards = to_int(
                first_value(
                    row,
                    "passing_yards",
                    "pass_yards",
                )
            )

            passing_tds = to_int(
                first_value(
                    row,
                    "passing_tds",
                    "pass_tds",
                )
            )

            interceptions = to_int(
                first_value(
                    row,
                    "interceptions",
                    "ints",
                )
            )

            air_yards = to_float(
                first_value(
                    row,
                    "receiving_air_yards",
                    "air_yards",
                )
            )

            yac = to_float(
                first_value(
                    row,
                    "receiving_yards_after_catch",
                    "yards_after_catch",
                    "yac",
                )
            )

            epa = to_float(
                first_value(
                    row,
                    "receiving_epa",
                    "rushing_epa",
                    "passing_epa",
                    "epa",
                )
            )

            success_rate = to_float(
                first_value(
                    row,
                    "success_rate",
                    "receiving_success_rate",
                    "rushing_success_rate",
                    "passing_success_rate",
                )
            )

            # Delete the existing player/game row first.
            # This makes the ingestion safely repeatable
            # even if the database does not have a
            # composite UNIQUE constraint.
            cur.execute(
                """
                DELETE FROM player_game_stats
                WHERE player_id = %s
                  AND game_id = %s
                """,
                (
                    player_id,
                    game_id,
                ),
            )

            cur.execute(
                """
                INSERT INTO player_game_stats (
                    player_id,
                    game_id,
                    season,
                    week,
                    snaps,
                    snap_share,
                    routes,
                    route_share,
                    targets,
                    target_share,
                    carries,
                    carry_share,
                    receptions,
                    receiving_yards,
                    receiving_tds,
                    rush_yards,
                    rushing_tds,
                    pass_attempts,
                    completions,
                    pass_yards,
                    passing_tds,
                    interceptions,
                    air_yards,
                    yac,
                    epa,
                    success_rate
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s
                )
                """,
                (
                    player_id,
                    game_id,
                    season,
                    week,
                    snaps,
                    snap_share,
                    routes,
                    route_share,
                    targets,
                    target_share,
                    carries,
                    carry_share,
                    receptions,
                    receiving_yards,
                    receiving_tds,
                    rush_yards,
                    rushing_tds,
                    pass_attempts,
                    completions,
                    pass_yards,
                    passing_tds,
                    interceptions,
                    air_yards,
                    yac,
                    epa,
                    success_rate,
                ),
            )

            processed += 1

            if processed % 5000 == 0:
                print(
                    f"Player stats processed: {processed}"
                )

        conn.commit()

print("========================================")
print("NFL BASE INGESTION COMPLETED")
print("========================================")
