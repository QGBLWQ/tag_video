from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class DeviceProfile:
    serial: str                                    # "e4e06e1f59b112c4"
    label: str                                     # "M1_3"
    dut_root: str = ""                             # "/mnt/nvme/CapturedData"
    dji_dir: Path = field(default_factory=Path)    # "tools/_dji_M1_3"
    port_base: int = 5555
    adb_prefix: str = ""                           # "-s e4e06e1f59b112c4"

    def __post_init__(self):
        if not self.adb_prefix:
            self.adb_prefix = f"-s {self.serial}"
        if isinstance(self.dji_dir, str):
            self.dji_dir = Path(self.dji_dir)
