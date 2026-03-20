import ssl
import socket
from datetime import datetime

def check_ssl(hostname: str):
    try:
        context = ssl.create_default_context()
        with socket.create_connection((hostname, 443), timeout=10) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert = ssock.getpeercert()
                expiry_str = cert["notAfter"]
                expiry_date = datetime.strptime(
                    expiry_str, "%b %d %H:%M:%S %Y %Z"
                )
                days_left = (expiry_date - datetime.utcnow()).days
                return {
                    "valid": True,
                    "expiry_date": expiry_date.isoformat(),
                    "days_left": days_left,
                    "expired": days_left < 0,
                    "expiring_soon": days_left <= 30
                }
    except Exception as e:
        return {
            "valid": False,
            "expiry_date": None,
            "days_left": None,
            "expired": None,
            "expiring_soon": None,
            "error": str(e)
        }