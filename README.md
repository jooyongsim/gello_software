# GELLO on Windows 11

> ### ⚠️ This is a **Windows 11** fork of [wuphilipp/gello_software](https://github.com/wuphilipp/gello_software).
>
> Upstream GELLO targets Linux: it assumes `/dev/serial/by-id` device paths, `udev`
> rules, SocketCAN, and Unix tools such as `lsof`, `fuser`, and `chmod`. This fork
> adds native Windows 11 support on top of that:
>
> - COM-port serial discovery via `pyserial` ([`gello/utils/serial_ports.py`](gello/utils/serial_ports.py))
> - Windows-safe paths in the Dynamixel driver — no `lsof` / `fuser` / `sudo chmod`
> - COM ports accepted wherever a Linux device path was previously required
> - UTF-8 README handling, so `pip install -e .` works on non-English Windows locales (cp949 and similar)
> - Real connection errors instead of a silent fake-driver fallback during calibration
>
> **Linux and macOS users should use the upstream repository instead.**
> Verified on Windows 11 with Python 3.11.

<p align="center">
  <img src="imgs/title.png" />
</p>

GELLO is a general, low-cost, and intuitive teleoperation framework for robot manipulators. This repository contains all the software components for GELLO.

### Windows users start here

| Step | Section | Hardware needed |
| --- | --- | --- |
| 1 | [Windows Quick Start 1: MuJoCo Simulation](#windows-quick-start-1-mujoco-simulation) | None |
| 2 | [Windows Quick Start 2: U2D2 GELLO Calibration](#windows-quick-start-2-u2d2-gello-calibration) | U2D2 + GELLO |
| — | [Full Windows 11 support notes](#windows-11-native-support) | — |

For additional resources:
- [Project Website](https://wuphilipp.github.io/gello_site/)
- [Hardware Repository](https://github.com/wuphilipp/gello_mechanical) - STL files and build instructions
- [ROS 2 Support](ros2/README.md)

---

## Windows Quick Start 1: MuJoCo Simulation

Run this first. It requires **no hardware** and confirms that the virtual
environment, the `mujoco_menagerie` submodule, and the ZMQ transport all work
before you connect a U2D2.

### Setup

```powershell
git clone --recursive https://github.com/jooyongsim/gello_software.git
cd gello_software

py -3.11 -m venv .venv

.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m pip install -e .\third_party\DynamixelSDK\python
```

`--recursive` matters: without the `mujoco_menagerie` submodule there are no robot
XML files and the simulation has nothing to load. If you already cloned without it,
run `git submodule update --init --recursive`.

If `requirements.txt` fails on `pin`, `ur-rtde`, or `pyrealsense2`, none of those
are needed for the simulation or the Dynamixel path. Install the working subset
instead and skip the rest:

```powershell
.\.venv\Scripts\python.exe -m pip install mujoco dm_control tyro omegaconf==2.3.0 pyzmq numpy-quaternion pyquaternion pygame termcolor Pillow setuptools pyserial
```

Verify the interpreter before continuing:

```powershell
.\.venv\Scripts\python.exe --version
```

The expected result is Python 3.11.x.

### Launch

The simulation is two processes talking over ZMQ: a **robot node** (MuJoCo,
default port 6001) and an **agent** that sends target joint angles. Open two
terminals, both in the repository root.

Terminal A — simulated robot node:

```powershell
.\.venv\Scripts\python.exe experiments\launch_nodes.py --robot sim_ur
```

A MuJoCo viewer window opens showing a UR5e. `--robot` accepts `sim_ur`,
`sim_panda`, `sim_xarm`, and `sim_yam`.

Terminal B — agent:

```powershell
.\.venv\Scripts\python.exe experiments\run_env.py --agent=none
```

Use `--agent=none` (or `dummy`) while no GELLO is connected. `--agent=gello`
requires real Dynamixel hardware and is covered in
[Quick Start 2](#windows-quick-start-2-u2d2-gello-calibration).

### Verifying the loop without an agent

To confirm the node is serving and the physics is stepping, connect a client
directly from a third terminal:

```powershell
.\.venv\Scripts\python.exe -c "from gello.zmq_core.robot_node import ZMQClientRobot; c = ZMQClientRobot(port=6001, host='127.0.0.1'); print('num_dofs =', c.num_dofs()); print('joint_state =', c.get_joint_state())"
```

Expected output for `sim_ur` — 6 arm joints plus 1 gripper:

```
num_dofs = 7
joint_state = [2.3e-12  0.030  0.009 -1.9e-04  1.3e-04  1.5e-06  2.6e-03]
```

The small non-zero values are the arm settling under gravity, which confirms that
`mj_step` is running rather than the model sitting frozen.

### Known behavior on Windows

- **Commanded poses do not land exactly on target.** The UR5e MJCF uses position
  actuators under gravity, so a commanded `-1.57` settles near `-1.26`. This
  steady-state droop is expected, not a configuration error.
- **`arena.xml` appears in the repository root.** [`gello/robots/sim_robot.py`](gello/robots/sim_robot.py)
  writes a debug MJCF dump into the working directory on every simulation launch.
  It is upstream behavior and safe to delete.
- **Run the node in a normal terminal, not a detached or background shell.**
  Tearing down the MuJoCo viewer from a detached process exits with a
  segmentation fault (exit code 139). The simulation itself is unaffected.
- **Repeated `Timeout in ZMQLeaderServer serve` lines are normal.** They are idle
  receive timeouts printed while no agent is connected.

---

## Windows Quick Start 2: U2D2 GELLO Calibration

Do this only after [Quick Start 1](#windows-quick-start-1-mujoco-simulation)
works. Calibration reads joint positions from real servos; it does not command
motion.

### Step 1 — Find the COM port

Plug in the U2D2 and enumerate serial ports:

```powershell
.\.venv\Scripts\python.exe -c "from serial.tools import list_ports; [print(p.device,'|',p.description,'|',p.hwid) for p in list_ports.comports()]"
```

The U2D2 is an FTDI device, so look for `VID:PID=0403:6014`:

```
COM4 | USB Serial Port(COM4) | USB VID:PID=0403:6014 SER=FTA7NLMOA
```

Device Manager shows the same assignment under Ports (COM & LPT). Note the number
and pass it explicitly with `--port` / `--gello-port`. Automatic selection can
pick a Bluetooth link or a virtual COM port instead.

### Step 2 — Confirm the servos respond

Ping each Dynamixel ID before calibrating. This is read-only: it changes no motor
settings and does not enable torque.

```powershell
.\.venv\Scripts\python.exe -c "from dynamixel_sdk import PortHandler, PacketHandler, COMM_SUCCESS; ph = PortHandler('COM4'); ph.openPort(); ph.setBaudRate(57600); pk = PacketHandler(2.0); print([(i, pk.ping(ph, i)[0]) for i in range(1, 11) if pk.ping(ph, i)[1] == COMM_SUCCESS]); ph.closePort()"
```

A healthy 6-DOF GELLO with a gripper reports seven servos:

```
[(1, 1200), (2, 1200), (3, 1200), (4, 1200), (5, 1200), (6, 1200), (7, 1190)]
```

IDs 1-6 are the arm joints (model 1200 = XL330-M288-T) and ID 7 is the gripper
(model 1190 = XL330-M077-T).

What to check if this returns nothing:

- **Empty list at 57600** — the servos are on a different baud rate.
  [`scripts/gello_get_offset.py`](scripts/gello_get_offset.py) hardcodes 57600, so
  set the motors to 57600 in Dynamixel Wizard rather than editing the script.
- **Duplicate or out-of-order IDs** — connect one motor at a time in Dynamixel
  Wizard and assign IDs 1 through 7 in order from base to gripper.
- **`openPort` fails** — another process already holds the port. On Windows the
  driver cannot report which one, so close any other GELLO process or Dynamixel
  Wizard session and retry.

### Step 3 — Pose GELLO and measure the offsets

1. Move GELLO into the reference pose for your follower robot
   (see `imgs/gello_matching_joints.jpg`).
2. Open the gripper fully — the script derives the open angle from the current
   gripper position.
3. Hold the pose and run:

```powershell
.\.venv\Scripts\python.exe scripts\gello_get_offset.py --start-joints 0 -1.57 1.57 -1.57 -1.57 0 --joint-signs 1 1 -1 1 1 1 --port COM4
```

`--start-joints` and `--joint-signs` depend on the follower robot:

| Robot | `--joint-signs` | `--start-joints` |
| --- | --- | --- |
| UR | `1 1 -1 1 1 1` | `0 -1.57 1.57 -1.57 -1.57 0` |
| Franka FER (Panda) | `1 -1 1 1 1 -1 1` | `0 0 0 -1.57 0 1.57 0` |
| xArm | `1 1 1 1 1 1 1` | depends on build |
| I2RT YAM | `1 -1 -1 -1 1 1` | `0 0 0 0 0 0` |

The script prints four lines. Keep all four — Step 4 needs them:

```
best offsets               :  ['3.142', '4.712', ...]
best offsets function of pi: [ 2*np.pi/2, 3*np.pi/2, ... ]
gripper open (degrees)        <number>
gripper close (degrees)       <number>
```

Because this fork passes `use_fake_fallback=False` during calibration, a failed
connection raises instead of returning fabricated joint values. If numbers are
printed, they are genuine readings.

#### Run it twice, and check the margins

`gello_get_offset.py` picks the nearest multiple of pi/2 for each joint. If a
joint sits near the midpoint between two candidates, the choice flips between
runs — the output looks perfectly normal, but a rerun silently gives a different
90° answer for that joint. **Always run the calibration twice and confirm both
runs match** before writing the values into a config.

To see *why* a joint is flipping rather than inferring it from repeated runs,
use the companion script:

```powershell
.\.venv\Scripts\python.exe scripts\check_offset_margin.py --port COM4
```

It prints the same offsets plus two diagnostic columns:

```
joint  raw(rad)      best    resid       2nd  margin  verdict
    1     6.386       4*pi/2     5.9d       5*pi/2   1.365  OK
    2     0.647       1*pi/2    37.0d       2*pi/2   0.278  AMBIGUOUS -- repose this joint
    3     1.528       2*pi/2     2.5d       1*pi/2   1.483  OK
    4    -0.943       0*pi/2    35.9d       1*pi/2   0.318  AMBIGUOUS -- repose this joint
    5     4.717       4*pi/2     0.2d       5*pi/2   1.563  OK
    6     6.222       4*pi/2     3.5d       3*pi/2   1.448  OK
```

- `resid` — how far the joint is from the reference pose after applying the
  chosen offset. A large value means GELLO is not actually in the reference pose
  for that joint.
- `margin` — the error gap to the runner-up candidate. Below roughly `0.8`, the
  choice is one small nudge away from flipping.

A joint is trustworthy when `resid` is under 15° and `margin` is over 0.8. In
the example above, joints 2 and 4 sit about 36° from any pi/2 multiple, which is
close to the 45° flip boundary — those two need to be physically re-posed, not
re-measured.

Add `--watch` to refresh live while posing GELLO by hand, which is far easier
than rerunning the calibration and comparing by eye:

```powershell
.\.venv\Scripts\python.exe scripts\check_offset_margin.py --port COM4 --watch
```

Press Ctrl+C once every joint reads `OK`; the final offsets are printed in the
same format `gello_get_offset.py` uses.

If a joint's `resid` refuses to drop no matter how carefully it is posed, that
servo horn was mounted at a non-pi/2 angle during assembly. Remount it, or write
the exact measured float into `joint_offsets` — the field accepts any float and
the pi/2 rule is only a convention.


### Step 4 — Add your COM port to `PORT_CONFIG_MAP`

Open [`gello/agents/gello_agent.py`](gello/agents/gello_agent.py) and find:

```python
PORT_CONFIG_MAP: Dict[str, DynamixelRobotConfig] = {
```

It already contains four entries keyed by Linux `/dev/serial/by-id/...` paths.
Add your COM port as one more key inside the same braces:

```python
"COM4": DynamixelRobotConfig(
    joint_ids=(1, 2, 3, 4, 5, 6),
    joint_offsets=(
        2 * np.pi / 2,
        3 * np.pi / 2,
        2 * np.pi / 2,
        2 * np.pi / 2,
        2 * np.pi / 2,
        2 * np.pi / 2,
    ),
    joint_signs=(1, 1, -1, 1, 1, 1),
    gripper_config=(7, 20, -22),
),
```

> **Every number above is a placeholder.** Substitute:
>
> - `joint_offsets` — the `best offsets function of pi` line from Step 3, one entry per joint
> - `joint_signs` — the same `--joint-signs` values passed in Step 3
> - `gripper_config` — `(gripper_joint_id, open_degrees, close_degrees)`, using the
>   gripper ID from Step 2 and the two gripper lines from Step 3
>
> Do not paste placeholder text such as `<open angle>` into the file. Python fails
> with `SyntaxError: invalid syntax` at that line, and because `gello_agent.py` is
> imported at startup, every entry point stops working until it is corrected.

### Step 5 — Teleoperate

Test against the simulator before touching a real follower arm:

```powershell
# Terminal A
.\.venv\Scripts\python.exe experiments\launch_nodes.py --robot sim_ur

# Terminal B
.\.venv\Scripts\python.exe experiments\run_env.py --agent=gello --gello-port COM4
```

Moving GELLO should move the simulated arm. If a joint moves in the wrong
direction, invert that joint's sign in `joint_signs` rather than re-running
calibration.

To record demonstrations, add `--use-save-interface`: press `s` to start and `q`
to stop. Episodes are written to `data/` in the repository root.

```powershell
.\.venv\Scripts\python.exe experiments\run_env.py --agent=gello --gello-port COM4 --use-save-interface
```

---

## Supported Robots
- **I2RT YAM**
- **Franka FR3** (ROS 2 implementation, please refer to the separate documenation in [`ros2/README.md`](ros2/README.md))
- **Franka FER (Panda)**
- **UR**
- **xArm**
- add your own, see [Adding New Robots](#adding-new-robots)

## Quick Start

```bash
git clone --recursive https://github.com/jooyongsim/gello_software.git
cd gello_software
```

## Installation

### Option 1: Virtual Environment (Recommended)

First, install uv if you don't have it:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Create and activate a virtual environment:
```bash
uv venv --python 3.11
source .venv/bin/activate  # Run this every time you open a new shell
git submodule init
git submodule update
uv pip install -r requirements.txt
uv pip install -e .
uv pip install -e third_party/DynamixelSDK/python
```

### Windows 11 (Native) Support

Windows 11 can run a useful subset of GELLO natively, including MuJoCo simulation,
ZMQ communication, data collection, RealSense, and single SpaceMouse control.
Dynamixel/U2D2 can also be used through a Windows COM port after adding the
appropriate calibrated entry to `PORT_CONFIG_MAP`.

#### Windows installation

From PowerShell, use Python 3.11 explicitly. Do not rely on whatever `python`
currently points to, because older system Python installations can be picked up
when virtual-environment activation fails.

```powershell
git clone --recursive https://github.com/jooyongsim/gello_software.git
cd gello_software

py -3.11 -m venv .venv

.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m pip install -e .\third_party\DynamixelSDK\python
```

Using `.venv\Scripts\python.exe` directly is intentional: it works even if
PowerShell activation is blocked or fails. To verify the interpreter:

```powershell
.\.venv\Scripts\python.exe --version
```

The expected result is Python 3.11.x.

Activation is optional. If you prefer an activated shell and PowerShell blocks
the activation script, the following changes the execution policy only for the
current shell:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

#### U2D2 / Dynamixel on Windows

Windows exposes U2D2 as a COM port such as `COM5`. Check the assigned port in
Device Manager and verify the motor IDs and baud rate with Dynamixel Wizard
before running GELLO.

The driver now skips Linux-only `lsof`, `fuser`, and `chmod` handling on
Windows and lets the Dynamixel SDK validate the COM port directly. Real GELLO
hardware and calibration also disable the fake-driver fallback so connection
errors are visible instead of silently returning fake joint values.

For offset calibration, pass the COM port directly:

```powershell
python scripts\gello_get_offset.py --start-joints 0 -1.57 1.57 -1.57 -1.57 0 --joint-signs 1 1 -1 1 1 1 --port COM5
```

For `GelloAgent`, add a calibrated Windows entry to the `PORT_CONFIG_MAP`
dictionary in `gello/agents/gello_agent.py`. The dictionary starts with
`PORT_CONFIG_MAP: Dict[str, DynamixelRobotConfig] = {` and already contains four
entries keyed by Linux `/dev/serial/by-id/...` paths. Add your COM port as one
more key inside those braces, using your actual COM port. For example:

```python
"COM5": DynamixelRobotConfig(
    joint_ids=(1, 2, 3, 4, 5, 6),
    joint_offsets=(
        # Replace these values with the output from gello_get_offset.py.
        0, 0, 0, 0, 0, 0,
    ),
    joint_signs=(1, 1, -1, 1, 1, 1),
    gripper_config=(7, 20, -22),
),
```

The offset and gripper values above are examples only; they depend on the
physical GELLO assembly.

You can then explicitly select the port:

```powershell
python experiments\run_env.py --agent gello --gello-port COM5
```

When `--gello-port` is omitted, `run_env.py` and `quick_run.py` fall back to
`gello/utils/serial_ports.py`, which enumerates Windows serial ports with
`pyserial`, drops ports that report no USB vendor id (Bluetooth links and
virtual COM ports), and lists FTDI devices first. A single match is used
automatically; several matches are printed and you are asked to choose, because
picking the first COM port silently is easy to get wrong on Windows. Passing
`--gello-port` explicitly is still the most reliable option.

#### YAML configs on Windows

Every file under `configs/` ships with a Linux `port:` value such as
`/dev/serial/by-id/usb-FTDI_USB__-__Serial_Converter_...`. Before using
`launch_yaml.py` on Windows, change that field to your COM port:

```yaml
agent:
  port: "COM5"
```

If a Linux device path is left in place, the driver now reports it directly
instead of failing inside the Dynamixel SDK:

```
Port /dev/serial/by-id/... is a Linux device path and cannot be opened on
Windows. Use the COM port from Device Manager (e.g. COM5) in your config.
```

#### Windows feature compatibility

| Feature | Windows 11 native | Notes |
| --- | --- | --- |
| MuJoCo simulation | Supported | UR/Panda/xArm/YAM simulation paths are Python/MuJoCo based. |
| Dummy/custom agents | Supported | No Linux device dependency in the agent abstraction. |
| ZMQ robot/camera communication | Supported | Uses pyzmq/TCP. |
| Data collection/post-processing | Supported | Normal Python filesystem usage; verify output paths for your setup. |
| RealSense RGB/depth | Supported | Uses `pyrealsense2`; install a compatible Windows RealSense runtime/wheel. |
| Single SpaceMouse | Supported with device/driver setup | `pyspacemouse.open()` can be used without a Linux `/dev/hidraw*` path. |
| Dual SpaceMouse | Needs code/config changes | Current bimanual launcher contains Linux `/dev/hidraw0` and `/dev/hidraw1` paths. |
| Quest/VR agent | Experimental on Windows | Depends on Oculus reader/ADB setup and is not documented as a primary Windows path. |
| U2D2 / Dynamixel GELLO | Supported with Windows configuration | Use a COM port and add a calibrated COM entry to `PORT_CONFIG_MAP`. |
| UR/xArm real robot | Potentially supported | Depends on the vendor SDK and network setup on Windows. |
| YAM real robot | Not supported natively by this repository | Hardware path depends on Linux CAN/udev/SocketCAN-style setup. |
| Franka FR3 ROS 2 stack | Linux recommended | Repository ROS 2 setup assumes Humble, libfranka/franka_ros2, bash and Linux device paths. |
| Panda via Polymetis | Linux recommended | Polymetis-based hardware path is Linux-oriented. |
| FACTR hardware gravity compensation | Linux recommended | Current hardware integration is tied closely to the YAM/Linux stack. |

For Windows-first development, a practical progression is:
`MuJoCo + DummyAgent` -> `MuJoCo + SpaceMouse` -> RealSense/data collection ->
U2D2/GELLO -> real follower robot.

### Option 2: Docker

Install [Docker](https://docs.docker.com/engine/install/ubuntu/), then:

```bash
docker build . -t gello:latest
python scripts/launch.py
```

### ROS 2 Support

> **Note:** GELLO also supports ROS 2 Humble for the Franka FR3 robot. See the [ROS 2-specific README](ros2/README.md) in the `ros2` directory.

## Hardware Configuration

The recommended setup for GELLO is with the I2RT YAM robot arm, using the YAML-based configuration system. This provides the most features and is the best-supported configuration.

### Generate YAML Configuration

For the I2RT YAM robot, you can automatically generate your configuration files. This process calibrates the joint offsets and creates configuration files for both simulation and real hardware.

1.  **Update Motor IDs**: Before generating the config, ensure each Dynamixel motor has a unique ID. Install the [Dynamixel Wizard](https://emanual.robotis.com/docs/en/software/dynamixel/dynamixel_wizard2/) and follow these steps:
    1.  Connect a single motor to the U2D2 controller.
    2.  Open Dynamixel Wizard and scan to detect the motor.
    3.  Change the ID to a unique number (e.g., 1 through 7).
    4.  Repeat for each motor, ensuring they are in order from base to gripper.

2.  **Run the Generation Script**: With the YAM arm in its default build position (see image below), run the script:
    ```bash
    python scripts/generate_yam_config.py
    ```
    Follow the prompts in the terminal. This will create `configs/yam_auto_generated.yaml` for the real robot and `configs/yam_auto_generated_sim.yaml` for the simulation.

<p align="center">
  <img src="imgs/yam_default.JPG" width="42%">
</p>

You can now skip to the [Usage](#usage) section.

### YAML Configuration System

GELLO uses YAML files in `configs/` for configuration. This allows for flexible setup of different robots, environments, and teleoperation parameters. If you have automatically generated your `.yaml` config files with `scripts/generate_yam_config.py`, you probably will not need to modify these confings manually.

#### Sample Configs

Sample configs for the YAM arm and the xarm can be found in `configs`.


#### Configuration Components

- **Robot Config**: Defines robot type, communication parameters, and physical settings.
- **Agent Config**: Defines GELLO device settings, joint mappings, and calibration.
- **DynamixelRobotConfig**: Motor-specific settings including IDs, offsets, signs, and gripper.
- **Control Parameters**: Update rates (`hz`), step limits (`max_steps`), and safety settings.

## Manual Configuration for Other Robots

#### Python Configuration for Non-YAM arms
- Most widely supported across different arms
- Located in `gello/agents/gello_agent.py`
- Uses `PORT_CONFIG_MAP` dictionary
- Maps USB serial ports to robot configurations

## Adding New Robots

To integrate a new robot to the Python configs:

1. **Check Compatibility**: Ensure your GELLO kinematics match the target robot
2. **Implement Robot Interface**: Create a new class implementing the `Robot` protocol from `gello/robots/robot.py`
3. **Add Configuration**: Update the configuration system with your robot's parameters

See existing implementations in `gello/robots/` for reference:
- `panda.py` - Franka Panda robot
- `ur.py` - Universal Robots
- `xarm_robot.py` - xArm robots
- `yam.py` - YAM robot

=======

#### 1. Manual `gello_agent` setup
Set your GELLO and robot arm to a known, matching configuration (see images below) and run the offset detection script.

<p align="center">
  <img src="imgs/gello_matching_joints.jpg" width="29%"/>
  <img src="imgs/robot_known_configuration.jpg" width="29%"/>
  <img src="imgs/fr3_gello_calib_pose.jpeg" width="31%"/>
</p>

**Command examples:**

**UR Robot:**
```bash
python scripts/gello_get_offset.py \
    --start-joints 0 -1.57 1.57 -1.57 -1.57 0 \
    --joint-signs 1 1 -1 1 1 1 \
    --port /dev/serial/by-id/usb-FTDI_USB__-__Serial_Converter_FT7WBG6
```

**Franka FER (Panda):**
```bash
python scripts/gello_get_offset.py \
    --start-joints 0 0 0 -1.57 0 1.57 0 \
    --joint-signs 1 1 1 1 1 -1 1 \
    --port /dev/serial/by-id/usb-FTDI_USB__-__Serial_Converter_FT7WBG6
```

**I2RT YAM:**
```bash
python scripts/gello_get_offset.py \
    --start-joints 0 0 0 0 0 0 \
    --joint-signs 1 -1 -1 -1 1 1 \
    --port /dev/serial/by-id/usb-FTDI_USB__-__Serial_Converter_FTAAMLV6-if00-port0
```

**Joint Signs Reference:**
- UR: `1 1 -1 1 1 1`
- Panda: `1 -1 1 1 1 -1 1`
- xArm: `1 1 1 1 1 1 1`
- YAM: `1 -1 -1 -1 1 1`

Add the generated joint offsets to `gello/agents/gello_agent.py` in the `PORT_CONFIG_MAP`.

#### 2. Create Custom YAML Configurations

1. Copy an existing config from `configs/` as a template (e.g., `yam_passive.yaml`).
2. Modify the robot `_target_` and parameters for your setup:
   - For hardware: `gello.robots.ur.URRobot`, `gello.robots.panda.PandaRobot`, etc.
   - For simulation: `gello.robots.sim_robot.MujocoRobotServer`
3. Update the agent configuration with your GELLO device settings:
   - `port`: Your U2D2 device path
   - `joint_offsets`: From the offset detection script
   - `joint_signs`: Based on your robot type
   - `start_joints`: Your GELLO's starting position

## Usage

The recommended way to launch GELLO is with a YAML configuration file.

### CAN Configuration
Robot arms such as the YAM use a CAN bus to communicate with your machine. If your arm uses a CAN bus, you will need to configure udev rules.
First, get your CAN bus ID:
```
udevadm info -a -p /sys/class/net/can* | grep -i serial
```
Then open your CAN bus rules using your text editor of choice.
```
sudo nano /etc/udev/rules.d/90-can.rules
```
If you only have one arm, add this line:
```
SUBSYSTEM=="net", ACTION=="add", ATTRS{serial}=="<your-CAN-id>", NAME="can_left"
```
If you have two arms (a bimanual setup), you will need a second line for your right arm. Your bimanual CAN rules file should contain:
```
SUBSYSTEM=="net", ACTION=="add", ATTRS{serial}=="<left-CAN-id>", NAME="can_left"
SUBSYSTEM=="net", ACTION=="add", ATTRS{serial}=="<right-CAN-id>", NAME="can_right"
```

After updating your udev rules, run the following and then unplug and reconnect your CAN devices.
```
sudo udevadm control --reload-rules && sudo systemctl restart systemd-udevd && sudo udevadm trigger
```
At this point, your CAN devices are correctly configured. If you encounter CAN connctivity issues after this point run `sh scripts/reset_all_can.sh` to reset your CAN buses.

### YAM GELLO Usage (Recommended)

First, install the YAM-specific dependency:
- **YAM**: [I2RT](https://github.com/i2rt-robotics/i2rt)
- `uv pip install -e third_party/i2rt`

**Testing in Simulation:**
Launch the simulation with the auto-generated sim config file:
```bash
python experiments/launch_yaml.py --left-config-path configs/yam_auto_generated_sim.yaml
```

**Real Robot Operation:**
Launch the real robot with the auto-generated hardware config file:
```bash
python experiments/launch_yaml.py --left-config-path configs/yam_auto_generated.yaml
```

### Launching `gello_agent` for non-YAM arms

For other robots or if not using a YAML configuration, you must launch the robot and controller nodes in separate terminals.

First, install robot-specific dependencies:
- **UR**: [ur_rtde](https://sdurobotics.gitlab.io/ur_rtde/installation/installation.html)
- **Panda**: [polymetis](https://facebookresearch.github.io/fairo/polymetis/installation.html)
- **xArm**: [xArm Python SDK](https://github.com/xArm-Developer/xArm-Python-SDK)

**1. Launch the robot node:**
```bash
# For simulation
python experiments/launch_nodes.py --robot <sim_ur|sim_panda|sim_xarm>

# For real hardware
python experiments/launch_nodes.py --robot <ur|panda|xarm>
```

**2. Launch GELLO controller:**
```bash
python experiments/run_env.py --agent=gello
```

### Troubleshooting

If, when you run `generate_yam_config.py`, you get an error detecting offsets, you may need to add your user to the dialout user group. To do so, run:
`sudo usermod -aG dialout $USER`
And then log out and log back in or restart your computer.s

If some joints in your arm are not behaving as expected, you may need to modify the joint signs of your configuration. Simply invert the affected joint sign(s) in your .yaml or `gello_agent.py` or physically reverse the installation of the servo.

### Optional: Starting Configuration

Use `--start-joints` to specify GELLO's starting configuration for automatic robot reset:
```bash
python experiments/run_env.py --agent=gello --start-joints <joint_angles>
```

## Advanced Features

### Data Collection

Collect teleoperation demonstrations with keyboard controls.

For the YAM arm launched with `launch_yaml.py`, you can append the flag `--use-save-interface` to enable data saving. This is the recommended method.

```
python experiments/launch_yaml.py --left-config-path configs/yam_passive.yaml --use-save-interface
```
After launching, you can begin saving with `s` and stop saving with `q`. Data saved will be in the `data` directory in the root of the project.

For non-YAM setups, use the following:
```bash
python experiments/run_env.py --agent=gello --use-save-interface
```
Process collected data:
```bash
python gello/data_utils/demo_to_gdict.py --source-dir=<source_dir>
```

### Bimanual Operation

The recommended way to use bimanual mode is with `launch_yaml.py`. Pass a config file for the right arm to `--right-config-path`.

```
python experiments/launch_yaml.py --left-config-path configs/gello_1.yaml --right-config-path configs/gello_2.yaml
```

For non-YAM setups, use:
```bash
python experiments/launch_nodes.py --robot=bimanual_ur
python experiments/run_env.py --agent=gello --bimanual
```
### FACTR Gravity Compensation
If you want to activate gravity compensation, all the code can be found in `gello/factr`. It works similarly to the regular launch but for now it's self-contained inside its own subdirectory and supports the YAM arm in sim and in hardware.

The YAML provides important fields that can control the strength of the gravity compensation and friction. Feel free to mess around with the strenght and friction til you attain your desired 

One important step is to add the URDF. We have provided the URDF for the active GELLO in the [Hardware Repository](https://github.com/wuphilipp/gello_mechanical). You will need to update the path in the YAML to the entry point of the URDF. 
```bash
python gello/factr/gravity_compensation.py --config configs/yam_gello_factr_hw.yaml

```

## Development

### Code Organization

```
├── scripts/             # Utility scripts
├── experiments/         # Entry points and launch scripts
├── gello/               # Core GELLO package
│   ├── agents/          # Teleoperation agents
│   ├── cameras/         # Camera interfaces
│   ├── data_utils/      # Data processing utilities
│   ├── dm_control_tasks/# MuJoCo environment utilities
│   ├── dynamixel/       # Dynamixel hardware interface
|   ├── factr/           # gravity compensation
│   ├── robots/          # Robot-specific interfaces
│   ├── utils/           # Shared launch and control utilities
│   └── zmq_core/        # ZMQ multiprocessing utilities
```

### Contributing

Install development dependencies and set up pre-commit hooks to ensure code quality before contributing:
```bash
uv pip install -r requirements_dev.txt
uv pip install pre-commit
pre-commit install
```

The codebase uses `isort` and `black` for code formatting.

We welcome contributions! Submit pull requests to help make teleoperation more accessible and higher quality.

## Citation

```bibtex
@misc{wu2023gello,
    title={GELLO: A General, Low-Cost, and Intuitive Teleoperation Framework for Robot Manipulators},
    author={Philipp Wu and Yide Shentu and Zhongke Yi and Xingyu Lin and Pieter Abbeel},
    year={2023},
}
```

## License & Acknowledgements

This project is licensed under the MIT License (see LICENSE file).

### Third-Party Dependencies
- [google-deepmind/mujoco_menagerie](https://github.com/google-deepmind/mujoco_menagerie): Robot models for MuJoCo
- [brentyi/tyro](https://github.com/brentyi/tyro): Argument parsing and configuration
- [ZMQ](https://zeromq.org/): Multiprocessing communication framework

This project uses components from ‘FACTR Teleop: Low-Cost Force-Feedback Teleoperation’ (Apache‑2.0). See `https://github.com/RaindragonD/factr_teleop/`.
