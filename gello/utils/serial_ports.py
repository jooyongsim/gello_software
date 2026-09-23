"""Cross-platform discovery of the serial port a GELLO is plugged into."""

import glob
import os
from typing import List, Optional, Tuple

# U2D2 and the usual GELLO builds expose an FTDI USB-serial converter.
FTDI_VENDOR_ID = 0x0403

_LINUX_BY_ID = "/dev/serial/by-id/"
_LINUX_FTDI_GLOB = "usb-FTDI_USB__-__Serial_Converter_*"


def list_gello_ports(ftdi_only: bool = False) -> List[Tuple[str, str]]:
    """Return ``(device, label)`` for every plausible GELLO serial port.

    On Linux/macOS this is the ``/dev/serial/by-id`` glob used elsewhere in the
    codebase. Windows has no by-id namespace, so ports are enumerated with
    pyserial and filtered down to real USB devices: Bluetooth links and virtual
    COM ports report no vendor id and are dropped, and FTDI devices sort first.
    """
    if os.name != "nt":
        pattern = _LINUX_FTDI_GLOB if ftdi_only else "*"
        return [(port, port) for port in sorted(glob.glob(_LINUX_BY_ID + pattern))]

    from serial.tools import list_ports

    ports = [port for port in list_ports.comports() if port.vid is not None]
    if ftdi_only:
        ports = [port for port in ports if port.vid == FTDI_VENDOR_ID]
    ports.sort(key=lambda port: (port.vid != FTDI_VENDOR_ID, port.device))
    return [(port.device, f"{port.device} ({port.description})") for port in ports]


def find_gello_port(ftdi_only: bool = False, interactive: bool = True) -> Optional[str]:
    """Pick a GELLO port, prompting the user when the choice is ambiguous.

    Returns ``None`` when nothing was found, or when several ports match and
    ``interactive`` is False. Auto-picking the first match is deliberately not
    done for multiple matches: on Windows the candidates can include unrelated
    USB-serial adapters, and silently opening the wrong one is hard to debug.
    """
    ports = list_gello_ports(ftdi_only=ftdi_only)
    if not ports:
        return None
    if len(ports) == 1:
        return ports[0][0]

    print("Multiple candidate GELLO ports found:")
    for index, (_, label) in enumerate(ports):
        print(f"  {index + 1}: {label}")

    if not interactive:
        print("Refusing to guess; pass the port explicitly.")
        return None

    while True:
        try:
            choice = int(input("Select port number: ")) - 1
            if 0 <= choice < len(ports):
                return ports[choice][0]
            print("Invalid choice, please try again.")
        except ValueError:
            print("Please enter a valid number.")


def is_linux_port_path(port: str) -> bool:
    """True if ``port`` is a Linux device path, which Windows cannot open."""
    return port.startswith("/dev/")
