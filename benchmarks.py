"""
Reference data and scoring logic for the athletic profile report: best-fit
sport, a specific position within that sport, a player archetype, and
percentile benchmarks for each test.

The percentile benchmarks and sport-weighting profiles below are reasonable
general-population estimates for a relative self-comparison — not sourced
from a specific published study.
"""
import math

# Approximate population mean/stdev per test, used to compute a percentile
# rank via the standard normal CDF. Form-based tests use the 0-100 quality
# score; jump uses raw height in cm (the same unit shown in the UI).
BENCHMARKS = {
    "running_spot": {"mean": 60.0, "stdev": 20.0},
    "high_knees": {"mean": 58.0, "stdev": 20.0},
    "pushup": {"mean": 55.0, "stdev": 22.0},
    "plank": {"mean": 60.0, "stdev": 20.0},
    "jump": {"mean": 40.0, "stdev": 12.0},
}


def get_percentile(mode, value):
    """Returns the athlete's percentile rank (0-100) for a metric, assuming
    a normal distribution with the benchmark's mean/stdev. Returns None for
    an unrecognized mode."""
    bench = BENCHMARKS.get(mode)
    if not bench or bench["stdev"] <= 0:
        return None
    z = (value - bench["mean"]) / bench["stdev"]
    cdf = 0.5 * (1 + math.erf(z / math.sqrt(2)))
    return round(max(0.0, min(1.0, cdf)) * 100, 1)


# Each sport's fit score is a weighted average of the athlete's five 0-100
# form scores (weights within a sport sum to 1). "positions" maps a subset
# of those same metrics to a specific position recommendation: whichever of
# a sport's listed metrics is the athlete's strongest becomes their position.
SPORT_PROFILES = {
    "Basketball": {
        "weights": {"jump": 0.40, "running_spot": 0.20, "high_knees": 0.20, "pushup": 0.10, "plank": 0.10},
        "positions": {
            "jump": "Power Forward / Center — elite vertical for rebounding and shot-blocking",
            "running_spot": "Point Guard — high cadence and agility for ball-handling and transition",
            "high_knees": "Shooting Guard — quick first step and change of direction",
        },
    },
    "Soccer": {
        "weights": {"running_spot": 0.35, "high_knees": 0.25, "plank": 0.20, "jump": 0.10, "pushup": 0.10},
        "positions": {
            "running_spot": "Winger / Fullback — built for sustained sprinting up and down the flank",
            "plank": "Center Back — core stability for physical duels and holding position",
            "high_knees": "Midfielder — repeated high-intensity bursts box-to-box",
        },
    },
    "Football (Skill Position)": {
        "weights": {"running_spot": 0.30, "jump": 0.25, "high_knees": 0.20, "pushup": 0.15, "plank": 0.10},
        "positions": {
            "running_spot": "Wide Receiver / Cornerback — top-end speed and route-running burst",
            "jump": "Tight End / Safety — explosive power for contested plays",
        },
    },
    "Football (Line)": {
        "weights": {"pushup": 0.40, "plank": 0.30, "jump": 0.15, "running_spot": 0.10, "high_knees": 0.05},
        "positions": {
            "pushup": "Offensive / Defensive Line — raw upper-body power at the point of attack",
            "plank": "Defensive Line — core strength and leverage to anchor against the run",
        },
    },
    "Volleyball": {
        "weights": {"jump": 0.45, "pushup": 0.20, "plank": 0.15, "high_knees": 0.10, "running_spot": 0.10},
        "positions": {
            "jump": "Outside Hitter / Middle Blocker — vertical explosiveness at the net",
        },
    },
    "Gymnastics / CrossFit": {
        "weights": {"plank": 0.35, "pushup": 0.30, "jump": 0.15, "high_knees": 0.10, "running_spot": 0.10},
        "positions": {
            "plank": "All-Around — core control is the foundation of every apparatus",
            "pushup": "Rings / Strength Events — raw pressing power",
        },
    },
    "Wrestling / Combat Sports": {
        "weights": {"pushup": 0.30, "plank": 0.30, "high_knees": 0.20, "running_spot": 0.10, "jump": 0.10},
        "positions": {
            "pushup": "Heavyweight — upper-body power for control and takedowns",
            "plank": "Lightweight — core stability and endurance for scrambles",
        },
    },
}

# The single metric an athlete scores highest on determines their archetype.
PLAYER_ARCHETYPES = {
    "jump": ("Explosive Power Player", "Best-in-class fast-twitch output — built to win vertical and first-step battles."),
    "running_spot": ("Speed & Agility Player", "Elite turnover and change-of-direction — thrives in open-space, transition-heavy roles."),
    "high_knees": ("Dynamic Athlete", "Strong triple-flexion mechanics that translate into explosive multi-directional movement."),
    "pushup": ("Power & Strength Player", "Elite upper-body force output — built for contact and control at the point of attack."),
    "plank": ("Endurance & Stability Player", "Elite core control and stamina — the engine that holds up over a full game."),
}

METRIC_TRAITS = {
    "jump": "Elite Vertical Explosiveness",
    "running_spot": "High-Cadence Sprint Mechanics",
    "high_knees": "Strong Triple-Flexion Coordination",
    "pushup": "Elite Upper-Body Power",
    "plank": "Elite Core Stability",
}


def build_profile(metrics, jump_cm):
    """Computes the full athletic profile from five 0-100 form scores
    (metrics, keyed by test name) and the best recorded jump height in cm:
    best-fit sport, a specific position within it, a player archetype,
    trait tags, and a percentile rank for each test."""
    any_data = any(v > 0 for v in metrics.values())

    if not any_data:
        sport = "General Athlete"
        position = "Complete at least one event to unlock a position recommendation."
        archetype, archetype_desc = "Developing Prospect", "Log a session to start building your athletic profile."
        traits = ["Active Foundation", "Building Motor Skills"]
    else:
        sport, _fit = max(
            (
                (name, sum(w * metrics[k] for k, w in profile["weights"].items()))
                for name, profile in SPORT_PROFILES.items()
            ),
            key=lambda pair: pair[1],
        )
        sport_positions = SPORT_PROFILES[sport]["positions"]
        best_metric_for_position = max(sport_positions, key=lambda k: metrics[k])
        position = sport_positions[best_metric_for_position]

        top_metric = max(metrics, key=lambda k: metrics[k])
        archetype, archetype_desc = PLAYER_ARCHETYPES[top_metric]

        ranked = sorted(metrics, key=lambda k: metrics[k], reverse=True)
        traits = [METRIC_TRAITS[m] for m in ranked[:2] if metrics[m] > 0] or ["Adaptive Athlete"]

    percentiles = {
        f"{k}_percentile": get_percentile(k, jump_cm if k == "jump" else metrics[k])
        for k in metrics
    }

    return {
        "sport": sport,
        "position": position,
        "archetype": archetype,
        "archetype_desc": archetype_desc,
        "skills": traits,
        "percentiles": percentiles,
    }
