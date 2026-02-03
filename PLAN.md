# Kidlock Open Source Improvement Plan

## Executive Summary

Kidlock is a well-architected Linux parental control system with good modular design. Before open sourcing and accepting donations, several improvements are needed in testing, security, maintainability, and open source readiness.

---

## Priority 1: Critical for Open Source Release

### 1.1 Add LICENSE File
**Status:** Missing
**Impact:** Cannot legally accept contributions or donations without a license

Recommend MIT or Apache-2.0 for maximum adoption. GPL-3.0 if you want copyleft protection.

### 1.2 Add Tests
**Status:** No tests exist
**Impact:** High - security-sensitive application needs test coverage

Required test areas:
- `enforcer.py` - Schedule parsing, time limit logic, usage tracking
- `config.py` - Config loading, validation, edge cases
- `pam-check.py` - Login decision logic
- `mqtt_client.py` - Message handling, discovery payload generation
- `notifier.py` - Mocking subprocess calls

Suggested structure:
```
tests/
  test_enforcer.py
  test_config.py
  test_pam_check.py
  test_mqtt_client.py
  conftest.py
```

### 1.3 Add pyproject.toml
**Status:** Uses requirements.txt only
**Impact:** Modern Python projects expect pyproject.toml

Benefits:
- Proper package metadata (version, author, description)
- Entry points for CLI commands
- Development dependencies (pytest, mypy, ruff)
- Build system specification

### 1.4 Add GitHub CI/CD
**Status:** No .github directory
**Impact:** Pull requests won't be automatically validated

Create `.github/workflows/ci.yml`:
- Run tests on push/PR
- Lint with ruff
- Type check with mypy
- Test on multiple Python versions (3.8, 3.10, 3.11, 3.12)

---

## Priority 2: Code Quality & Maintainability

### 2.1 Fix Code Duplication
**Location:** `enforcer.py:121-138` and `pam-check.py:43-58`
**Issue:** Schedule parsing logic is duplicated

Solution: Extract to shared module `agent/schedule.py`:
```python
def is_within_schedule(schedule: ScheduleConfig) -> bool:
    """Check if current time is within allowed schedule."""
```

Import in both `enforcer.py` and `pam-check.py`.

### 2.2 Replace os.system with subprocess
**Location:** `main.py:106-113`
**Issue:** `os.system()` is a security anti-pattern

Current code:
```python
os.system(f"shutdown -h +{max(1, delay // 60)}")
```

Fix:
```python
subprocess.run(["shutdown", "-h", f"+{max(1, delay // 60)}"], check=True)
```

### 2.3 Add Config Validation
**Location:** `config.py`
**Issue:** Invalid config values silently use defaults or cause runtime errors

Add validation:
- Schedule format validation (HH:MM-HH:MM)
- Port range validation (1-65535)
- Username existence check (optional warning)
- daily_minutes >= 0
- poll_interval >= 1
- warnings list sorted descending

### 2.4 Improve Error Handling
**Multiple locations**
**Issue:** Broad `except Exception` catches hide specific errors

Replace with specific exceptions:
```python
# Bad
except Exception as e:
    log.error(f"Failed: {e}")

# Good
except json.JSONDecodeError as e:
    log.error(f"Invalid JSON in state file: {e}")
except PermissionError as e:
    log.error(f"Cannot read state file (permission denied): {e}")
```

### 2.5 Extract Magic Numbers to Constants
**Multiple locations**

| Current | Suggested Constant | Location |
|---------|-------------------|----------|
| `60` | `MQTT_KEEPALIVE_SECONDS` | mqtt_client.py:91 |
| `30` | `DEFAULT_CONNECTION_TIMEOUT` | main.py:254 |
| `10` | `SUBPROCESS_TIMEOUT_SHORT` | enforcer.py:110 |
| `5` | `SUBPROCESS_TIMEOUT_VERY_SHORT` | notifier.py:28 |

### 2.6 Add Type Hints Throughout
**Status:** Partial coverage
**Files needing improvement:**
- `notifier.py` - Missing return types on some methods
- `dns_blocker.py` - Missing Optional annotations
- `tray/kidlock-tray.py` - No type hints

---

## Priority 3: Feature Improvements

### 3.1 Add Schedule End Warning
**Issue:** Users get warned about time limits but not about schedule ending

Add to `enforcer.py`:
```python
def get_minutes_until_schedule_end(self, schedule: ScheduleConfig) -> int:
    """Get minutes until allowed hours end."""
```

Then in `main.py`, send warning 10/5 minutes before schedule ends.

### 3.2 Make DNS Upstream Configurable
**Location:** `dns_blocker.py:22`
**Issue:** Hardcoded `8.8.8.8`

Add to config:
```yaml
dns_blocking:
  upstream_dns: "8.8.8.8"  # or 1.1.1.1, etc.
  whitelist:
    - google.com
    - wikipedia.org
```

### 3.3 Add MQTT Reconnection Logic
**Location:** `mqtt_client.py`
**Issue:** Uses paho-mqtt's auto-reconnect but doesn't re-publish discovery on reconnect

Add:
```python
def _on_connect(self, ...):
    if rc == 0:
        # Re-publish discovery on reconnect
        self.publish_ha_discovery(self._users)
```

### 3.4 Optimize Tray App
**Location:** `tray/kidlock-tray.py:100-107`
**Issue:** Reads config file on every update (every 30 seconds)

Fix: Cache config and only reload on file modification:
```python
def __init__(self):
    self._config = None
    self._config_mtime = 0

def _get_config(self):
    mtime = CONFIG_FILE.stat().st_mtime
    if mtime != self._config_mtime:
        self._config = load_config()
        self._config_mtime = mtime
    return self._config
```

### 3.5 Add Health Check
**Issue:** No way to check if service is healthy without checking logs

Options:
1. Create `/var/run/kidlock/health` file with timestamp
2. Add HTTP health endpoint (more complex)
3. Add systemd watchdog integration

---

## Priority 4: Open Source Readiness

### 4.1 Add CONTRIBUTING.md
Content should include:
- How to set up development environment
- How to run tests
- Code style guidelines
- PR process
- Issue reporting guidelines

### 4.2 Add CODE_OF_CONDUCT.md
Use standard Contributor Covenant.

### 4.3 Add CHANGELOG.md
Start with current state as v1.0.0:
```markdown
# Changelog

## [1.0.0] - 2024-XX-XX
### Added
- Initial public release
- PAM integration for login blocking
- Home Assistant MQTT integration
- Desktop notifications
- System tray indicator
```

### 4.4 Add Issue Templates
Create `.github/ISSUE_TEMPLATE/`:
- `bug_report.md`
- `feature_request.md`

### 4.5 Add PR Template
Create `.github/pull_request_template.md`

### 4.6 Add Funding Configuration
Create `.github/FUNDING.yml`:
```yaml
github: your-username
ko_fi: your-username
# or
patreon: your-username
```

### 4.7 Add Security Policy
Create `SECURITY.md` explaining how to report vulnerabilities.

---

## Priority 5: Documentation Improvements

### 5.1 Add Architecture Diagram
Add ASCII or Mermaid diagram to README showing:
- Service components
- Data flow
- MQTT topics

### 5.2 Document Permissions Required
Add section explaining:
- Why root is required
- What PAM integration does
- State file permissions rationale

### 5.3 Add Troubleshooting Expansion
Current troubleshooting is good, add:
- Common MQTT broker configurations (Mosquitto)
- Wayland vs X11 notification differences
- Multi-display setups

---

## Implementation Order Recommendation

### Phase 1: Legal & Critical (Before Open Source)
1. Add LICENSE
2. Add basic tests for enforcer and config
3. Add pyproject.toml
4. Fix os.system security issue

### Phase 2: Quality (First Week)
5. Add GitHub Actions CI
6. Fix code duplication
7. Add config validation
8. Add comprehensive type hints

### Phase 3: Community (First Month)
9. Add CONTRIBUTING.md
10. Add CODE_OF_CONDUCT.md
11. Add issue/PR templates
12. Add CHANGELOG.md

### Phase 4: Polish (Ongoing)
13. Add remaining tests
14. Feature improvements
15. Documentation improvements

---

## Estimated Effort

| Phase | Items | Effort |
|-------|-------|--------|
| Phase 1 | 4 items | 1-2 days |
| Phase 2 | 4 items | 2-3 days |
| Phase 3 | 4 items | 1 day |
| Phase 4 | Ongoing | As needed |

---

## Questions to Clarify

1. **License preference?** MIT (permissive), Apache-2.0 (patent protection), or GPL-3.0 (copyleft)?
2. **Donation platform preference?** GitHub Sponsors, Ko-fi, Patreon, or multiple?
3. **Python version support?** Recommend 3.8+ minimum for wide compatibility
4. **Do you want Windows support?** There's a stub `platform/windows.py` - remove or implement?
