"""ADB 设备连接状态实时监控服务。

QTimer 每 5 秒后台执行 adb devices，解析输出，状态变化时 emit 信号。
"""

import subprocess
import sys

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

if sys.platform == "win32":
    _CREATE_NO_WINDOW = 0x08000000
else:
    _CREATE_NO_WINDOW = 0


class AdbStatusService(QObject):
    """后台轮询 adb devices，上报在线设备数与首个序列号。"""

    status_changed = pyqtSignal(bool, str)  # (is_connected, serial)

    def __init__(self, adb_exe: str = "adb", interval_ms: int = 5000, parent=None) -> None:
        super().__init__(parent)
        self._adb_exe = adb_exe
        self._last_connected = None  # None = 未知，强制首次 emit
        self._last_serial = ""
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._check)
        self._timer.start()
        # 启动时立即检查一次
        QTimer.singleShot(100, self._check)

    def _check(self) -> None:
        serial = ""
        connected = False
        try:
            kwargs = {"capture_output": True, "text": True, "timeout": 3}
            if sys.platform == "win32":
                kwargs["creationflags"] = _CREATE_NO_WINDOW
            result = subprocess.run(
                [self._adb_exe, "devices"],
                **kwargs,
            )
            lines = [line.strip() for line in result.stdout.splitlines()
                     if line.strip() and "List of devices" not in line]
            for line in lines:
                parts = line.split()
                if len(parts) >= 2 and parts[1] == "device":
                    connected = True
                    serial = parts[0]
                    break
        except Exception:
            connected = False
            serial = ""

        if connected != self._last_connected or serial != self._last_serial:
            self._last_connected = connected
            self._last_serial = serial
            self.status_changed.emit(connected, serial)

    def stop(self) -> None:
        self._timer.stop()

    def force_check(self) -> None:
        """手动触发一次检查（比如用户点刷新按钮）。"""
        self._check()
