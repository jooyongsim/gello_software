"""Report how decisive each GELLO joint offset is.

``gello_get_offset.py`` picks the nearest multiple of pi/2 for every joint. When
a joint sits near the midpoint between two candidates, that choice flips between
runs and the resulting config is effectively a coin toss -- the printed offsets
look fine, but rerunning the script gives a different answer for that joint.

This script prints the same offsets plus two extra columns that make the problem
visible:

* ``resid`` -- how far the joint is from the reference pose after applying the
  chosen offset. Large values mean GELLO is not actually in the reference pose.
* ``margin`` -- the error gap to the runner-up candidate. Small values mean the
  choice is about to flip.

Use ``--watch`` to refresh live while posing GELLO by hand.

Examples:
    python scripts/check_offset_margin.py --port COM4
    python scripts/check_offset_margin.py --port COM4 --watch
    python scripts/check_offset_margin.py --port /dev/ttyUSB0 \
        --start-joints 0 0 0 0 0 0 --joint-signs 1 -1 -1 -1 1 1
"""

import time
from dataclasses import dataclass
from typing import List, Tuple

import numpy as np
import tyro

from gello.dynamixel.driver import DynamixelDriver

# gello_get_offset.py searches multiples of pi/2 over +/- 8 pi.
_CANDIDATE_OFFSETS = np.linspace(-8 * np.pi, 8 * np.pi, 8 * 4 + 1)


@dataclass
class Args:
    port: str = "/dev/ttyUSB0"
    """The port that GELLO is connected to (for example COM4 on Windows)."""

    start_joints: Tuple[float, ...] = (0, -1.57, 1.57, -1.57, -1.57, 0)
    """The joint angles that GELLO is placed in (in radians). Default is UR."""

    joint_signs: Tuple[float, ...] = (1, 1, -1, 1, 1, 1)
    """The joint signs for the follower robot. Default is UR."""

    gripper: bool = True
    """Whether or not the gripper is attached."""

    baudrate: int = 57600
    """Dynamixel baudrate. Must match gello_get_offset.py to be comparable."""

    watch: bool = False
    """Refresh continuously instead of printing once. Stop with Ctrl+C."""

    max_residual_deg: float = 15.0
    """A joint passes when its residual is below this many degrees."""

    min_margin: float = 0.8
    """A joint passes when its margin to the runner-up exceeds this (radians)."""

    def __post_init__(self):
        assert len(self.joint_signs) == len(self.start_joints)
        for idx, j in enumerate(self.joint_signs):
            assert (
                j == -1 or j == 1
            ), f"Joint idx: {idx} should be -1 or 1, but got {j}."

    @property
    def num_robot_joints(self) -> int:
        return len(self.start_joints)

    @property
    def num_joints(self) -> int:
        extra_joints = 1 if self.gripper else 0
        return self.num_robot_joints + extra_joints


def _rank_offsets(
    joint_state: np.ndarray, index: int, args: Args
) -> List[Tuple[float, float]]:
    """Return (error, offset) pairs for one joint, best first."""
    sign = args.joint_signs[index]
    start = args.start_joints[index]
    ranked = [
        (abs(sign * (joint_state[index] - offset) - start), offset)
        for offset in _CANDIDATE_OFFSETS
    ]
    ranked.sort()
    return ranked


def _report(joint_state: np.ndarray, args: Args) -> List[float]:
    """Print one table and return the chosen offsets."""
    print(
        f"{'joint':>5} {'raw(rad)':>9} {'best':>9} {'resid':>8} "
        f"{'2nd':>9} {'margin':>7}  verdict"
    )
    offsets = []
    for i in range(args.num_robot_joints):
        ranked = _rank_offsets(joint_state, i, args)
        (best_err, best_off), (second_err, second_off) = ranked[0], ranked[1]
        residual_deg = np.rad2deg(best_err)
        margin = second_err - best_err
        decisive = (
            residual_deg < args.max_residual_deg and margin > args.min_margin
        )
        verdict = "OK" if decisive else "AMBIGUOUS -- repose this joint"
        offsets.append(best_off)
        print(
            f"{i + 1:>5} {joint_state[i]:>9.3f} "
            f"{int(round(best_off / (np.pi / 2))):>7}*pi/2 "
            f"{residual_deg:>7.1f}d "
            f"{int(round(second_off / (np.pi / 2))):>7}*pi/2 "
            f"{margin:>7.3f}  {verdict}"
        )
    return offsets


def _print_config(offsets: List[float], joint_state: np.ndarray, args: Args) -> None:
    """Print the values in the same shape gello_get_offset.py uses."""
    print()
    print("best offsets               : ", [f"{x:.3f}" for x in offsets])
    print(
        "best offsets function of pi: ["
        + ", ".join([f"{int(np.round(x / (np.pi / 2)))}*np.pi/2" for x in offsets])
        + " ]",
    )
    if args.gripper:
        print("gripper open (degrees)       ", np.rad2deg(joint_state[-1]) - 0.2)
        print("gripper close (degrees)      ", np.rad2deg(joint_state[-1]) - 42)


def main(args: Args) -> None:
    joint_ids = list(range(1, args.num_joints + 1))
    driver = DynamixelDriver(
        joint_ids,
        port=args.port,
        baudrate=args.baudrate,
        use_fake_fallback=False,
    )

    for _ in range(10):
        driver.get_joints()  # warmup

    joint_state = driver.get_joints()

    if not args.watch:
        offsets = _report(joint_state, args)
        _print_config(offsets, joint_state, args)
        return

    offsets = _report(joint_state, args)
    try:
        while True:
            joint_state = driver.get_joints()
            print("\033[H\033[J", end="")  # clear screen, cursor home
            print(
                "Pose GELLO until every joint reads OK. Ctrl+C to stop.\n",
                flush=True,
            )
            offsets = _report(joint_state, args)
            time.sleep(0.2)
    except KeyboardInterrupt:
        print()
        _print_config(offsets, joint_state, args)


if __name__ == "__main__":
    main(tyro.cli(Args))
