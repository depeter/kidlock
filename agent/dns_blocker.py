"""DNS-based website blocking using dnsmasq for Kidlock agent."""

import logging
import subprocess
from typing import List, Optional

log = logging.getLogger(__name__)

# Default whitelist includes common CDNs and essential services
DEFAULT_WHITELIST = [
    "google.com",
    "googleapis.com",
    "gstatic.com",
    "duckduckgo.com",
    "wikipedia.org",
    "wikimedia.org",
    "cloudflare.com",
    "akamaihd.net",
]

DNSMASQ_CONFIG_PATH = "/etc/dnsmasq.d/kidlock.conf"
UPSTREAM_DNS = "8.8.8.8"


class DnsBlocker:
    """Manages DNS-based website whitelisting via dnsmasq.

    When enabled, blocks all domains by default and only allows
    whitelisted domains to resolve via upstream DNS.
    """

    def __init__(self, enabled: bool = False, whitelist: Optional[List[str]] = None):
        self._enabled = enabled
        self._whitelist = whitelist or []
        log.info(f"DnsBlocker initialized: enabled={enabled}, whitelist={self._whitelist}")

    @property
    def enabled(self) -> bool:
        """Whether DNS blocking is currently enabled."""
        return self._enabled

    @property
    def whitelist(self) -> List[str]:
        """Current whitelist of allowed domains."""
        return self._whitelist

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable DNS blocking.

        Args:
            enabled: True to enable blocking, False to disable.
        """
        if enabled == self._enabled:
            return

        self._enabled = enabled
        log.info(f"DNS blocking {'enabled' if enabled else 'disabled'}")

        if enabled:
            self._write_config()
            self._restart_dnsmasq()
        else:
            self._clear_config()
            self._restart_dnsmasq()

    def update_whitelist(self, domains: List[str]) -> None:
        """Update the whitelist of allowed domains.

        Args:
            domains: List of domain names to allow (e.g., ["google.com", "youtube.com"]).
        """
        # Normalize domains (strip whitespace, lowercase)
        normalized = [d.strip().lower() for d in domains if d.strip()]

        if normalized == self._whitelist:
            return

        self._whitelist = normalized
        log.info(f"Whitelist updated: {self._whitelist}")

        if self._enabled:
            self._write_config()
            self._restart_dnsmasq()

    def _get_effective_whitelist(self) -> List[str]:
        """Get whitelist including default entries."""
        combined = set(DEFAULT_WHITELIST)
        combined.update(self._whitelist)
        return sorted(combined)

    def _generate_config(self) -> str:
        """Generate dnsmasq configuration content."""
        lines = [
            "# Kidlock DNS blocking configuration",
            "# Auto-generated - do not edit manually",
            "",
            "# Block all domains by default (return NXDOMAIN)",
            "address=/#/",
            "",
            "# Whitelisted domains - forward to upstream DNS",
        ]

        for domain in self._get_effective_whitelist():
            # Allow the domain and all subdomains
            lines.append(f"server=/{domain}/{UPSTREAM_DNS}")
            lines.append(f"server=/.{domain}/{UPSTREAM_DNS}")

        lines.append("")
        return "\n".join(lines)

    def _write_config(self) -> None:
        """Write dnsmasq configuration file via sudo."""
        config_content = self._generate_config()
        log.debug(f"Writing dnsmasq config:\n{config_content}")

        try:
            # Use sudo tee to write the config file
            proc = subprocess.run(
                ["sudo", "/usr/bin/tee", DNSMASQ_CONFIG_PATH],
                input=config_content.encode(),
                capture_output=True,
                timeout=10,
            )
            if proc.returncode != 0:
                log.error(f"Failed to write dnsmasq config: {proc.stderr.decode()}")
            else:
                log.info(f"Wrote dnsmasq config to {DNSMASQ_CONFIG_PATH}")
        except subprocess.TimeoutExpired:
            log.error("Timeout writing dnsmasq config")
        except Exception as e:
            log.error(f"Error writing dnsmasq config: {e}")

    def _clear_config(self) -> None:
        """Clear the dnsmasq configuration (disable blocking)."""
        config_content = "# Kidlock DNS blocking disabled\n"

        try:
            proc = subprocess.run(
                ["sudo", "/usr/bin/tee", DNSMASQ_CONFIG_PATH],
                input=config_content.encode(),
                capture_output=True,
                timeout=10,
            )
            if proc.returncode != 0:
                log.error(f"Failed to clear dnsmasq config: {proc.stderr.decode()}")
            else:
                log.info("Cleared dnsmasq config (blocking disabled)")
        except subprocess.TimeoutExpired:
            log.error("Timeout clearing dnsmasq config")
        except Exception as e:
            log.error(f"Error clearing dnsmasq config: {e}")

    def _restart_dnsmasq(self) -> None:
        """Restart dnsmasq service via sudo."""
        try:
            proc = subprocess.run(
                ["sudo", "/bin/systemctl", "restart", "dnsmasq"],
                capture_output=True,
                timeout=30,
            )
            if proc.returncode != 0:
                log.error(f"Failed to restart dnsmasq: {proc.stderr.decode()}")
            else:
                log.info("Restarted dnsmasq service")
        except subprocess.TimeoutExpired:
            log.error("Timeout restarting dnsmasq")
        except Exception as e:
            log.error(f"Error restarting dnsmasq: {e}")
