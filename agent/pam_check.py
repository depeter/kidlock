#!/usr/bin/env python3
"""PAM check script for Kidlock - called during login to verify if user is allowed."""

import sys

from .enforcer import check_login_allowed


def main() -> int:
    """Check if a user is allowed to log in.

    Called by PAM during login. Reads username from command line argument.
    Returns 0 if allowed, 1 if denied.
    """
    if len(sys.argv) < 2:
        print("Usage: kidlock-pam-check <username>", file=sys.stderr)
        return 1

    username = sys.argv[1]
    allowed, reason = check_login_allowed(username)

    if not allowed:
        print(f"Kidlock: {reason}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
