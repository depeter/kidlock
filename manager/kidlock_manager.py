#!/usr/bin/env python3
"""KidLock Manager — Desktop application for managing kidlock devices over MQTT."""

import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import paho.mqtt.client as mqtt
from PyQt5.QtCore import Qt, pyqtSignal, QObject
from PyQt5.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QFrame,
    QProgressBar,
    QSpinBox,
    QLineEdit,
    QTextEdit,
    QGridLayout,
    QDialog,
    QFormLayout,
    QDialogButtonBox,
    QSystemTrayIcon,
    QMenu,
    QSplitter,
    QMessageBox,
    QInputDialog,
)

# ---------------------------------------------------------------------------
# Settings persistence
# ---------------------------------------------------------------------------

CONFIG_DIR = Path.home() / ".config" / "kidlock-manager"
CONFIG_FILE = CONFIG_DIR / "settings.json"

DEFAULT_SETTINGS = {
    "broker": "",
    "port": 1883,
    "username": "",
    "password": "",
}


def load_settings():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return {**DEFAULT_SETTINGS, **json.load(f)}
    return dict(DEFAULT_SETTINGS)


def save_settings(settings):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(settings, f, indent=2)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class UserState:
    username: str = ""
    hostname: str = ""
    active: bool = False
    usage_minutes: int = 0
    daily_limit: int = 0
    time_remaining: int = -1
    blocked: bool = False
    block_reason: str = ""
    paused: bool = False
    bonus_minutes: int = 0
    is_idle: bool = False
    status: str = "Offline"
    current_app: str = ""
    top_apps: list = field(default_factory=list)
    has_pending_request: bool = False
    pending_request: dict = field(default_factory=dict)
    schedule_weekday: str = ""
    schedule_weekend: str = ""
    last_seen: float = 0.0

    @classmethod
    def from_mqtt(cls, hostname, data):
        return cls(
            username=data.get("username", ""),
            hostname=hostname,
            active=data.get("active", False),
            usage_minutes=data.get("usage_minutes", 0),
            daily_limit=data.get("daily_limit", 0),
            time_remaining=data.get("time_remaining", -1),
            blocked=data.get("blocked", False),
            block_reason=data.get("block_reason", ""),
            paused=data.get("paused", False),
            bonus_minutes=data.get("bonus_minutes", 0),
            is_idle=data.get("is_idle", False),
            status=data.get("status", "Offline"),
            current_app=data.get("current_app", ""),
            top_apps=data.get("top_apps", []),
            has_pending_request=data.get("has_pending_request", False),
            pending_request=data.get("pending_request") or {},
            schedule_weekday=data.get("schedule_weekday", ""),
            schedule_weekend=data.get("schedule_weekend", ""),
            last_seen=time.time(),
        )


# ---------------------------------------------------------------------------
# MQTT ↔ Qt bridge (thread-safe via signals)
# ---------------------------------------------------------------------------


class MQTTSignals(QObject):
    user_updated = pyqtSignal(str, str, dict)  # hostname, username, payload
    device_online = pyqtSignal(str, bool)       # hostname, is_online
    event = pyqtSignal(str, dict)               # hostname, event_data
    tamper = pyqtSignal(str, dict)              # hostname, tamper_data
    update_status = pyqtSignal(str, dict)       # hostname, update_data
    connected = pyqtSignal()
    disconnected = pyqtSignal(str)              # reason


class MQTTManager:
    def __init__(self, signals: MQTTSignals):
        self.signals = signals
        # Support both paho-mqtt v1 and v2
        try:
            self.client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION1,
                client_id="kidlock-manager",
            )
        except (AttributeError, TypeError):
            self.client = mqtt.Client(client_id="kidlock-manager")
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self._connected = False

    def connect(self, broker, port, username="", password=""):
        if username:
            self.client.username_pw_set(username, password)
        self.client.will_set("kidlock-manager/status", "offline", retain=True)
        self.client.connect_async(broker, port)
        self.client.loop_start()

    def disconnect(self):
        self.client.loop_stop()
        self.client.disconnect()
        self._connected = False

    def publish_command(self, hostname, action, **kwargs):
        payload = {"action": action, **kwargs}
        self.client.publish(f"parental/{hostname}/command", json.dumps(payload))

    # -- callbacks (called from network thread) ----------------------------

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._connected = True
            client.subscribe("parental/+/user/+")
            client.subscribe("parental/+/status")
            client.subscribe("parental/+/event")
            client.subscribe("parental/+/tamper")
            client.subscribe("parental/+/update")
            self.signals.connected.emit()
        else:
            reasons = {
                1: "incorrect protocol",
                2: "invalid client ID",
                3: "server unavailable",
                4: "bad credentials",
                5: "not authorized",
            }
            self.signals.disconnected.emit(
                f"Connection refused: {reasons.get(rc, f'error {rc}')}"
            )

    def _on_disconnect(self, client, userdata, rc):
        self._connected = False
        if rc != 0:
            self.signals.disconnected.emit("Connection lost — reconnecting…")
        else:
            self.signals.disconnected.emit("Disconnected")

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            return

        parts = msg.topic.split("/")
        if len(parts) < 3 or parts[0] != "parental":
            return

        hostname = parts[1]
        subtopic = parts[2]

        if subtopic == "user" and len(parts) == 4:
            self.signals.user_updated.emit(hostname, parts[3], payload)
        elif subtopic == "status":
            self.signals.device_online.emit(
                hostname, payload.get("state") == "online"
            )
        elif subtopic == "event":
            self.signals.event.emit(hostname, payload)
        elif subtopic == "tamper":
            self.signals.tamper.emit(hostname, payload)
        elif subtopic == "update":
            self.signals.update_status.emit(hostname, payload)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

STATUS_COLORS = {
    "Playing": "#4caf50",
    "Paused": "#ff9800",
    "Blocked": "#f44336",
    "Offline": "#9e9e9e",
    "Overridden": "#2196f3",
}

EVENT_COLORS = {
    "login": "#4caf50",
    "logout": "#9e9e9e",
    "time_warning": "#ff9800",
    "time_exhausted": "#f44336",
    "time_request": "#2196f3",
    "request_approved": "#4caf50",
    "request_denied": "#f44336",
    "clock_tamper": "#f44336",
    "bonus_time": "#4caf50",
    "pause_changed": "#ff9800",
}


def make_circle_icon(color_hex, size=64):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(color_hex))
    p.setPen(Qt.NoPen)
    p.drawEllipse(4, 4, size - 8, size - 8)
    p.end()
    return QIcon(pixmap)


def fmt_minutes(minutes):
    if minutes < 0:
        return "unlimited"
    h, m = divmod(int(minutes), 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


def progress_color(pct):
    if pct < 50:
        return "#4caf50"
    if pct < 80:
        return "#ff9800"
    if pct < 95:
        return "#ff5722"
    return "#f44336"


# ---------------------------------------------------------------------------
# User card — one per user per device
# ---------------------------------------------------------------------------

CARD_CSS = """
UserCard {
    border: 1px solid palette(mid);
    border-radius: 8px;
    padding: 8px;
    margin: 2px 0px;
    background: palette(base);
}
"""

REQUEST_CSS = """
QFrame#requestFrame {
    background: #fff3e0;
    border: 2px solid #ff9800;
    border-radius: 6px;
    padding: 6px;
}
"""

BTN_RED = "QPushButton { background: #f44336; color: white; padding: 4px 12px; border-radius: 4px; }"
BTN_GREEN = "QPushButton { background: #4caf50; color: white; padding: 4px 12px; border-radius: 4px; }"
BTN_BLUE = "QPushButton { background: #2196f3; color: white; padding: 4px 12px; border-radius: 4px; }"


class UserCard(QFrame):
    def __init__(self, hostname, username, mqtt_mgr, parent=None):
        super().__init__(parent)
        self.hostname = hostname
        self.username = username
        self.mqtt = mqtt_mgr
        self.state = UserState(username=username, hostname=hostname)
        self.setObjectName("userCard")
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(CARD_CSS)
        self._build()

    # -- layout ------------------------------------------------------------

    def _build(self):
        root = QVBoxLayout(self)
        root.setSpacing(6)

        # Header: dot + name + status
        hdr = QHBoxLayout()
        self.dot = QLabel("\u25cf")
        self.dot.setFont(QFont("", 18))
        self.dot.setFixedWidth(28)
        hdr.addWidget(self.dot)
        self.lbl_name = QLabel(self.username)
        self.lbl_name.setFont(QFont("", 14, QFont.Bold))
        hdr.addWidget(self.lbl_name)
        hdr.addStretch()
        self.lbl_status = QLabel("Offline")
        self.lbl_status.setFont(QFont("", 12))
        hdr.addWidget(self.lbl_status)
        root.addLayout(hdr)

        # Progress bar
        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        self.progress.setMinimumHeight(22)
        root.addWidget(self.progress)

        # Info grid
        grid = QGridLayout()
        grid.setSpacing(4)
        self.lbl_remaining = QLabel("-")
        self.lbl_app = QLabel("-")
        self.lbl_sched_wd = QLabel("-")
        self.lbl_sched_we = QLabel("-")
        self.lbl_top_apps = QLabel("-")
        self.lbl_top_apps.setWordWrap(True)

        r = 0
        grid.addWidget(QLabel("Remaining:"), r, 0)
        grid.addWidget(self.lbl_remaining, r, 1)
        grid.addWidget(QLabel("Current app:"), r, 2)
        grid.addWidget(self.lbl_app, r, 3)
        r += 1
        grid.addWidget(QLabel("Weekday:"), r, 0)
        grid.addWidget(self.lbl_sched_wd, r, 1)
        grid.addWidget(QLabel("Weekend:"), r, 2)
        grid.addWidget(self.lbl_sched_we, r, 3)
        r += 1
        grid.addWidget(QLabel("Top apps:"), r, 0)
        grid.addWidget(self.lbl_top_apps, r, 1, 1, 3)
        root.addLayout(grid)

        # Action buttons
        acts = QHBoxLayout()
        self.btn_lock = QPushButton("Lock")
        self.btn_lock.setStyleSheet(BTN_RED)
        self.btn_lock.clicked.connect(lambda: self._cmd("lock"))
        self.btn_unlock = QPushButton("Unlock")
        self.btn_unlock.setStyleSheet(BTN_GREEN)
        self.btn_unlock.clicked.connect(lambda: self._cmd("unlock"))
        self.btn_pause = QPushButton("Pause")
        self.btn_pause.clicked.connect(lambda: self._cmd("pause"))
        self.btn_resume = QPushButton("Resume")
        self.btn_resume.clicked.connect(lambda: self._cmd("resume"))
        self.btn_add15 = QPushButton("+15m")
        self.btn_add15.setStyleSheet(BTN_BLUE)
        self.btn_add15.clicked.connect(lambda: self._cmd("add_time", minutes=15))
        self.btn_add30 = QPushButton("+30m")
        self.btn_add30.setStyleSheet(BTN_BLUE)
        self.btn_add30.clicked.connect(lambda: self._cmd("add_time", minutes=30))
        self.btn_add_custom = QPushButton("+Custom")
        self.btn_add_custom.clicked.connect(self._add_custom_time)
        for b in (
            self.btn_lock,
            self.btn_unlock,
            self.btn_pause,
            self.btn_resume,
            self.btn_add15,
            self.btn_add30,
            self.btn_add_custom,
        ):
            acts.addWidget(b)
        root.addLayout(acts)

        # Schedule / limit editing
        edit = QHBoxLayout()
        edit.addWidget(QLabel("Daily limit:"))
        self.spin_limit = QSpinBox()
        self.spin_limit.setRange(0, 720)
        self.spin_limit.setSingleStep(5)
        self.spin_limit.setSuffix(" min")
        self.spin_limit.setSpecialValueText("unlimited")
        edit.addWidget(self.spin_limit)
        btn_set_lim = QPushButton("Set")
        btn_set_lim.clicked.connect(self._set_limit)
        edit.addWidget(btn_set_lim)
        edit.addSpacing(16)
        edit.addWidget(QLabel("WD:"))
        self.edit_wd = QLineEdit()
        self.edit_wd.setPlaceholderText("HH:MM-HH:MM")
        self.edit_wd.setMaximumWidth(120)
        edit.addWidget(self.edit_wd)
        edit.addWidget(QLabel("WE:"))
        self.edit_we = QLineEdit()
        self.edit_we.setPlaceholderText("HH:MM-HH:MM")
        self.edit_we.setMaximumWidth(120)
        edit.addWidget(self.edit_we)
        btn_set_sched = QPushButton("Set Schedule")
        btn_set_sched.clicked.connect(self._set_schedule)
        edit.addWidget(btn_set_sched)
        edit.addStretch()
        root.addLayout(edit)

        # Pending-request banner (hidden by default)
        self.req_frame = QFrame()
        self.req_frame.setObjectName("requestFrame")
        self.req_frame.setStyleSheet(REQUEST_CSS)
        rl = QHBoxLayout(self.req_frame)
        self.lbl_request = QLabel()
        self.lbl_request.setFont(QFont("", 11))
        rl.addWidget(self.lbl_request)
        rl.addStretch()
        btn_approve = QPushButton("Approve")
        btn_approve.setStyleSheet(BTN_GREEN + " QPushButton { font-weight: bold; }")
        btn_approve.clicked.connect(lambda: self._cmd("approve_request"))
        btn_deny = QPushButton("Deny")
        btn_deny.setStyleSheet(BTN_RED + " QPushButton { font-weight: bold; }")
        btn_deny.clicked.connect(lambda: self._cmd("deny_request"))
        rl.addWidget(btn_approve)
        rl.addWidget(btn_deny)
        self.req_frame.setVisible(False)
        root.addWidget(self.req_frame)

    # -- state updates -----------------------------------------------------

    def update_state(self, data):
        self.state = UserState.from_mqtt(self.hostname, data)
        self._refresh()

    def _refresh(self):
        s = self.state
        color = STATUS_COLORS.get(s.status, "#9e9e9e")
        self.dot.setStyleSheet(f"color: {color};")

        status_text = s.status
        if s.is_idle and s.active:
            status_text += " (idle)"
        if s.blocked and s.block_reason:
            status_text += f" — {s.block_reason}"
        self.lbl_status.setText(status_text)

        # Progress
        if s.daily_limit > 0:
            total = s.daily_limit + s.bonus_minutes
            pct = min(100, int(s.usage_minutes / total * 100)) if total else 0
            self.progress.setMaximum(total)
            self.progress.setValue(min(s.usage_minutes, total))
            bonus_note = f"  (+{s.bonus_minutes}m bonus)" if s.bonus_minutes else ""
            self.progress.setFormat(
                f"{fmt_minutes(s.usage_minutes)} / {fmt_minutes(total)}{bonus_note}"
            )
            bc = progress_color(pct)
            self.progress.setStyleSheet(
                f"QProgressBar {{ border:1px solid #ccc; border-radius:4px; "
                f"text-align:center; background:#e0e0e0; }}"
                f"QProgressBar::chunk {{ background:{bc}; border-radius:3px; }}"
            )
        else:
            self.progress.setMaximum(1)
            self.progress.setValue(0)
            self.progress.setFormat(f"{fmt_minutes(s.usage_minutes)} used (no limit)")
            self.progress.setStyleSheet("")

        # Info labels
        self.lbl_remaining.setText(
            fmt_minutes(s.time_remaining) if s.time_remaining >= 0 else "unlimited"
        )
        self.lbl_app.setText(s.current_app or "-")
        self.lbl_sched_wd.setText(s.schedule_weekday or "-")
        self.lbl_sched_we.setText(s.schedule_weekend or "-")

        if s.top_apps:
            self.lbl_top_apps.setText(
                ", ".join(f"{a['app']} ({a['minutes']}m)" for a in s.top_apps[:5])
            )
        else:
            self.lbl_top_apps.setText("-")

        # Populate edit fields only when they don't have focus
        if not self.spin_limit.hasFocus():
            self.spin_limit.setValue(s.daily_limit)
        if not self.edit_wd.hasFocus():
            self.edit_wd.setText(s.schedule_weekday)
        if not self.edit_we.hasFocus():
            self.edit_we.setText(s.schedule_weekend)

        # Button sensitivity
        self.btn_lock.setEnabled(not s.blocked)
        self.btn_unlock.setEnabled(s.blocked)
        self.btn_pause.setEnabled(s.active and not s.paused)
        self.btn_resume.setEnabled(s.paused)

        # Pending request
        if s.has_pending_request and s.pending_request:
            req = s.pending_request
            mins = req.get("minutes", "?")
            reason = req.get("reason", "")
            txt = f"Time request: {mins} minutes"
            if reason:
                txt += f'  —  "{reason}"'
            self.lbl_request.setText(txt)
            self.req_frame.setVisible(True)
        else:
            self.req_frame.setVisible(False)

    # -- commands ----------------------------------------------------------

    def _cmd(self, action, **kw):
        self.mqtt.publish_command(self.hostname, action, user=self.username, **kw)

    def _add_custom_time(self):
        mins, ok = QInputDialog.getInt(
            self, "Add Time", f"Minutes to add for {self.username}:", 15, 1, 480, 5
        )
        if ok:
            self._cmd("add_time", minutes=mins)

    def _set_limit(self):
        self._cmd("set_daily_limit", minutes=self.spin_limit.value())

    def _set_schedule(self):
        pat = re.compile(r"^\d{2}:\d{2}-\d{2}:\d{2}$")
        wd = self.edit_wd.text().strip()
        we = self.edit_we.text().strip()
        if wd and not pat.match(wd):
            QMessageBox.warning(self, "Invalid", "Weekday format: HH:MM-HH:MM")
            return
        if we and not pat.match(we):
            QMessageBox.warning(self, "Invalid", "Weekend format: HH:MM-HH:MM")
            return
        if wd:
            self._cmd("set_schedule", day="weekday", schedule=wd)
        if we:
            self._cmd("set_schedule", day="weekend", schedule=we)


# ---------------------------------------------------------------------------
# Device panel — one per hostname
# ---------------------------------------------------------------------------


class DevicePanel(QFrame):
    def __init__(self, hostname, mqtt_mgr, parent=None):
        super().__init__(parent)
        self.hostname = hostname
        self.mqtt = mqtt_mgr
        self.online = False
        self.user_cards: dict[str, UserCard] = {}

        self.setFrameShape(QFrame.NoFrame)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Header
        hdr = QHBoxLayout()
        self.dot = QLabel("\u25cf")
        self.dot.setFont(QFont("", 14))
        self.dot.setStyleSheet("color: #9e9e9e;")
        hdr.addWidget(self.dot)
        self.lbl_title = QLabel(hostname)
        self.lbl_title.setFont(QFont("", 13, QFont.Bold))
        hdr.addWidget(self.lbl_title)
        hdr.addStretch()

        btn_shutdown = QPushButton("Shutdown")
        btn_shutdown.setToolTip("Shut down this device")
        btn_shutdown.clicked.connect(self._shutdown)
        hdr.addWidget(btn_shutdown)
        btn_restart = QPushButton("Restart")
        btn_restart.setToolTip("Restart this device")
        btn_restart.clicked.connect(self._restart)
        hdr.addWidget(btn_restart)
        layout.addLayout(hdr)

        self.cards_layout = QVBoxLayout()
        layout.addLayout(self.cards_layout)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep)

    def set_online(self, online):
        self.online = online
        c = "#4caf50" if online else "#9e9e9e"
        self.dot.setStyleSheet(f"color: {c};")
        suffix = "" if online else " (offline)"
        self.lbl_title.setText(f"{self.hostname}{suffix}")

    def get_or_create_card(self, username) -> UserCard:
        if username not in self.user_cards:
            card = UserCard(self.hostname, username, self.mqtt, self)
            self.user_cards[username] = card
            self.cards_layout.addWidget(card)
        return self.user_cards[username]

    def _shutdown(self):
        if (
            QMessageBox.question(
                self, "Confirm", f"Shut down {self.hostname}?",
                QMessageBox.Yes | QMessageBox.No,
            )
            == QMessageBox.Yes
        ):
            self.mqtt.publish_command(self.hostname, "shutdown")

    def _restart(self):
        if (
            QMessageBox.question(
                self, "Confirm", f"Restart {self.hostname}?",
                QMessageBox.Yes | QMessageBox.No,
            )
            == QMessageBox.Yes
        ):
            self.mqtt.publish_command(self.hostname, "restart")


# ---------------------------------------------------------------------------
# Event log
# ---------------------------------------------------------------------------


class EventLog(QWidget):
    MAX_LINES = 500

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("Event Log"))
        hdr.addStretch()
        btn_clear = QPushButton("Clear")
        btn_clear.clicked.connect(self.clear)
        hdr.addWidget(btn_clear)
        layout.addLayout(hdr)

        self.text = QTextEdit()
        self.text.setReadOnly(True)
        self.text.setFont(QFont("monospace", 10))
        self.text.setMaximumHeight(200)
        layout.addWidget(self.text)

    def add_event(self, hostname, data):
        ts = data.get("timestamp", "")
        if ts:
            try:
                ts = datetime.fromisoformat(ts).strftime("%H:%M:%S")
            except ValueError:
                ts = ts[:8]

        event = data.get("event", "unknown")
        user = data.get("user", "")
        extras = {k: v for k, v in data.items() if k not in ("event", "user", "timestamp")}
        detail = ""
        if extras:
            detail = "  " + " ".join(f"{k}={v}" for k, v in extras.items())

        color = EVENT_COLORS.get(event, "#666")
        self.text.append(
            f'<span style="color:#888">{ts}</span> '
            f'<span style="color:#666">{hostname}</span> '
            f"<b>{user}</b> "
            f'<span style="color:{color}">{event}</span>'
            f"{detail}"
        )

        if self.text.document().blockCount() > self.MAX_LINES:
            cur = self.text.textCursor()
            cur.movePosition(cur.Start)
            cur.movePosition(cur.Down, cur.KeepAnchor, 50)
            cur.removeSelectedText()

    def clear(self):
        self.text.clear()


# ---------------------------------------------------------------------------
# Settings dialog
# ---------------------------------------------------------------------------


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("MQTT Connection Settings")
        self.setMinimumWidth(360)

        layout = QFormLayout(self)
        self.edit_broker = QLineEdit(settings.get("broker", ""))
        self.edit_broker.setPlaceholderText("e.g. homeassistant.local")
        self.spin_port = QSpinBox()
        self.spin_port.setRange(1, 65535)
        self.spin_port.setValue(settings.get("port", 1883))
        self.edit_user = QLineEdit(settings.get("username", ""))
        self.edit_pass = QLineEdit(settings.get("password", ""))
        self.edit_pass.setEchoMode(QLineEdit.Password)

        layout.addRow("Broker:", self.edit_broker)
        layout.addRow("Port:", self.spin_port)
        layout.addRow("Username:", self.edit_user)
        layout.addRow("Password:", self.edit_pass)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def get_settings(self):
        return {
            "broker": self.edit_broker.text().strip(),
            "port": self.spin_port.value(),
            "username": self.edit_user.text().strip(),
            "password": self.edit_pass.text(),
        }


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("KidLock Manager")
        self.setMinimumSize(900, 600)
        self.resize(1050, 750)

        self.settings = load_settings()
        self.device_panels: dict[str, DevicePanel] = {}
        self._known_requests: set[str] = set()

        # MQTT
        self.signals = MQTTSignals()
        self.mqtt = MQTTManager(self.signals)

        self.signals.user_updated.connect(self._on_user_updated)
        self.signals.device_online.connect(self._on_device_online)
        self.signals.event.connect(self._on_event)
        self.signals.connected.connect(self._on_connected)
        self.signals.disconnected.connect(self._on_disconnected)

        self._build_ui()
        self._setup_tray()

        # Auto-connect on start if broker is configured
        if self.settings.get("broker"):
            self._do_connect()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # Toolbar row
        bar = QHBoxLayout()
        self.btn_connect = QPushButton("Connect")
        self.btn_connect.clicked.connect(self._toggle_connect)
        bar.addWidget(self.btn_connect)
        btn_settings = QPushButton("Settings")
        btn_settings.clicked.connect(self._show_settings)
        bar.addWidget(btn_settings)
        bar.addStretch()
        self.lbl_status = QLabel("\u25cf Disconnected")
        self.lbl_status.setStyleSheet("color: #f44336; font-weight: bold;")
        bar.addWidget(self.lbl_status)
        root.addLayout(bar)

        # Splitter: scrollable device area | event log
        splitter = QSplitter(Qt.Vertical)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self.devices_widget = QWidget()
        self.devices_layout = QVBoxLayout(self.devices_widget)
        self.devices_layout.addStretch()
        scroll.setWidget(self.devices_widget)
        splitter.addWidget(scroll)

        self.event_log = EventLog()
        splitter.addWidget(self.event_log)
        splitter.setSizes([500, 200])
        root.addWidget(splitter)

        self.statusBar().showMessage("Not connected")

    def _setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self._tray = None
            return
        self._tray = QSystemTrayIcon(self)
        self._tray.setIcon(make_circle_icon("#2196f3"))
        self._tray.setToolTip("KidLock Manager")

        menu = QMenu()
        act_show = menu.addAction("Show")
        act_show.triggered.connect(self._show_window)
        act_quit = menu.addAction("Quit")
        act_quit.triggered.connect(self._quit)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._tray_clicked)
        self._tray.show()

    def _show_window(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def _tray_clicked(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self._show_window()

    # -- connection --------------------------------------------------------

    def _do_connect(self):
        s = self.settings
        self.mqtt.connect(s["broker"], s["port"], s.get("username", ""), s.get("password", ""))
        self.lbl_status.setText("\u25cf Connecting\u2026")
        self.lbl_status.setStyleSheet("color: #ff9800; font-weight: bold;")
        self.btn_connect.setText("Disconnect")

    def _do_disconnect(self):
        self.mqtt.disconnect()
        self.btn_connect.setText("Connect")
        self.lbl_status.setText("\u25cf Disconnected")
        self.lbl_status.setStyleSheet("color: #f44336; font-weight: bold;")
        self.statusBar().showMessage("Disconnected")

    def _toggle_connect(self):
        if self.mqtt._connected:
            self._do_disconnect()
        else:
            if not self.settings.get("broker"):
                self._show_settings()
                return
            self._do_connect()

    def _show_settings(self):
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec_() == QDialog.Accepted:
            self.settings = dlg.get_settings()
            save_settings(self.settings)
            if self.mqtt._connected:
                self._do_disconnect()
                self._do_connect()

    # -- signal handlers ---------------------------------------------------

    def _on_connected(self):
        self.lbl_status.setText("\u25cf Connected")
        self.lbl_status.setStyleSheet("color: #4caf50; font-weight: bold;")
        self.statusBar().showMessage(f"Connected to {self.settings['broker']}")
        self.btn_connect.setText("Disconnect")

    def _on_disconnected(self, reason):
        self.lbl_status.setText(f"\u25cf {reason}")
        self.lbl_status.setStyleSheet("color: #f44336; font-weight: bold;")
        self.statusBar().showMessage(reason)

    def _get_device(self, hostname) -> DevicePanel:
        if hostname not in self.device_panels:
            panel = DevicePanel(hostname, self.mqtt, self)
            self.device_panels[hostname] = panel
            self.devices_layout.insertWidget(self.devices_layout.count() - 1, panel)
        return self.device_panels[hostname]

    def _on_user_updated(self, hostname, username, data):
        device = self._get_device(hostname)
        card = device.get_or_create_card(username)
        card.update_state(data)

        # Desktop notification for new time requests
        key = f"{hostname}/{username}"
        has_req = data.get("has_pending_request", False)
        if has_req and key not in self._known_requests:
            self._known_requests.add(key)
            req = data.get("pending_request") or {}
            mins = req.get("minutes", "?")
            reason = req.get("reason", "")
            msg = f"{username}@{hostname} requests {mins} minutes"
            if reason:
                msg += f": {reason}"
            if self._tray:
                self._tray.showMessage("Time Request", msg, QSystemTrayIcon.Information, 10000)
        elif not has_req:
            self._known_requests.discard(key)

    def _on_device_online(self, hostname, online):
        self._get_device(hostname).set_online(online)

    def _on_event(self, hostname, data):
        self.event_log.add_event(hostname, data)

    # -- window lifecycle --------------------------------------------------

    def closeEvent(self, event):
        if self._tray:
            event.ignore()
            self.hide()
            self._tray.showMessage(
                "KidLock Manager",
                "Still running in the system tray.",
                QSystemTrayIcon.Information,
                2000,
            )
        else:
            self._quit()

    def _quit(self):
        self.mqtt.disconnect()
        QApplication.quit()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("KidLock Manager")
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(make_circle_icon("#2196f3"))

    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
